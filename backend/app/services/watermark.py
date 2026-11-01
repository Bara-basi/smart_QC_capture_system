"""Canonical, server-rendered QC watermarking."""

from __future__ import annotations

import io
import re
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

_FACTORY_SUFFIX = re.compile(r"^(?P<contract>.+?)-(?P<factory>[A-Za-z]+)$")
_CONTRACT_PREFIX = re.compile(r"^(?P<year>\d{2})(?P<company>[A-Za-z]+)-(?P<employee>\d{2})(?P<code>[A-Za-z])(?P<order>\d+)$")
_FONT_PATHS = (
    "C:/Windows/Fonts/msyh.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


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
            source = ImageOps.exif_transpose(source).convert("RGB")
            width, height = source.size
            font_size = watermark_font_size(width, height)
            font = _font(font_size)
            spacing = max(5, font_size // 4)
            padding = max(18, font_size // 3)
            draw = ImageDraw.Draw(source)
            stroke_width = max(1, font_size // 14)
            watermark_text = _wrap_watermark_lines(draw, lines, font, width - padding * 2, stroke_width)
            box = draw.multiline_textbbox(
                (0, 0), watermark_text, font=font, spacing=spacing, stroke_width=stroke_width,
            )
            x, y = padding - box[0], max(padding - box[1], height - box[3] - padding)
            draw.multiline_text(
                (x, y), watermark_text, font=font, fill="white", spacing=spacing,
                stroke_width=stroke_width, stroke_fill="black",
            )
            return _jpeg_bytes(source, quality=92), "image/jpeg"
    except UnidentifiedImageError as exc:
        raise WatermarkError("Unsupported image data") from exc


def render_unwatermarked(image_bytes: bytes) -> tuple[bytes, str]:
    """Normalize an upload to the exact image that was captured, without overlays."""
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            return _jpeg_bytes(source, quality=95), "image/jpeg"
    except UnidentifiedImageError as exc:
        raise WatermarkError("Unsupported image data") from exc


def watermark_font_size(width: int, height: int) -> int:
    """Use 1.5 times the former font size, half of the previous enlarged label."""
    previous_size = max(20, min(54, round(min(width, height) * 0.045)))
    return previous_size * 3 // 2


def _wrap_watermark_lines(
    draw: ImageDraw.ImageDraw,
    lines: tuple[str, str, str],
    font: ImageFont.FreeTypeFont,
    max_width: int,
    stroke_width: int,
) -> str:
    """Wrap oversized labels while retaining the enlarged font size."""
    wrapped: list[str] = []
    for line in lines:
        if draw.textlength(line, font=font) <= max_width:
            wrapped.append(line)
            continue
        current = ""
        for word in line.split():
            candidate = f"{current} {word}".strip()
            if draw.textlength(candidate, font=font) + stroke_width * 2 <= max_width:
                current = candidate
                continue
            if current:
                wrapped.append(current)
                current = ""
            for character in word:
                candidate = current + character
                if current and draw.textlength(candidate, font=font) + stroke_width * 2 > max_width:
                    wrapped.append(current.rstrip())
                    current = character
                else:
                    current = candidate
        if current:
            wrapped.append(current)
    return "\n".join(wrapped)


def render_thumbnail(image_bytes: bytes, max_size: int = 640) -> bytes:
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source = ImageOps.exif_transpose(source).convert("RGB")
            source.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
            return _jpeg_bytes(source, quality=84)
    except UnidentifiedImageError as exc:
        raise WatermarkError("Unsupported image data") from exc


def _jpeg_bytes(source: Image.Image, *, quality: int) -> bytes:
    output = io.BytesIO()
    source.save(output, format="JPEG", quality=quality, optimize=True)
    return output.getvalue()


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in _FONT_PATHS:
        try:
            return ImageFont.truetype(path, size=size)
        except OSError:
            continue
    return ImageFont.load_default()
