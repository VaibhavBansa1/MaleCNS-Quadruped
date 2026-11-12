# fly_body: the robot firmware

PlatformIO project for an ESP32 + PCA9685 four-legged robot.

* `src/main.cpp`: diagonal walking gait, serial commands (F B L R S ...),
  head servo, 500 ms watchdog.
* `src/face.cpp`: animated fruit-fly face on a 0.96" SSD1306 OLED (second I2C bus).
* `src/mic.cpp`: optional on-robot microphones (GPIO34 / GPIO35).

Open this folder in VS Code with the PlatformIO extension, plug in the ESP32, and
press Upload. Libraries are fetched automatically from `platformio.ini`.

Wiring, settings and the full command list: [docs/HARDWARE.md](../docs/HARDWARE.md).
