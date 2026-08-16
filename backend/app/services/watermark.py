"""Canonical, server-rendered QC watermarking."""

from __future__ import annotations

import io
import re
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

_FACTORY_SUFFIX = re.compile(r"^(?P<contract>.+?)-(?P<factory>[A-Za-z]+)$")
_CONTRACT_PREFIX = re.compile(r"^(?P<year>\d{2})(?P<company>[A-Za-z]+)-(?P<employee>\d{2})(?P<code>[A-Za-z])(?P<order>\d+)$")
_FONT_PATHS = ("C:/Windows/Fonts/msyh.ttc", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")


class WatermarkError(ValueError):
    pass


def watermark_lines(contract_no: str, sequence_no: str | None, specification: str | None, captured_at: datetime) -> tuple[str, str, str]:
    return (
        format_contract(contract_no, sequence_no),
        format_specification(specification),
        captured_at.strftime("%Y.%m.%d %H:%M"),
    )


def format_contract(contract_no: str, sequence_no: str | None) -> str:
    normalized = re.sub(r"\s+", "", contract_no or "")
    match = _FACTORY_SUFFIX.fullmatch(normalized)
    factory = match.group("factory").upper() if match else ""
    core = match.group("contract") if match else normalized
    parsed = _CONTRACT_PREFIX.fullmatch(core)
    compact = (
        f"{parsed.group('year')}{parsed.group('company').upper()}{parsed.group('employee')}{parsed.group('code').upper()}{parsed.group('order')}"
        if parsed else core.replace("-", "").upper()
    )
    prefix = f"{factory}-" if factory else ""
    suffix = str(sequence_no).strip() if sequence_no is not None and str(sequence_no).strip() else ""
    return f"{prefix}{compact}{'-' + suffix if suffix else ''}"


def factory_initials(contract_no: str) -> str | None:
    match = _FACTORY_SUFFIX.fullmatch(re.sub(r"\s+", "", contract_no or ""))
    return match.group("factory").upper() if match else None


def format_specification(specification: str | None) -> str:
    """Join the first two whitespace-delimited spec tokens for the label."""
    tokens = (specification or "").strip().split()
    return "-".join(tokens[:2]) if tokens else "未填写规格"


def render_watermark(image_bytes: bytes, lines: tuple[str, str, str]) -> tuple[bytes, str]:
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source = source.convert("RGB")
            width, height = source.size
            font_size = max(20, min(54, round(min(width, height) * 0.045)))
            font = _font(font_size)
            spacing = max(5, font_size // 4)
            padding = max(18, font_size // 2)
            draw = ImageDraw.Draw(source)
            box = draw.multiline_textbbox((0, 0), "\n".join(lines), font=font, spacing=spacing, stroke_width=1)
            text_height = box[3] - box[1]
            x, y = padding, max(padding, height - text_height - padding)
            draw.multiline_text((x, y), "\n".join(lines), font=font, fill="white", spacing=spacing, stroke_width=max(1, font_size // 14), stroke_fill="black")
            output = io.BytesIO()
            source.save(output, format="JPEG", quality=92, optimize=True)
            return output.getvalue(), "image/jpeg"
    except UnidentifiedImageError as exc:
        raise WatermarkError("Unsupported image data") from exc


def render_thumbnail(image_bytes: bytes, max_size: int = 640) -> bytes:
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source = source.convert("RGB")
            source.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            source.save(output, format="JPEG", quality=84, optimize=True)
            return output.getvalue()
    except UnidentifiedImageError as exc:
        raise WatermarkError("Unsupported image data") from exc


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()
