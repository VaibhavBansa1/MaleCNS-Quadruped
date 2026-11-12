# fly-vision: the brain side

Python code that runs on the PC. It feeds a webcam and a microphone into the
MaleCNS v1.0 fruit-fly connectome (through `flybrain`) and turns the brain's
behaviour neurons into robot commands.

* `live/`: the live robot program. Start with `live/run_live.py`.
  Every file explains itself at the top and can be run alone.
  Plain-language guide: [live/GUIDE.md](live/GUIDE.md).
* `fly_pipeline.py`: offline experiments, video -> brain -> trained readout.
  The live code reuses its `FeatureRoute` and `EarRoute`.
* `visual_spike_encoder.py`, `audio_spike_encoder.py`: video and audio encoders.
* `inspect_pipeline.py`: prints every stage for debugging.
* `fly_body.py`: drives the simulated MuJoCo fly from the brain. It needs the separate
  male-cns-arena environment (MuJoCo + FlyGym), which is not included here.

Setup and commands: see the [main README](../README.md#quick-start).
