from datetime import datetime

from PIL import Image

from app.services.watermark import format_contract, format_specification, render_watermark, watermark_lines


def test_contract_watermark_formats_factory_and_sequence() -> None:
    assert format_contract("26MT-03T005-GYL", "1") == "GYL-26MT03T005-1"
    assert format_contract("26MT-03T005", "1") == "26MT03T005-1"


def test_specification_watermark_keeps_first_two_parts() -> None:
    assert format_specification("304 DN50") == "304-DN50"
    assert format_specification("ASTM A312 TP304 DN50") == "ASTM-A312"


def test_rendered_image_is_a_valid_jpeg() -> None:
    source = Image.new("RGB", (800, 1200), "gray")
    from io import BytesIO
    buffer = BytesIO()
    source.save(buffer, format="JPEG")
    image, content_type = render_watermark(buffer.getvalue(), watermark_lines("26MT-03T005-GYL", "1", "304 DN50", datetime(2026, 6, 10, 10, 36)))
    assert content_type == "image/jpeg"
    assert image.startswith(b"\xff\xd8\xff")
