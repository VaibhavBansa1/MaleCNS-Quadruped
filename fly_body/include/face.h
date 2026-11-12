// The robot's OLED face (0.96" 128x64 SSD1306, yellow strip on top, blue below).
// Runs in its own task so drawing never slows the legs.
#pragma once

void faceBegin();                                          // call once in setup()
void faceSetCommand(char letter);                          // F B L R S
void faceSetStatus(bool brainMode, float steer, bool escape); // from the PC's E line
void faceTouch();                                          // any message from the PC
