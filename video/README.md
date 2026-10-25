# The Hanko demo video

A 96-second motion piece, built in code with [Remotion](https://www.remotion.dev).
Every number on screen comes from the live project: the BTC decision record is a
real scheduled run, the BONK exit cost is a live quote captured on 25 Oct 2026,
and the Bitcoin block is the one run_836b976720f63dc0 is anchored in.

The hook cards are labelled as an illustration on screen.

```bash
npm install
python tts.py          # narration, one MP3 per scene, plus word timings
python sound.py        # music bed and sound effects, synthesised
node capture.mjs       # screenshots of the live site (needs CHROME_PATH)
npm run render         # out/hanko-demo.mp4
npx remotion render HankoTeaser out/hanko-teaser.mp4   # the 33-second cut for X
node srt.mjs           # out/hanko-demo.srt (English)
node srt-ja.mjs        # out/hanko-demo.ja.srt (Japanese, one cue per sentence)
```

- `script.json`: the narration, scene by scene.
- `src/timeline.ts`: scene lengths come from the narration's word timings.
- `src/Captions.tsx`: word-by-word captions. The highlight is pink on paper,
  yellow on ink, and black on pink, for contrast.
- `src/scenes1.tsx`, `src/scenes2.tsx`: the ten scenes.
