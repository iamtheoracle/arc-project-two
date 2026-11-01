"""One-shot ORBITS media worker. Runs only inside the locked-down Podman image."""
from __future__ import annotations

import base64
import io
import json
import sys


def _document(data: bytes) -> dict:
    if data.startswith(b"%PDF-"):
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data), strict=True)
        if len(reader.pages) > 100:
            raise ValueError("PDF exceeds the 100-page processing limit")
        chunks = []
        total = 0
        for page in reader.pages:
            text = page.extract_text() or ""
            total += len(text)
            if total > 100_000:
                raise ValueError("Extracted PDF text exceeds 100 KB")
            chunks.append(text)
        return {"media_type": "document", "format": "application/pdf",
                "page_count": len(reader.pages), "text": "\n".join(chunks)}
    text = data.decode("utf-8")
    if len(text) > 100_000:
        raise ValueError("Text document exceeds 100 KB")
    return {"media_type": "document", "format": "text/plain", "page_count": 1, "text": text}


def _image(data: bytes) -> dict:
    from PIL import Image, ImageOps
    import pytesseract

    Image.MAX_IMAGE_PIXELS = 20_000_000
    with Image.open(io.BytesIO(data)) as source:
        source.verify()
    with Image.open(io.BytesIO(data)) as source:
        if source.width * source.height > 20_000_000:
            raise ValueError("Image exceeds the 20-megapixel processing limit")
        image = ImageOps.exif_transpose(source).convert("RGB")
        text = pytesseract.image_to_string(image, timeout=30)
    if len(text) > 100_000:
        raise ValueError("OCR output exceeds 100 KB")
    return {"media_type": "image", "format": "image-ocr",
            "width": image.width, "height": image.height, "text": text}


def _audio(data: bytes) -> dict:
    from mutagen import File as MutagenFile

    audio = MutagenFile(io.BytesIO(data), easy=True)
    if audio is None:
        raise ValueError("Audio container or codec is not supported")
    info = getattr(audio, "info", None)
    return {
        "media_type": "audio",
        "format": type(audio).__name__,
        "duration_seconds": round(float(info.length), 3) if info and info.length else None,
        "bitrate": int(info.bitrate) if info and info.bitrate else None,
        "sample_rate": int(info.sample_rate) if info and info.sample_rate else None,
        "channels": int(info.channels) if info and info.channels else None,
        "tags": {str(k)[:80]: [str(v)[:240] for v in list(values)[:5]]
                 for k, values in (audio.tags or {}).items()},
        "transcription": None,
        "transcription_status": "not_installed",
    }


def execute(payload: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"processor_id", "data_base64"}:
        raise ValueError("Invalid ORBITS worker request")
    processor_id = payload["processor_id"]
    if processor_id not in {"document.extract", "image.ocr", "audio.inspect"}:
        raise ValueError("Processor is not in the isolated worker allowlist")
    encoded = payload["data_base64"]
    if not isinstance(encoded, str) or len(encoded) > 36_000_000:
        raise ValueError("Encoded media exceeds the worker input budget")
    data = base64.b64decode(encoded, validate=True)
    if not data:
        raise ValueError("Media input is empty")
    if processor_id == "document.extract":
        return _document(data)
    if processor_id == "image.ocr":
        return _image(data)
    return _audio(data)


if __name__ == "__main__":
    try:
        request = json.load(sys.stdin)
        result = execute(request)
        encoded = json.dumps({"result": result}, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > 1_000_000:
            raise ValueError("ORBITS output exceeds one megabyte")
        print(encoded)
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__}))
        raise SystemExit(1)
