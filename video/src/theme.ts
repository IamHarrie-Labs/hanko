import { loadFont as loadGrotesk } from "@remotion/google-fonts/SpaceGrotesk";
import { loadFont as loadMono } from "@remotion/google-fonts/JetBrainsMono";
import { continueRender, delayRender, staticFile } from "remotion";

export const { fontFamily: SANS } = loadGrotesk("normal", { weights: ["400", "500", "700"], subsets: ["latin"] });
export const { fontFamily: MONO } = loadMono("normal", { weights: ["400", "700"], subsets: ["latin"] });
// Noto Serif JP 900, subset to the two glyphs of 判子 (1.4 KB, not 124 files).
export const SERIF_JP = "HankoSealJP";
const sealFont = delayRender("seal font");
const face = new FontFace(SERIF_JP, `url(${staticFile("fonts/seal-jp.woff2")}) format('woff2')`, { weight: "900" });
face
  .load()
  .then(() => {
    document.fonts.add(face);
    continueRender(sealFont);
  })
  .catch(() => continueRender(sealFont));

// The site's own palette, so the video and the product read as one thing.
export const C = {
  paper: "#E3E2DD",
  surface: "#EFEDE9",
  ink: "#171614",
  ink2: "#23211E",
  body: "#3B3833",
  muted: "#625E58",
  pink: "#E357AE",
  pinkLift: "#FF9AD9",
  pinkDeep: "#A2307F",
  yellow: "#FFD54A",
  good: "#3FA35F",
  goodDark: "#29703E",
  white: "#F4F2EF",
};

export type Tone = "light" | "dark" | "pink";

export const BG: Record<Tone, string> = { light: C.paper, dark: C.ink, pink: C.pink };
export const FG: Record<Tone, string> = { light: C.ink, dark: C.white, pink: C.ink };
