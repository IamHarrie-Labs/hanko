"""Cut the site's image assets from the master logo.

The design prototype had one 1280x1280 upload and cropped it with CSS
`background-position`, which is what you do inside a design tool. On a real
site it is fragile: the whole lockup depends on a background image resolving
and on two hand-tuned offsets staying in step with each other.

So the crops are done once, here, into real files the page can reference as
content with alt text.

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
SOURCE = ROOT / "design" / "logo-source.png"
OUT = ROOT / "site" / "assets"

# The source is a genuine RGBA cutout (background removed, not a flat-colour
# JPEG), so the two logo crops below keep real transparency and composite
# cleanly over any ground -- no colour-matching hack needed for those.
# A few outputs (favicon, apple-touch-icon, the og-image social card) are
# still flattened onto this colour: transparency there is either discouraged
# (Apple composites a transparent apple-touch-icon onto black) or simply
# unpredictable (social platforms pick their own background for og:image).
# It matches the site's --ground token.
GROUND = (227, 226, 221)

# Measured against the alpha channel, not eyeballed: the full artwork
# (ink + pink swash + drips) sits at (440, 664, 1492, 1208) in the
# 2000x2000 source, ratio 1.934 -- close enough to the prototype's 1.928
# that the existing 340x177 / 115x60 CSS sizes still read correctly.
# +/-20px of air added on each side so the drips at the bottom aren't
# cropped flush.
LOCKUP = (420, 644, 1512, 1228)

# A square centred on the H, measured the same way: the black-ink column
# runs are H 638-794, A 796-930, N 948-1082, KO 1092-1354, and H's own
# ink rows are 766-972. The full lockup is ~2:1 and turns to mush at
# 32px, so the icon is one glyph on its swash instead, with a deliberate
# sliver of A at the right edge (matches the crop chosen by eye from the
# previous source).
GLYPH = (576, 729, 856, 1009)


def main() -> int:
    if not SOURCE.exists():
        raise SystemExit("missing " + str(SOURCE.relative_to(ROOT)))

    OUT.mkdir(parents=True, exist_ok=True)
    master = Image.open(SOURCE).convert("RGBA")

    # Transparent content crops -- used directly as <img> on the page.
    lockup = master.crop(LOCKUP)
    lockup.save(OUT / "hanko-logo.png", optimize=True)

    glyph_rgba = master.crop(GLYPH)

    def flattened(im: Image.Image) -> Image.Image:
        base = Image.new("RGBA", im.size, GROUND + (255,))
        base.alpha_composite(im)
        return base.convert("RGB")

    glyph_flat = flattened(glyph_rgba)
    for size in (32, 180, 512):
        name = "favicon.png" if size == 32 else "icon-" + str(size) + ".png"
        glyph_flat.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)

    # Social card: the lockup flattened onto the ground at the 1.91:1
    # ratio every platform crops og:image to.
    card = Image.new("RGB", (1200, 630), GROUND)
    scaled = flattened(lockup).resize(
        (880, round(880 * lockup.height / lockup.width)), Image.LANCZOS
    )
    card.paste(scaled, ((1200 - scaled.width) // 2, (630 - scaled.height) // 2))
    card.save(OUT / "og-image.png", optimize=True)

    for path in sorted(OUT.iterdir()):
        print(path.name.ljust(20) + format(path.stat().st_size, ",") + " bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
