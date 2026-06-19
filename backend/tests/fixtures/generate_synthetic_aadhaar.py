"""Generate synthetic Aadhaar test image for manual/API pipeline testing."""

import io
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

SYNTHETIC_AADHAAR_TEXT = """
GOVERNMENT OF INDIA
Unique Identification Authority of India
AADHAAR
Name: Ravi Kumar Sharma
Date of Birth: 15/08/1995
Gender: Male
Address: 42 MG Road, Pune, Maharashtra 411001
2341 2341 2346
"""


def build_synthetic_aadhaar_png() -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (900, 700), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    y = 40
    for line in SYNTHETIC_AADHAAR_TEXT.strip().splitlines():
        draw.text((40, y), line.strip(), fill=(0, 0, 0))
        y += 36

    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "synthetic_aadhaar.png"
    out.write_bytes(build_synthetic_aadhaar_png())
    print(f"Wrote {out}")
