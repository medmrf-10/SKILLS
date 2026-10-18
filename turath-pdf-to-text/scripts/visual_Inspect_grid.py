#!/usr/bin/env python3
"""
Visual Inspection Grid Generator for Heritage Arabic Pages (`turath-pdf-to-text`)
=================================================================================
Overlays horizontal & vertical percentage grid lines and multi-zone boundary lines
(`header`, `matn_top`, `sharh_body`, `footnotes`, `margin_notes`) onto rendered
page images to inspect layout zones visually and verify separator detection.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageDraw
except ImportError:
    Image = None
    ImageDraw = None


def detect_zone_ratios(img: "Image.Image") -> Dict[str, Tuple[float, float]]:
    """
    Detect vertical ratios `(y_start_ratio, y_end_ratio)` for multi-zone heritage
    pages (`header`, `matn_top`, `sharh_body`, `footnotes`).
    """
    gray = img.convert("L")
    w, h = gray.size
    pixels = gray.load()
    margin_x = int(w * 0.12)
    scan_w = max(1, w - 2 * margin_x)

    row_ink: List[float] = []
    for y in range(h):
        dark = 0
        for x in range(margin_x, w - margin_x, 2):
            if pixels[x, y] < 185:
                dark += 1
        row_ink.append(dark / (scan_w / 2.0))

    header_cut = int(h * 0.08)
    for y in range(int(h * 0.04), int(h * 0.14)):
        if row_ink[y] < 0.008:
            header_cut = y
            break

    fn_cut = int(h * 0.78)
    for y in range(int(h * 0.48), int(h * 0.88)):
        if 0.12 < row_ink[y] < 0.55:
            above = sum(row_ink[max(0, y - 8) : y]) / 8.0
            below = sum(row_ink[y + 1 : min(h, y + 9)]) / 8.0
            if above < 0.03 and below < 0.03:
                fn_cut = y
                break

    # Detect optional Matn/Sharh divider in upper-middle region (20%..55%)
    matn_sharh_cut: Optional[int] = None
    for y in range(int(h * 0.20), min(fn_cut - int(h * 0.08), int(h * 0.55))):
        if 0.10 < row_ink[y] < 0.50:
            above = sum(row_ink[max(0, y - 6) : y]) / 6.0
            below = sum(row_ink[y + 1 : min(h, y + 7)]) / 6.0
            if above < 0.025 and below < 0.025:
                matn_sharh_cut = y
                break

    zones: Dict[str, Tuple[float, float]] = {
        "header": (0.0, round(header_cut / h, 4)),
    }
    if matn_sharh_cut is not None:
        zones["matn_top"] = (round(header_cut / h, 4), round(matn_sharh_cut / h, 4))
        zones["sharh_body"] = (round(matn_sharh_cut / h, 4), round(fn_cut / h, 4))
    else:
        zones["body"] = (round(header_cut / h, 4), round(fn_cut / h, 4))
    zones["footnotes"] = (round(fn_cut / h, 4), 1.0)
    return zones


def render_inspection_grid(
    image_path: str,
    output_path: str,
    step_pct: int = 10,
) -> Dict[str, Tuple[float, float]]:
    """
    Draw a visual inspection grid and detected multi-zone boundaries on `image_path`
    and save to `output_path`.
    """
    if Image is None:
        raise RuntimeError("Pillow (PIL) is required for visual_Inspect_grid.py")

    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    draw = ImageDraw.Draw(img)

    for pct in range(step_pct, 100, step_pct):
        y = int(h * (pct / 100.0))
        x = int(w * (pct / 100.0))
        draw.line([(0, y), (w, y)], fill=(200, 200, 200), width=1)
        draw.line([(x, 0), (x, h)], fill=(200, 200, 200), width=1)

    zones = detect_zone_ratios(img)
    colors = {
        "header": (0, 120, 255),
        "matn_top": (0, 180, 80),
        "sharh_body": (255, 140, 0),
        "body": (255, 140, 0),
        "footnotes": (220, 30, 60),
    }
    for z_name, (y0_r, y1_r) in zones.items():
        y0 = int(h * y0_r)
        y1 = int(h * y1_r)
        col = colors.get(z_name, (128, 0, 128))
        draw.rectangle([(4, y0 + 2), (w - 4, max(y0 + 4, y1 - 2))], outline=col, width=3)

    img.save(output_path)
    return zones


def main() -> int:
    parser = argparse.ArgumentParser(description="Overlay visual inspection grid & multi-zone boundaries.")
    parser.add_argument("image_path", help="Input page image PNG/JPG")
    parser.add_argument("-o", "--output", help="Output grid image path")
    args = parser.parse_args()

    out = args.output or str(Path(args.image_path).with_name(Path(args.image_path).stem + "_grid.png"))
    zones = render_inspection_grid(args.image_path, out)
    print(json.dumps({"output": out, "zones": zones}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
