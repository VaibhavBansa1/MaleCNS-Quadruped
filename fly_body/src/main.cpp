// Four-leg walking gait for an ESP32 + PCA9685 (PlatformIO / Arduino framework).
// Serial commands (115200 baud, one per line):
//   F  forward     B  backward     L  turn left     R  turn right     S  stop
//   H <deg>  head angle 0..180     A <deg>  step size    P <ms>  step period
//   D <pct>  stance percent (50..80)    W <ms>  watchdog (0 = off)
//   M 1 / M 0  start / stop sending microphone levels (see mic.cpp)
//   E <mode> <steer> <escape>   status from the PC for the face and head:
//            mode 1 = brain, 0 = manual; steer -1 (left) .. +1 (right); escape 1/0
//   T <n>    test: leg n (0..3) swings to ITS "forward" for 1.5 s, others stay at 90.
//            Use it to see which physical leg is on which channel, and which way
//            the code thinks is forward for it.
// Later, the fly-brain program on the PC sends the same commands.

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include "mic.h"
#include "face.h"

Adafruit_PWMServoDriver pwm(0x40);

// ---- Edit these to match your robot ---------------------------------------
// Leg order everywhere: 0 = front-left, 1 = front-right, 2 = back-left, 3 = back-right
const int LEG_CH[4] = {0, 1, 2, 3};      // PCA9685 channel of each leg servo
const int HEAD_CH   = 4;                 // 180 degree head servo
const int HEAD_SIGN = -1;                // flipped: with +1 the head turned right on a LEFT command
const float HEAD_RANGE = 60.0f;          // degrees either side at full steer
// The robot was turned around (head end is now the front), so every sign was flipped.
int SIDE_SIGN[4]    = {-1, 1, -1, 1};    // flip a sign if that leg swings the wrong way
int TRIM_US[4]      = {0, 0, 0, 0};      // per-servo centre trim in microseconds
// ----------------------------------------------------------------------------

// Which side each leg is on. Turning the robot around swaps left and right,
// so this is back to channels 0 and 2 on the left.
const bool  IS_LEFT[4]      = {true, false, true, false};
const float PHASE_OFFSET[4] = {0.0f, 0.5f, 0.5f, 0.0f};  // diagonal pairs move together

float ampDeg   = 25.0f;     // how far each leg swings from centre
float periodMs = 1200.0f;   // time for one full step cycle
float duty     = 0.65f;     // fraction of the cycle spent pushing (slow stroke)
unsigned long watchdogMs = 0;

const float MAX_DPS = 300.0f;            // servo speed limit, softens jerks and current spikes
const unsigned long TICK_MS = 20;        // 50 Hz, same as the servo frame rate

enum Mode { STOP, FWD, BACK, LEFT, RIGHT };
Mode mode = STOP;

float curAngle[4] = {90, 90, 90, 90};
float phase = 0.0f;
unsigned long lastTick = 0;
unsigned long lastCmd = 0;
float headTarget = 90.0f, headAngle = 90.0f;
int testLeg = -1;                 // leg being tested with T, -1 = none
unsigned long testUntil = 0;

int angleToUs(float a) {
  return (int)(500.0f + a * (2000.0f / 180.0f));   // 90 deg = 1500 us
}

// +1 = leg fully forward, -1 = fully back. Slow push stroke, fast return stroke.
float wave(float p, float d) {
  if (p < d) return 1.0f - 2.0f * (p / d);
  return -1.0f + 2.0f * ((p - d) / (1.0f - d));
}

void writeLeg(int i) {
  int us = angleToUs(curAngle[i]) + TRIM_US[i];
  pwm.writeMicroseconds(LEG_CH[i], constrain(us, 600, 2400));
}

void setHead(float deg) {
  deg = constrain(deg, 0.0f, 180.0f);
  int us = (int)(500.0f + deg * (2000.0f / 180.0f));
  pwm.writeMicroseconds(HEAD_CH, constrain(us, 500, 2500));
}

// Moves the head smoothly towards headTarget (90 degrees per second at most).
void updateHead(float dt) {
  float step = 90.0f * dt;
  headAngle += constrain(headTarget - headAngle, -step, step);
  setHead(headAngle);
}

void updateGait(float dt) {
  float dirL = 0, dirR = 0;
  switch (mode) {
    case FWD:   dirL =  1; dirR =  1; break;
    case BACK:  dirL = -1; dirR = -1; break;
    case LEFT:  dirL = -1; dirR =  1; break;
    case RIGHT: dirL =  1; dirR = -1; break;
    default: break;
  }

  if (mode != STOP) {
    phase += dt * 1000.0f / periodMs;
    phase -= floorf(phase);
  }

  for (int i = 0; i < 4; i++) {
    float target = 90.0f;
    if (mode == STOP && i == testLeg && millis() < testUntil) {
      target = 90.0f + SIDE_SIGN[i] * 30.0f;     // this leg's "forward"
    }
    if (mode != STOP) {
      float p = phase + PHASE_OFFSET[i];
      p -= floorf(p);
      float dir = IS_LEFT[i] ? dirL : dirR;
      target = 90.0f + SIDE_SIGN[i] * dir * wave(p, duty) * ampDeg;
    }
    float maxStep = MAX_DPS * dt;
    float diff = constrain(target - curAngle[i], -maxStep, maxStep);
    curAngle[i] += diff;
    writeLeg(i);
  }
}

void setMode(Mode m, const char *name) {
  mode = m;
  const char letters[] = {'S', 'F', 'B', 'L', 'R'};
  faceSetCommand(letters[m]);
  lastCmd = millis();
  Serial.print("mode: ");
  Serial.println(name);
}

void handleLine(String s) {
  s.trim();
  if (s.length() == 0) return;
  char c = toupper(s[0]);
  float v = s.substring(1).toFloat();
  faceTouch();

  switch (c) {
    case 'F': setMode(FWD, "forward"); break;
    case 'B': setMode(BACK, "backward"); break;
    case 'L': setMode(LEFT, "turn left"); break;
    case 'R': setMode(RIGHT, "turn right"); break;
    case 'S': setMode(STOP, "stop"); break;
    case 'H': headTarget = constrain(v, 0.0f, 180.0f); break;
    case 'E': {
      int brain = 0, escape = 0;
      float steer = 0.0f;
      sscanf(s.c_str() + 1, "%d %f %d", &brain, &steer, &escape);
      steer = constrain(steer, -1.0f, 1.0f);
      faceSetStatus(brain == 1, steer, escape == 1);
      headTarget = 90.0f + HEAD_SIGN * steer * HEAD_RANGE;
      break;
    }
    case 'A': ampDeg = constrain(v, 5.0f, 40.0f); Serial.print("amp "); Serial.println(ampDeg); break;
    case 'P': periodMs = constrain(v, 400.0f, 3000.0f); Serial.print("period "); Serial.println(periodMs); break;
    case 'D': duty = constrain(v, 50.0f, 80.0f) / 100.0f; Serial.print("duty "); Serial.println(duty); break;
    case 'T':
      testLeg = constrain((int)v, 0, 3);
      testUntil = millis() + 1500;
      mode = STOP;
      Serial.print("testing leg ");
      Serial.print(testLeg);
      Serial.print(" on channel ");
      Serial.println(LEG_CH[testLeg]);
      break;
    case 'M': micSetStreaming(v > 0.5f); break;
    case 'W': watchdogMs = (unsigned long)max(v, 0.0f); Serial.print("watchdog ms "); Serial.println(watchdogMs); break;
    default: Serial.println("unknown command"); break;
  }
}

void setup() {
  Serial.begin(115200);
  Serial.setTimeout(50);   // never wait long for a half-received command
  Wire.begin(21, 22);
  pwm.begin();
  pwm.setOscillatorFrequency(27000000);
  pwm.setPWMFreq(50);
  delay(10);

  for (int i = 0; i < 4; i++) {
    writeLeg(i);
    delay(250);
  }
  setHead(90);

  micBegin();
  faceBegin();
  Serial.println("Ready. F B L R S, H <deg>, A <deg>, P <ms>, D <pct>, W <ms>, M 1/0, E m s e");
  lastTick = millis();
}

void loop() {
  if (Serial.available()) {
    handleLine(Serial.readStringUntil('\n'));
  }

  unsigned long now = millis();
  if (now - lastTick >= TICK_MS) {
    float dt = (now - lastTick) / 1000.0f;
    lastTick = now;

    if (watchdogMs > 0 && mode != STOP && now - lastCmd > watchdogMs) {
      mode = STOP;
      Serial.println("watchdog: stop");
    }
    updateGait(dt);
    updateHead(dt);
  }

  micReport();
}