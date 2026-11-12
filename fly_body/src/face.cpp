// The robot's OLED face: a fruit fly seen from the front.
//
// What it draws (128 x 64 pixels):
//   yellow strip, rows 0-15:  the command in big letters, B or M (brain / manual) on the right
//   blue area,   rows 16-63:  the fly's face
//     - two big compound eyes, white with a pattern of dots for the facets (ommatidia)
//     - a dark spot in each eye: the "pseudopupil". Real fly eyes show one, and it
//       seems to follow you. Here it moves left/right with the steering signal.
//     - antennae with feathery aristae on top, the proboscis (mouthpart) below
//   escape:          eyes grow, antennae go up, "ESCAPE!"
//   no PC messages:  eyes become outlines (asleep), "NO SIGNAL"
//
// Wiring (power comes from a GPIO pin, no soldering):
//   OLED VCC -> GPIO 23 (the code switches it on, 3.3 V, the screen draws ~10-20 mA)
//   OLED GND -> any GND
//   OLED SDA -> GPIO 18
//   OLED SCL -> GPIO 19
// It uses the ESP32's second I2C bus (Wire1), separate from the servo driver on 21/22.
// If the screen is missing, the robot still walks; a warning is printed.

#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "driver/gpio.h"
#include "face.h"

const int OLED_SDA = 18;
const int OLED_SCL = 19;
const int OLED_POWER = 23;
const uint8_t OLED_ADDRESS = 0x3C;      // most of these screens; some are 0x3D
const unsigned long NO_SIGNAL_MS = 1500;
// The screen faces the people in FRONT of the robot, so it is a mirror:
// the robot's left is the viewer's right. -1 makes the eyes move towards the
// robot's own turning side as seen from the front. Use 1 if the screen faces backwards.
const int FACE_MIRROR = -1;

static Adafruit_SSD1306 oled(128, 64, &Wire1, -1, 400000UL, 400000UL);

static volatile char faceCommand = 'S';
static volatile bool faceBrain = false;
static volatile float faceSteer = 0.0f;   // -1 = left ... +1 = right
static volatile bool faceEscape = false;
static volatile unsigned long faceLast = 0;

// Ovals drawn by hand (the graphics library only has circles).
static void fillOval(int cx, int cy, int rx, int ry, uint16_t color) {
  for (int y = -ry; y <= ry; y++) {
    float f = 1.0f - float(y * y) / float(ry * ry);
    int half = (int)(rx * sqrtf(f > 0 ? f : 0));
    oled.drawFastHLine(cx - half, cy + y, 2 * half + 1, color);
  }
}

static void drawOval(int cx, int cy, int rx, int ry, uint16_t color) {
  for (int i = 0; i < 160; i++) {
    float t = i * (2.0f * PI / 160.0f);
    oled.drawPixel(cx + (int)roundf(rx * cosf(t)), cy + (int)roundf(ry * sinf(t)), color);
  }
}

// One compound eye: a filled oval with dark dots for facets, and the pseudopupil.
static void drawEye(int cx, int cy, int rx, int ry, int look, bool awake) {
  if (!awake) {
    drawOval(cx, cy, rx, ry, SSD1306_WHITE);
    oled.drawLine(cx - rx + 4, cy, cx + rx - 4, cy, SSD1306_WHITE);   // closed eye
    return;
  }
  fillOval(cx, cy, rx, ry, SSD1306_WHITE);
  for (int y = cy - ry + 3; y <= cy + ry - 3; y += 4) {
    int shift = ((y - cy) / 4) % 2 ? 2 : 0;                           // honeycomb rows
    for (int x = cx - rx + 3 + shift; x <= cx + rx - 3; x += 4) {
      float dx = float(x - cx) / (rx - 2), dy = float(y - cy) / (ry - 2);
      if (dx * dx + dy * dy < 1.0f) oled.drawPixel(x, y, SSD1306_BLACK);
    }
  }
  oled.fillCircle(cx + look, cy, 4, SSD1306_BLACK);                   // pseudopupil
}

static void drawFace(int dx, bool escape, bool awake, int look) {
  int cx = 64 + dx;
  int rx = escape ? 19 : 16, ry = escape ? 21 : 18;
  drawEye(cx - 22, 40, rx, ry, look, awake);
  drawEye(cx + 22, 40, rx, ry, look, awake);

  // Middle of the head between the eyes.
  oled.drawRoundRect(cx - 5, 30, 10, 20, 4, SSD1306_WHITE);

  // Antennae with feathery aristae; raised when escaping.
  int tipY = escape ? 18 : 22;
  oled.drawLine(cx - 3, 30, cx - 7, tipY, SSD1306_WHITE);
  oled.drawLine(cx + 3, 30, cx + 7, tipY, SSD1306_WHITE);
  oled.drawLine(cx - 7, tipY, cx - 12, tipY - 1, SSD1306_WHITE);
  oled.drawLine(cx + 7, tipY, cx + 12, tipY - 1, SSD1306_WHITE);
  oled.drawPixel(cx - 10, tipY - 2, SSD1306_WHITE);
  oled.drawPixel(cx + 10, tipY - 2, SSD1306_WHITE);

  // Proboscis.
  oled.drawLine(cx, 50, cx, 59, SSD1306_WHITE);
  oled.drawLine(cx, 59, cx - 3, 62, SSD1306_WHITE);
  oled.drawLine(cx, 59, cx + 3, 62, SSD1306_WHITE);
}

static const char *wordFor(char c) {
  switch (c) {
    case 'F': return "FORWARD";
    case 'B': return "BACK";
    case 'L': return "LEFT";
    case 'R': return "RIGHT";
    default:  return "STOP";
  }
}

static void faceTask(void *) {
  char lastWord[16] = "";
  int lastKey = -9999;
  for (;;) {
    bool awake = millis() - faceLast < NO_SIGNAL_MS;
    bool escape = awake && faceBrain && faceEscape;
    float steer = FACE_MIRROR * constrain((float)faceSteer, -1.0f, 1.0f);
    int dx = (int)roundf(steer * 10.0f);       // whole face leans towards the turn
    int look = (int)roundf(steer * 6.0f);      // pseudopupil moves further

    const char *word = !awake ? "NO SIGNAL" : (escape ? "ESCAPE!" : wordFor(faceCommand));
    int key = dx * 1000 + look * 10 + (escape ? 1 : 0) + (awake ? 2 : 0) + (faceBrain ? 4 : 0);

    if (key != lastKey || strcmp(word, lastWord) != 0) {   // redraw only on change
      oled.clearDisplay();
      oled.setTextColor(SSD1306_WHITE);
      oled.setTextSize(2);
      oled.setCursor(0, 0);
      oled.print(word);
      if (awake) {
        oled.setTextSize(1);
        oled.setCursor(122, 4);
        oled.print(faceBrain ? 'B' : 'M');
      }
      drawFace(dx, escape, awake, look);
      oled.display();
      strncpy(lastWord, word, sizeof(lastWord) - 1);
      lastKey = key;
    }
    vTaskDelay(pdMS_TO_TICKS(60));
  }
}

void faceBegin() {
  pinMode(OLED_POWER, OUTPUT);
  gpio_set_drive_capability((gpio_num_t)OLED_POWER, GPIO_DRIVE_CAP_3);   // strongest drive
  digitalWrite(OLED_POWER, HIGH);
  delay(100);                                                           // let the screen start

  Wire1.begin(OLED_SDA, OLED_SCL, 400000);
  // periphBegin = false: we already started Wire1 on our own pins.
  if (!oled.begin(SSD1306_SWITCHCAPVCC, OLED_ADDRESS, true, false)) {
    Serial.println("face: OLED not found (check wiring or try address 0x3D); robot works without it");
    return;
  }
  oled.clearDisplay();
  oled.display();
  xTaskCreatePinnedToCore(faceTask, "face", 4096, nullptr, 1, nullptr, 0);
  Serial.println("face: OLED ready");
}

void faceSetCommand(char letter) { faceCommand = letter; }

void faceSetStatus(bool brainMode, float steer, bool escape) {
  faceBrain = brainMode;
  faceSteer = steer;
  faceEscape = escape;
}

void faceTouch() { faceLast = millis(); }
