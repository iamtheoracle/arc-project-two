#!/usr/bin/env python3
"""Run an actual local, offline ORBITS speech-to-text inference on a supplied audio file."""
from __future__ import annotations

import argparse
from pathlib import Path

from core.orbits import validate_asset
from core.orbits_asr_runtime import run_local_asr


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_file")
    args = parser.parse_args()
    path = Path(args.audio_file).expanduser().resolve(strict=True)
    data = path.read_bytes()
    asset = validate_asset(data, path.name)
    if asset.media_type != "audio":
        raise SystemExit("Input file is not a supported audio format.")
    result = run_local_asr(data)
    if result.get("transcription_status") != "completed" or result.get("inference_location") != "local":
        raise SystemExit("ASR did not return a verified local transcription.")
    print(result["text"])


if __name__ == "__main__":
    main()
