import React from "react";
import { AbsoluteFill, interpolate, spring, useCurrentFrame, useVideoConfig } from "remotion";
import { C, SANS, Tone } from "./theme";
import { FPS, LEAD, SCENES, SceneTiming, Word } from "./timeline";

type Page = { words: (Word & { abs: number; absEnd: number })[]; start: number; end: number; tone: Tone };

// Highlight chosen for contrast against each background: pink on paper,
// yellow on ink, black on pink. The active word's text flips to suit it.
const STYLE: Record<Tone, { base: string; spoken: string; pending: string; hl: string; hlText: string }> = {
  light: { base: C.ink, spoken: C.ink, pending: "rgba(23,22,20,0.38)", hl: C.pink, hlText: C.ink },
  dark: { base: C.white, spoken: C.white, pending: "rgba(244,242,239,0.4)", hl: C.yellow, hlText: C.ink },
  pink: { base: C.ink, spoken: C.ink, pending: "rgba(23,22,20,0.45)", hl: C.ink, hlText: C.white },
};

const MAX_WORDS = 6;

const paginate = (scene: SceneTiming): Page[] => {
  const voiceAt = scene.from + LEAD;
  const words = scene.words.map((w) => ({
    ...w,
    abs: voiceAt + Math.round(w.start * FPS),
    absEnd: voiceAt + Math.round(w.end * FPS),
  }));
  const pages: Page[] = [];
  let cur: Page["words"] = [];
  words.forEach((w, i) => {
    cur.push(w);
    const sentenceEnd = /[.?!]$/.test(w.text);
    const softBreak = /,$/.test(w.text) && cur.length >= 4;
    const next = words[i + 1];
    const longPause = next && next.abs - w.absEnd > 9;
    if (sentenceEnd || softBreak || longPause || cur.length >= MAX_WORDS || i === words.length - 1) {
      pages.push({ words: cur, start: cur[0].abs - 2, end: cur[cur.length - 1].absEnd + 10, tone: scene.tone });
      cur = [];
    }
  });
  // A page stays up until the next one begins, if that is soon.
  for (let i = 0; i < pages.length - 1; i++) {
    const gap = pages[i + 1].start - pages[i].end;
    if (gap > 0 && gap < 12) pages[i].end = pages[i + 1].start;
  }
  return pages;
};

const PAGES = SCENES.flatMap(paginate);

export const Captions: React.FC = () => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const page = PAGES.find((p) => frame >= p.start && frame < p.end);
  if (!page) return null;
  const s = STYLE[page.tone];
  const inP = spring({ frame: frame - page.start, fps, config: { damping: 200 }, durationInFrames: 8 });
  const outO = interpolate(frame, [page.end - 5, page.end], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  const activeIndex = page.words.findIndex((w, i) => {
    const next = page.words[i + 1];
    return frame >= w.abs && (next ? frame < next.abs : frame < w.absEnd + 8);
  });
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", paddingBottom: 66, pointerEvents: "none" }}>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          justifyContent: "center",
          gap: "0 6px",
          maxWidth: 1500,
          fontFamily: SANS,
          fontWeight: 700,
          fontSize: 58,
          lineHeight: 1.25,
          letterSpacing: "-0.01em",
          opacity: outO,
          transform: `translateY(${(1 - inP) * 24}px)`,
        }}
      >
        {page.words.map((w, i) => {
          const active = i === activeIndex;
          const spoken = frame >= w.abs;
          const pop = spring({ frame: frame - w.abs, fps, config: { damping: 12, stiffness: 220 }, durationInFrames: 10 });
          const scale = active ? 1 + (1 - pop) * 0.12 + 0.02 : 1;
          return (
            <span
              key={i}
              style={{
                position: "relative",
                padding: "2px 14px 6px",
                borderRadius: 14,
                color: active ? s.hlText : spoken ? s.spoken : s.pending,
                transform: `scale(${scale}) rotate(${active ? -1.2 : 0}deg)`,
                display: "inline-block",
              }}
            >
              {active ? (
                <span
                  style={{
                    position: "absolute",
                    inset: 0,
                    borderRadius: 14,
                    background: s.hl,
                    transform: `scaleX(${0.6 + 0.4 * pop})`,
                    boxShadow: page.tone === "dark" ? "0 6px 24px rgba(255,213,74,0.25)" : "0 6px 18px rgba(0,0,0,0.12)",
                    zIndex: -1,
                  }}
                />
              ) : null}
              <span style={{ position: "relative" }}>{w.text}</span>
            </span>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
