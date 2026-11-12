// Robot microphones: purple MAX4466 (left ear) and red KY-037 AO (right ear).
// Runs on its own core so sampling never disturbs the legs.
#pragma once

void micBegin();                 // call once in setup()
void micSetStreaming(bool on);   // PC sends "M 1" / "M 0"
void micReport();                // call every loop(); prints "M songL fastL songR fastR" 20x a second
