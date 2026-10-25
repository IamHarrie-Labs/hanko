import fs from "fs";
const t = JSON.parse(fs.readFileSync("src/data/timings.json", "utf8"));
const FPS = 30, LEAD = 14, TAIL = 22, OVERLAP = 18, HOLD = 110;
let from = 0; const out = {};
t.forEach((s, i) => {
  const dur = LEAD + Math.ceil(s.words.at(-1).end * FPS) + TAIL + (s.id === "close" ? HOLD : 0);
  out[s.id] = { from, dur, w: s.words.map((w) => from + LEAD + Math.round(w.start * FPS)) };
  from += dur - (i < t.length - 1 ? OVERLAP : 0);
});
console.log(JSON.stringify(out));
