#!/usr/bin/env python3
"""Smart Hearing Aid - 4-mic DOA + beamforming. Usage:
   python3 run.py                 # real hardware (ALSA I2S), dashboard on :8080
   python3 run.py --sim           # synthetic source, no hardware needed
   python3 run.py --wav in.wav    # replay a 4-channel recording
"""
import argparse, logging, sys
from ha import config
from ha.audio_source import ALSASource, SimSource, WavSource
from ha.pipeline import Pipeline
from ha.server import create_app

ap = argparse.ArgumentParser()
ap.add_argument("--config"); ap.add_argument("--sim", action="store_true"); ap.add_argument("--wav")
ap.add_argument("--port", type=int); ap.add_argument("--playback", action="store_true")
a = ap.parse_args()
cfg = config.load(a.config)
if a.playback: cfg["output"]["playback"] = True
src = SimSource(cfg) if a.sim or cfg["source"] == "sim" else WavSource(cfg, a.wav) if a.wav else ALSASource(cfg)
pipe = Pipeline(cfg, src); pipe.start()
logging.getLogger("werkzeug").setLevel(logging.ERROR)
port = a.port or cfg["dashboard"]["port"]
print(f"Dashboard: http://<pi-ip>:{port}   (source: {src.name})", flush=True)
create_app(pipe).run(host=cfg["dashboard"]["host"], port=port, threaded=True)
