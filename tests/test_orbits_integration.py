import io
import os
import struct
import wave
import zlib

import pytest

from core.orbits import build_default_orbits_registry, validate_asset
from core.orbits_runtime import run_isolated_orbits_processor


pytestmark = pytest.mark.skipif(
    not os.environ.get("ORACLE_ARC_ORBITS_WORKER_IMAGE"),
    reason="Requires the CI-built isolated ORBITS Podman image",
)


def _png(width=8, height=8):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">2I5B", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def _wav():
    stream = io.BytesIO()
    with wave.open(stream, "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00\x00" * 800)
    return stream.getvalue()


def test_isolated_orbits_document_processor_extracts_real_text():
    data = b"Oracle Arc document ingestion integration test."
    result = run_isolated_orbits_processor("document.extract", data)
    assert result["media_type"] == "document"
    assert result["text"] == data.decode()


def test_isolated_orbits_image_processor_decodes_and_ocr_checks_image():
    data = _png()
    asset = validate_asset(data, "blank.png", "image/png")
    result = build_default_orbits_registry().process("image.ocr", asset, data)
    assert result["media_type"] == "image"
    assert result["width"] == 8
    assert result["height"] == 8
    assert isinstance(result["text"], str)


def test_isolated_orbits_audio_processor_reads_real_wav_metadata():
    data = _wav()
    asset = validate_asset(data, "sample.wav", "audio/wav")
    result = build_default_orbits_registry().process("audio.inspect", asset, data)
    assert result["media_type"] == "audio"
    assert result["duration_seconds"] == pytest.approx(0.1, abs=0.01)
    assert result["sample_rate"] == 8000
    assert result["transcription"] is None
    assert result["transcription_status"] == "not_installed"
