#!/usr/bin/env python3
"""
High-Resolution Quadrant & Multi-Zone Cropper (`turath-pdf-to-text`)
===================================================================
Crops a heritage manuscript/printed page image into overlapping quadrants
(`top_right`, `top_left`, `bottom_right`, `bottom_left` in RTL reading order)
and/or horizontal layout bands (`header`, `matn_top`, `sharh_body`, `footnotes`)
for high-precision visual inspection of small footnote markers (`[١]`, `²`, `(3)`)
and dense vocalized Matn blocks (`﴿...﴾`).
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict

try:
    from PIL import Image
except ImportError:
    Image = None


def crop_page_quadrants(
    image_path: str,
    output_dir: str,
    overlap_ratio: float = 0.08,
) -> Dict[str, str]:
    """
    Crop an image into 4 overlapping quadrants ordered for Arabic RTL reading
    plus horizontal bands (`matn_top_band`, `sharh_band`, `footnote_band`).
    """
    if Image is None:
        raise RuntimeError("Pillow (PIL) is required for crop_quadrants.py")

    img = Image.open(image_path)
    w, h = img.size
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(image_path).stem

    dx = int(w * overlap_ratio)
    dy = int(h * overlap_ratio)
    mid_x = w // 2
    mid_y = h // 2

    boxes = {
        "q1_top_right": (max(0, mid_x - dx), 0, w, min(h, mid_y + dy)),
        "q2_top_left": (0, 0, min(w, mid_x + dx), min(h, mid_y + dy)),
        "q3_bottom_right": (max(0, mid_x - dx), max(0, mid_y - dy), w, h),
        "q4_bottom_left": (0, max(0, mid_y - dy), min(w, mid_x + dx), h),
        "matn_top_band": (0, int(h * 0.06), w, int(h * 0.42)),
        "sharh_band": (0, int(h * 0.35), w, int(h * 0.78)),
        "footnote_band": (0, int(h * 0.70), w, h),
    }

    saved: Dict[str, str] = {}
    for name, box in boxes.items():
        crop_img = img.crop(box)
        dest = out_dir / f"{stem}_{name}.png"
        crop_img.save(dest)
        saved[name] = str(dest)

    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description="Crop page image into RTL quadrants and multi-zone bands.")
    parser.add_argument("image_path", help="Input page image PNG/JPG")
    parser.add_argument("-o", "--output-dir", help="Output directory for cropped images")
    parser.add_argument("--overlap", type=float, default=0.08, help="Overlap ratio (default: 0.08)")
    args = parser.parse_args()

    out_dir = args.output_dir or str(Path(args.image_path).parent / "quadrants")
    saved = crop_page_quadrants(args.image_path, out_dir, overlap_ratio=args.overlap)
    print(json.dumps(saved, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
