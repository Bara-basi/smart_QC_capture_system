#!/usr/bin/env python3
"""Render a diagnostic watermark image in an isolated test container."""

from __future__ import annotations

import io
from datetime import datetime

from PIL import Image

from app.services.watermark import render_watermark, watermark_lines

source = Image.new("RGB", (1000, 750), (125, 135, 140))
buffer = io.BytesIO()
source.save(buffer, format="JPEG")
output, _ = render_watermark(
    buffer.getvalue(),
    watermark_lines(
        "26MT-03T005-GYL",
        "1",
        "304 未填写规格",
        datetime(2026, 10, 22, 10, 30),
    ),
)
with open("/tests/qa-watermark-font.jpg", "wb") as image_file:
    image_file.write(output)
print("wrote /tests/qa-watermark-font.jpg")
