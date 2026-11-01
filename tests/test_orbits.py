import pytest

from core.orbits import (
    OrbitAssetRejected, OrbitProcessorRegistry, OrbitProcessorUnavailable,
    validate_asset,
)


def test_orbits_detects_image_audio_and_pdf_types():
    assert validate_asset(b"\x89PNG\r\n\x1a\npayload", "image.png").media_type == "image"
    assert validate_asset(b"ID3payload", "voice.mp3").mime_type == "audio/mpeg"
    assert validate_asset(b"%PDF-payload", "paper.pdf").mime_type == "application/pdf"


def test_orbits_rejects_mime_spoofing_active_content_and_path_traversal():
    with pytest.raises(OrbitAssetRejected):
        validate_asset(b"\x89PNG\r\n\x1a\npayload", "image.png", "text/html")
    with pytest.raises(OrbitAssetRejected):
        validate_asset(b"<svg><script>alert(1)</script></svg>", "vector.svg")
    with pytest.raises(OrbitAssetRejected):
        validate_asset(b"\xef\xbb\xbf<svg><script>blocked</script></svg>", "bom.svg")
    with pytest.raises(OrbitAssetRejected):
        validate_asset(b"<!-- header --><html><script>blocked</script></html>", "comment.html")
    with pytest.raises(OrbitAssetRejected):
        validate_asset(b"PK\x03\x04archive", "archive.docx")
    with pytest.raises(OrbitAssetRejected):
        validate_asset(b"%PDF-payload", "../secret.pdf")


def test_orbits_processors_are_platform_installed_and_isolation_required():
    registry = OrbitProcessorRegistry()
    with pytest.raises(PermissionError):
        registry.register("image.ocr", "image", 1000, lambda *_: {}, isolated=False)

    registry.register(
        "image.inspect", "image", 1000,
        lambda asset, data: {"asset_id": asset.asset_id, "bytes": len(data)},
        isolated=True,
    )
    data = b"\x89PNG\r\n\x1a\npayload"
    asset = validate_asset(data, "image.png")
    assert registry.process("image.inspect", asset, data)["asset_id"] == asset.asset_id


def test_orbits_requires_installed_processor_and_rechecks_asset_digest():
    registry = OrbitProcessorRegistry()
    data = b"%PDF-payload"
    asset = validate_asset(data, "paper.pdf")
    with pytest.raises(OrbitProcessorUnavailable):
        registry.process("document.extract", asset, data)

    registry.register("pdf.extract", "document", 1000, lambda *_: {"text": "ok"}, isolated=True)
    with pytest.raises(OrbitAssetRejected):
        registry.process("pdf.extract", asset, data + b"tampered")
