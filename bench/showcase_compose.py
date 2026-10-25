"""Stack real workspace screenshots into one labelled README image. Nothing in the screenshots is edited: each is
placed whole under a caption bar that names the example, its document and source.

    python bench/showcase_compose.py --out docs/assets/showcase/lead.png \
        "Example 1|Arabic letter (genuine): who signed it|docs/assets/showcase/arabic-letter-signer.png" \
        "Example 2|English form (genuine): a label's value|docs/assets/showcase/form-label-value.png"

The exact command that made the README's lead.png is in the README's reproduction block.

Needs Pillow (only for this script).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BAR = 64
GAP = 24
BG = (11, 15, 20)
ACCENT = (34, 211, 238)
TEXT = (230, 236, 241)
FONTS = [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\segoeui.ttf", "DejaVuSans-Bold.ttf"]


def font(size: int) -> ImageFont.ImageFont:
    for f in FONTS:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("panels", nargs="+", help="'tag|caption|screenshot.png'")
    args = ap.parse_args()
    panels = [p.split("|", 2) for p in args.panels]
    shots = [Image.open(path).convert("RGB") for _, _, path in panels]
    width = max(s.width for s in shots)
    height = sum(BAR + s.height for s in shots) + GAP * (len(shots) - 1)
    canvas = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(canvas)
    y = 0
    for (tag, caption, _), shot in zip(panels, shots, strict=True):
        draw.text((24, y + 14), tag, font=font(30), fill=ACCENT)
        draw.text((24 + draw.textlength(tag, font=font(30)) + 18, y + 14), caption, font=font(30), fill=TEXT)
        canvas.paste(shot, (0, y + BAR))
        y += BAR + shot.height + GAP
    canvas.save(args.out, optimize=True)
    print(f"wrote {args.out} ({width}x{height})")


if __name__ == "__main__":
    main()
