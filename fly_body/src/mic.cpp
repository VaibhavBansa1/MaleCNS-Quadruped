// Robot microphones -> fly-ear band levels.
//
// Samples both mics 4000 times a second on core 0 (the legs run on core 1).
// Every 50 ms it reports how loud each mic was in the two bands a fly hears:
//   song  100-350 Hz  -> Johnston's organ JO-B
//   fast  350-900 Hz  -> JO-A
// Output line (only after the PC sends "M 1"):
//   M <songLeft> <fastLeft> <songRight> <fastRight>
// The numbers are raw loudness. The PC compares them with the quiet room,
// which also evens out the two different mic boards.
//
// Wiring:
//   purple MAX4466: VCC -> 3.3V, GND -> GND, OUT -> GPIO 34   (left ear)
//   red KY-037:     +   -> 3.3V, G   -> GND, AO  -> GPIO 35   (right ear)
// GPIO 34/35 are ADC1 pins, which keep working even if WiFi is ever turned on.

#include <Arduino.h>
#include "mic.h"

const int MIC_PIN[2] = {34, 35};          // 0 = left, 1 = right
const float SAMPLE_HZ = 4000.0f;
const int WINDOW = 200;                    // 200 samples at 4 kHz = 50 ms

// A band-pass filter (standard "biquad" recipe). Lets one band through.
struct BandPass {
  float b0, b2, a1, a2;
  float z1 = 0, z2 = 0;

  void setup(float centreHz, float q) {
    float w0 = 2.0f * PI * centreHz / SAMPLE_HZ;
    float alpha = sinf(w0) / (2.0f * q);
    float a0 = 1.0f + alpha;
    b0 = alpha / a0;
    b2 = -alpha / a0;
    a1 = -2.0f * cosf(w0) / a0;
    a2 = (1.0f - alpha) / a0;
  }

  float run(float x) {
    float y = b0 * x + z1;
    z1 = -a1 * y + z2;
    z2 = b2 * x - a2 * y;
    return y;
  }
};

volatile float micLevel[4] = {0, 0, 0, 0};   // songL, fastL, songR, fastR
volatile bool micFresh = false;
bool micStreaming = false;

static void micTask(void *) {
  BandPass song[2], fast[2];
  for (int ch = 0; ch < 2; ch++) {
    song[ch].setup(187.0f, 0.75f);   // centre of 100-350 Hz
    fast[ch].setup(561.0f, 1.0f);    // centre of 350-900 Hz
  }
  float dc[2] = {2048.0f, 2048.0f};  // the mics sit at about half supply when silent
  float sum[4] = {0, 0, 0, 0};
  int count = 0;
  const unsigned long periodUs = (unsigned long)(1000000.0f / SAMPLE_HZ);
  unsigned long next = micros();

  for (;;) {
    for (int ch = 0; ch < 2; ch++) {
      float x = analogRead(MIC_PIN[ch]);
      dc[ch] += 0.001f * (x - dc[ch]);          // slowly track the silent level
      float v = x - dc[ch];
      float s = song[ch].run(v);
      float f = fast[ch].run(v);
      sum[ch * 2] += s * s;
      sum[ch * 2 + 1] += f * f;
    }

    if (++count >= WINDOW) {
      for (int k = 0; k < 4; k++) {
        micLevel[k] = sqrtf(sum[k] / WINDOW);   // RMS loudness in this band
        sum[k] = 0;
      }
      count = 0;
      micFresh = true;
      vTaskDelay(1);                            // let the system breathe (watchdog)
      next = micros();
    }

    next += periodUs;
    while ((long)(micros() - next) < 0) { }     // wait for the next sample time
  }
}

void micBegin() {
  analogReadResolution(12);
  analogSetAttenuation(ADC_11db);               // full 0..3.3 V range
  xTaskCreatePinnedToCore(micTask, "mic", 4096, nullptr, 1, nullptr, 0);
}

void micSetStreaming(bool on) {
  micStreaming = on;
}

void micReport() {
  if (!micStreaming || !micFresh) return;
  micFresh = false;
  Serial.printf("M %.2f %.2f %.2f %.2f\n", micLevel[0], micLevel[1], micLevel[2], micLevel[3]);
}
