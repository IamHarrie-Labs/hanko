// Subtitles for upload, from the same timings and the same page breaks as the burned-in captions.
import fs from "fs";
const t = JSON.parse(fs.readFileSync("src/data/timings.json", "utf8"));
const FPS = 30, LEAD = 14, TAIL = 22, OVERLAP = 18, HOLD = 110;
const ts = (s) => {
  const ms = Math.round(s * 1000), h = Math.floor(ms / 3600000), m = Math.floor(ms / 60000) % 60, sec = Math.floor(ms / 1000) % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")},${String(ms % 1000).padStart(3, "0")}`;
};
let from = 0, n = 1, out = "";
t.forEach((s, i) => {
  const tokens = s.text.split(/\s+/);
  const base = (from + LEAD) / FPS;
  let page = [];
  s.words.forEach((w, k) => {
    page.push({ ...w, text: tokens[k] });
    const end = /[.?!]$/.test(tokens[k]) || (/,$/.test(tokens[k]) && page.length >= 4) || page.length >= 6 || k === s.words.length - 1;
    if (end) {
      out += `${n++}\n${ts(base + page[0].start)} --> ${ts(base + page.at(-1).end + 0.25)}\n${page.map((p) => p.text).join(" ")}\n\n`;
      page = [];
    }
  });
  from += LEAD + Math.ceil(s.words.at(-1).end * FPS) + TAIL + (s.id === "close" ? HOLD : 0) - (i < t.length - 1 ? OVERLAP : 0);
});
fs.mkdirSync("out", { recursive: true });
fs.writeFileSync("out/hanko-demo.srt", out);
console.log(n - 1, "cues");
