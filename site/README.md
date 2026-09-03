# site

The Hanko landing page. Static HTML, no build step required to view it, no
framework, no dependencies — matching how the rest of the project is built.

```
site/index.html          the page
site/assets/              generated images -- do not hand-edit, see below
site/build.py             refreshes the numbers and trail from the repo
site/make_assets.py       cuts site/assets/ from design/logo-source.jpg
```

## Viewing it

```bash
python -m http.server 8899 --directory site
```

Opening `site/index.html` directly works too, except the wordmark: the logo is
a background-position crop of a single image, and some browsers block that over
`file://`.

## The numbers are generated, not typed

The receipt card is labelled **LIVE OUTPUT**. `build.py` is what makes that
label true rather than decorative — it runs the agent for real and writes the
result into the page, along with the test count, line count, commit count and
the GitHub URL read from `git remote`.

```bash
python site/build.py           # rewrite index.html in place
python site/build.py --check   # exit 1 if stale, change nothing
```

`--check` is the CI form. It fails the build when the page has drifted from the
code, so a stale statistic cannot ship. Worth wiring next to `pytest`.

The trail is produced with fixed inputs — a fixture, and `--as-of
2026-08-27T12:00:00Z` — so the published `decision_id` is stable across builds.
That reproducibility is the same property the agent claims about its own
decisions, applied to its website.

Long lines are re-wrapped with a hanging indent to fit the card. That is the one
cosmetic liberty taken with real output; nothing is reworded or trimmed.

## The logo

The handoff shipped one 1280x1280 JPEG and cropped it in CSS with
`background-position` -- workable inside a design tool, fragile as a real
asset: the whole lockup depended on a background image resolving and two
hand-tuned pixel offsets staying in sync with each other, and it produced no
favicon, no social preview image, and no alt text.

`site/make_assets.py` cuts real files out of it once, measured against the
letterforms rather than eyeballed:

```bash
pip install Pillow
python site/make_assets.py
```

```
site/assets/hanko-logo.png   694x360  the full lockup, used as <img> content
site/assets/favicon.png       32x32   the H, for the browser tab
site/assets/icon-180.png     180x180  apple-touch-icon
site/assets/icon-512.png     512x512  the icon manifests ask for
site/assets/og-image.png    1200x630  link-preview card
```

The crop keeps the flat `#E3E2DD` ground intact rather than keying it out --
that colour is exactly the page's `--ground` token, which is presumably where
it came from, and keeping it avoids the halo a JPEG alpha key would leave.

`site/assets/` is generated and committed, the same way a favicon usually is.
Regenerate it after touching `design/logo-source.jpg`; nothing else in the
build depends on Pillow.

## Deploying

Any static host. There is nothing to compile.

```bash
# Netlify / Vercel / Cloudflare Pages
publish directory: site
build command:     python site/build.py
```

For GitHub Pages, point it at `/site` on the default branch.

## The design

Implemented from `Hanko Site.dc.html`, exported from Claude Design. The
prototype used inline styles and a small runtime for its template bindings; this
version uses a stylesheet and plain DOM, and reproduces the visual output
exactly — same palette, type scale, spacing, and the three scroll-triggered
moments.

**Palette.** Warm neutral ground `#E3E2DD`, ink `#171614`, magenta accent
`#E357AE` with `#FF9AD9` on dark and `#B0348A` on light. Green `#2E7D45` marks a
check that held. Space Grotesk for text, JetBrains Mono for anything that came
out of the machine.

**The three moments**, each fired once on scroll at 0.35 visibility:

| Section | What happens | Why it earns its place |
|---|---|---|
| `#missing` | 3.28% → 3.08% | The size falls because a safety check went missing. Nothing else changed. |
| `#voices` | 3 → 2, one card struck through | An echo is demoted in front of you, with its reason. |
| `#commitment` | FALSIFIED stamps across the card | The seal metaphor, paid off — a decision graded against its own words. |

All three respect `prefers-reduced-motion`: the end state is applied immediately
and the typing and stamp animations are skipped.

## Still to fill in

The GitHub links resolve from `git remote get-url origin`. Until a remote
exists they stay as `#`, and `build.py` leaves them alone rather than inventing
a URL.
