import timings from "./data/timings.json";
import type { Tone } from "./theme";

export const FPS = 30;
export const LEAD = 14; // frames of picture before the voice starts
export const TAIL = 22; // frames after the last word
export const OVERLAP = 18; // frames each scene's entrance overlaps the last one
export const CLOSE_HOLD = 110; // the end card stays up after the last word

export type Word = { text: string; start: number; end: number };
export type SceneTiming = {
  id: string;
  tone: Tone;
  words: Word[];
  from: number;
  duration: number;
};

type Raw = { id: string; tone: Tone; text: string; words: Word[] };

const build = (): SceneTiming[] => {
  let from = 0;
  return (timings as Raw[]).map((s, i) => {
    // Show the script's own tokens (with punctuation) when they line up
    // one-to-one with the spoken word boundaries, which they do here.
    const tokens = s.text.split(/\s+/);
    const words = s.words.map((w, k) => ({ ...w, text: tokens.length === s.words.length ? tokens[k] : w.text }));
    const last = words[words.length - 1].end;
    const duration = LEAD + Math.ceil(last * FPS) + TAIL + (s.id === "close" ? CLOSE_HOLD : 0);
    const scene = { id: s.id, tone: s.tone, words, from, duration };
    from += duration - (i < (timings as Raw[]).length - 1 ? OVERLAP : 0);
    return scene;
  });
};

export const SCENES = build();
export const TOTAL = SCENES[SCENES.length - 1].from + SCENES[SCENES.length - 1].duration;

export const sceneById = (id: string) => SCENES.find((s) => s.id === id)!;

/** Local frame (inside the scene) at which word `i` starts being spoken. */
export const wordFrame = (id: string, i: number) => {
  const s = sceneById(id);
  const w = s.words[Math.max(0, Math.min(i, s.words.length - 1))];
  return LEAD + Math.round(w.start * FPS);
};
