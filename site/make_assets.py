"""Cut the site's image assets from the master logo.

The design prototype had one 1280x1280 upload and cropped it with CSS
`background-position`, which is what you do inside a design tool. On a real
site it is fragile: the whole lockup depends on a background image resolving
and on two hand-tuned offsets staying in step with each other.

So the crops are done once, here, into real files the page can reference as
content with alt text. The proportions are matched to the prototype exactly:
the lockup crop is 694x360 (1.928:1), which renders at 340x177 in the hero
and 115x60 in the nav, the two sizes the design specified.

    python site/make_assets.py

Requires Pillow, which is a build-time dependency only. Nothing the agent
does needs it, and the generated files are committed, so a clone can build
and deploy the site without installing it.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - build tooling, not runtime
    raise SystemExit("Pillow is needed to regenerate assets: pip install Pillow")

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "design" / "logo-source.jpg"
OUT = ROOT / "site" / "assets"

# The artwork sits inside a flat ground of #E3E2DD, which is where the
# site's --ground token comes from. Because the two are byte-identical
# there is no need to key out the background: cropping with the ground
# intact is exact, and avoids the halo a JPEG alpha key would leave.
GROUND = (227, 226, 221)

# Measured bounding box of the ink and pink, plus 12px of air so the
# result matches the prototype's aspect ratio.
LOCKUP = (272, 424, 966, 784)

# A square centred on the H, measured from the letterforms rather than
# eyeballed: the black ink runs are H 408-507, A 510-595, N 606-692,
# KO 698-868, with ink rows 486-622. The full lockup is 2:1 and turns to
# mush at 32px, so the icon is one glyph on its swash instead.
GLYPH = (382, 479, 532, 629)


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit("missing " + str(SOURCE.relative_to(ROOT)))

    OUT.mkdir(parents=True, exist_ok=True)
    master = Image.open(SOURCE).convert("RGB")

    lockup = master.crop(LOCKUP)
    lockup.save(OUT / "hanko-logo.png", optimize=True)

    glyph = master.crop(GLYPH)
    for size in (32, 180, 512):
        name = "favicon.png" if size == 32 else "icon-" + str(size) + ".png"
        glyph.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)

    # Social card: the lockup centred on the ground, at the 1.91:1 ratio
    # every platform crops to.
    card = Image.new("RGB", (1200, 630), GROUND)
    scaled = lockup.resize((880, round(880 * lockup.height / lockup.width)), Image.LANCZOS)
    card.paste(scaled, ((1200 - scaled.width) // 2, (630 - scaled.height) // 2))
    card.save(OUT / "og-image.png", optimize=True)

    for path in sorted(OUT.iterdir()):
        print(path.name.ljust(20) + format(path.stat().st_size, ",") + " bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
