"""Generate the narration, one file per scene, with per-word timings."""
import asyncio, json, sys
from pathlib import Path
import edge_tts

VOICE = "en-US-AvaMultilingualNeural"
ONLY = set(sys.argv[1:])  # scene ids to regenerate; empty means all
OUT = Path("voice")

async def scene(s):
    com = edge_tts.Communicate(s["text"], VOICE, rate="-3%", boundary="WordBoundary")
    audio, words = bytearray(), []
    async for chunk in com.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
        elif chunk["type"] == "WordBoundary":
            words.append({"text": chunk["text"], "start": chunk["offset"] / 1e7,
                          "end": (chunk["offset"] + chunk["duration"]) / 1e7})
    (OUT / (s["id"] + ".mp3")).write_bytes(audio)
    return {"id": s["id"], "tone": s["tone"], "text": s["text"], "words": words}

async def with_retry(s):
    for attempt in range(6):
        try:
            return await scene(s)
        except Exception as exc:  # the free endpoint rate-limits bursts
            print("retry", s["id"], type(exc).__name__)
            await asyncio.sleep(10 * (attempt + 1))
    raise SystemExit("gave up on " + s["id"])

async def main():
    scenes = json.loads(Path("script.json").read_text(encoding="utf-8"))
    old = {}
    if Path("voice/timings.json").exists():
        old = {t["id"]: t for t in json.loads(Path("voice/timings.json").read_text(encoding="utf-8"))}
    out = []
    for s in scenes:
        if ONLY and s["id"] not in ONLY and s["id"] in old:
            out.append(old[s["id"]])
        else:
            out.append(await with_retry(s))
    Path("voice/timings.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    for s in out:
        print(s["id"], round(s["words"][-1]["end"], 2), len(s["words"]))

asyncio.run(main())
