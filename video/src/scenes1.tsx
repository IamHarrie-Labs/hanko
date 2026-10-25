import React from "react";
import { AbsoluteFill, Easing, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { evolvePath } from "@remotion/paths";
import { C, MONO, SANS } from "./theme";
import { wordFrame } from "./timeline";
import { Counter, Eyebrow, Land, Rise, Seal, Sfx, Typewriter, clamp, easeInOut, easeOut, useDrift, useEnter } from "./kit";

// ---------------------------------------------------------------------------
// 1. Hook: five cards that turn out to be one.
// ---------------------------------------------------------------------------

const POST = "$BONK is about to run. Buying now.";
const COPIES = [
  { tag: "ORIGINAL", note: "", rot: -3, x: -560, y: -40 },
  { tag: "REPOST", note: "RT", rot: 4, x: -190, y: -150 },
  { tag: "FORWARD", note: "Forwarded from a channel", rot: -2, x: 180, y: -20 },
  { tag: "COPY", note: "", rot: 3, x: 540, y: -140 },
  { tag: "COPY + AD", note: "Join our VIP group for signals", rot: -4, x: 20, y: 200 },
];

const PostCard: React.FC<{ i: number; tag: string; note: string; showTag: number; dim: number }> = ({ i, tag, note, showTag, dim }) => (
  <div
    style={{
      width: 400,
      padding: "26px 28px",
      borderRadius: 22,
      background: "#26231F",
      border: "1px solid rgba(244,242,239,0.12)",
      boxShadow: "0 30px 60px rgba(0,0,0,0.45)",
      color: C.white,
      fontFamily: SANS,
      opacity: 1 - dim * 0.15,
    }}
  >
    <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 16 }}>
      <div style={{ width: 46, height: 46, borderRadius: 23, background: ["#E357AE", "#7C8CF8", "#5CB46A", "#E5B54A", "#E06C5D"][i] }} />
      <div style={{ fontFamily: MONO, fontSize: 20, color: "rgba(244,242,239,0.7)" }}>@account_{i + 1}</div>
      <div
        style={{
          marginLeft: "auto",
          fontFamily: MONO,
          fontSize: 15,
          fontWeight: 700,
          letterSpacing: "0.12em",
          padding: "5px 10px",
          borderRadius: 8,
          background: i === 0 ? "rgba(244,242,239,0.12)" : C.pink,
          color: i === 0 ? C.white : C.ink,
          opacity: showTag,
          transform: `scale(${0.6 + 0.4 * showTag})`,
        }}
      >
        {tag}
      </div>
    </div>
    {note && i !== 4 ? <div style={{ fontFamily: MONO, fontSize: 17, color: "rgba(244,242,239,0.45)", marginBottom: 8 }}>{note}</div> : null}
    <div style={{ fontSize: 30, fontWeight: 500, lineHeight: 1.3 }}>{POST}</div>
    {i === 4 ? <div style={{ fontSize: 22, color: C.pinkLift, marginTop: 10 }}>{note}</div> : null}
  </div>
);

export const Hook: React.FC = () => {
  const frame = useCurrentFrame();
  const w = (i: number) => wordFrame("hook", i);
  const collapse = interpolate(frame, [w(9), w(9) + 26], [0, 1], { ...clamp, easing: easeInOut });
  const tags = useEnter(w(11), 200, 14);
  const count = frame < w(9) + 10 ? Math.min(5, Math.max(0, Math.floor((frame - w(0) + 6) / 5) + 1)) : 1;
  const counterPop = useEnter(w(9) + 10, 10);
  return (
    <AbsoluteFill>
      <AbsoluteFill style={{ alignItems: "center", justifyContent: "center", top: -70 }}>
        {COPIES.map((c, i) => {
          const at = w(0) + i * 5;
          const d = useDrift("card" + i, 8);
          const tx = c.x * (1 - collapse) + (i === 0 ? 0 : (i - 2) * 14 * collapse);
          const ty = c.y * (1 - collapse) + i * 10 * collapse;
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                transform: `translate(${tx + d.x}px, ${ty + d.y}px) rotate(${c.rot * (1 - collapse) + (i - 2) * 2 * collapse}deg)`,
                zIndex: i === 0 ? 10 : 5 - i,
              }}
            >
              <Land at={at} from={0.6} y={120} rotate={c.rot * 3} damping={13}>
                <PostCard i={i} tag={c.tag} note={c.note} showTag={tags} dim={i === 0 ? 0 : collapse} />
              </Land>
            </div>
          );
        })}
      </AbsoluteFill>
      <div style={{ position: "absolute", left: 120, top: 92, display: "flex", alignItems: "baseline", gap: 22 }}>
        <div
          style={{
            fontFamily: SANS,
            fontWeight: 700,
            fontSize: 150,
            lineHeight: 1,
            color: count === 1 && frame > w(9) ? C.pink : C.white,
            transform: `scale(${frame > w(9) + 10 ? 1 + (1 - counterPop) * 0.3 : 1})`,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {frame >= w(0) - 4 ? count : ""}
        </div>
        <Eyebrow color="rgba(244,242,239,0.6)">{count === 1 && frame > w(9) ? "voice, really" : "voices?"}</Eyebrow>
      </div>
      <Eyebrow color="rgba(244,242,239,0.35)" style={{ position: "absolute", right: 120, top: 112, fontSize: 18 }}>
        illustration
      </Eyebrow>
      {COPIES.map((_, i) => (
        <Sfx key={i} at={w(0) + i * 5} name="pop" volume={0.35} />
      ))}
      <Sfx at={w(9)} name="whoosh" volume={0.45} />
      <Sfx at={w(9) + 22} name="stamp" volume={0.4} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 2. Problem: the noise, the action, the missing record.
// ---------------------------------------------------------------------------

const noisePath = (() => {
  let d = "M 0 300";
  let y = 300;
  for (let x = 40; x <= 1920; x += 40) {
    y = 300 + Math.sin(x * 0.013) * 90 + Math.sin(x * 0.051) * 70 + ((x * 7919) % 97) - 48;
    d += ` L ${x} ${y.toFixed(1)}`;
  }
  return d;
})();

export const Problem: React.FC = () => {
  const frame = useCurrentFrame();
  const w = (i: number) => wordFrame("problem", i);
  const draw = interpolate(frame, [0, w(10)], [0, 1], { ...clamp, easing: Easing.out(Easing.quad) });
  const { strokeDasharray, strokeDashoffset } = evolvePath(draw, noisePath);
  const strike = interpolate(frame, [w(17), w(17) + 12], [0, 1], { ...clamp, easing: easeOut });
  const big: React.CSSProperties = { fontFamily: SANS, fontWeight: 700, fontSize: 132, letterSpacing: "-0.035em", lineHeight: 0.98 };
  return (
    <AbsoluteFill>
      <svg width={1920} height={600} style={{ position: "absolute", top: 440, opacity: 0.45 }}>
        <path d={noisePath} fill="none" stroke={C.pink} strokeWidth={6} strokeLinejoin="round" strokeDasharray={strokeDasharray} strokeDashoffset={strokeDashoffset} />
      </svg>
      <div style={{ position: "absolute", left: 130, top: 110 }}>
        <Rise at={w(0)}>
          <div style={{ fontFamily: SANS, fontSize: 46, fontWeight: 500, color: C.body }}>Most trading bots can't tell.</div>
        </Rise>
      </div>
      <div style={{ position: "absolute", left: 130, top: 250, display: "flex", flexDirection: "column", gap: 8 }}>
        <Rise at={w(8)}>
          <div style={big}>They count the noise.</div>
        </Rise>
        <Rise at={w(11)}>
          <div style={big}>Act on it.</div>
        </Rise>
        <Rise at={w(15)}>
          <div style={{ ...big, position: "relative", display: "inline-block" }}>
            Keep no record.
            <div
              style={{
                position: "absolute",
                left: "-2%",
                top: "52%",
                height: 16,
                width: `${strike * 104}%`,
                background: C.pink,
                transform: "rotate(-2deg)",
                borderRadius: 8,
              }}
            />
          </div>
        </Rise>
      </div>
      <Sfx at={w(8)} name="tick" volume={0.6} />
      <Sfx at={w(11)} name="tick" volume={0.6} />
      <Sfx at={w(15)} name="tick" volume={0.6} />
      <Sfx at={w(17)} name="whoosh" volume={0.3} />
      <Sfx at={w(19)} name="riser" volume={0.5} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 3. Reveal: the name, the seal, and the order of events.
// ---------------------------------------------------------------------------

export const Reveal: React.FC = () => {
  const frame = useCurrentFrame();
  const w = (i: number) => wordFrame("reveal", i);
  const lift = interpolate(frame, [w(16) - 6, w(16) + 14], [0, 1], { ...clamp, easing: easeInOut });
  const line = interpolate(frame, [w(17), w(23)], [0, 1], { ...clamp, easing: easeInOut });
  const shake = frame >= w(2) && frame < w(2) + 8 ? Math.sin(frame * 3.1) * (8 - (frame - w(2))) * 1.6 : 0;
  const shake2 = frame >= w(7) && frame < w(7) + 8 ? Math.cos(frame * 2.7) * (8 - (frame - w(7))) * 1.4 : 0;
  return (
    <AbsoluteFill style={{ transform: `translate(${shake + shake2}px, ${shake2}px)` }}>
      <div
        style={{
          position: "absolute",
          left: 0,
          right: 0,
          top: 150 - lift * 70,
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          gap: 90,
          transform: `scale(${1 - lift * 0.28})`,
        }}
      >
        <Land at={w(2) - 4} from={1.8} y={0} rotate={-8} damping={11}>
          <div style={{ background: C.paper, padding: "40px 54px", borderRadius: 30, transform: "rotate(-3deg)", boxShadow: "0 30px 70px rgba(80,10,50,0.35)" }}>
            <Img src={staticFile("hanko-logo.png")} style={{ width: 560, display: "block" }} />
          </div>
        </Land>
        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 18 }}>
          <Seal at={w(7)} size={330} color={C.ink} paper="rgba(255,255,255,0.10)" label="HANKO · SEAL" />
          <Rise at={w(9)}>
            <div style={{ fontFamily: MONO, fontSize: 26, letterSpacing: "0.18em", color: C.ink }}>判子 · STAMP TO COMMIT</div>
          </Rise>
        </div>
      </div>
      {/* the order of events */}
      <div style={{ position: "absolute", left: 230, right: 230, top: 640, opacity: lift }}>
        <div style={{ position: "relative", height: 150 }}>
          <div style={{ position: "absolute", left: 0, right: 0, top: 70, height: 6, borderRadius: 3, background: "rgba(23,22,20,0.18)" }} />
          <div style={{ position: "absolute", left: 0, top: 70, height: 6, borderRadius: 3, width: `${line * 100}%`, background: C.ink }} />
          <div style={{ position: "absolute", left: -40, top: 0 }}>
            <Land at={w(20)} from={2} y={-60} damping={10}>
              <div style={{ width: 146, height: 146, borderRadius: 73, background: C.ink, color: C.pink, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: MONO, fontWeight: 700, fontSize: 22, letterSpacing: "0.1em", textAlign: "center" }}>
                STAMPED
                <br />
                NOW
              </div>
            </Land>
          </div>
          <div style={{ position: "absolute", right: -40, top: 0 }}>
            <Land at={w(23)} from={0.7} y={20}>
              <div style={{ width: 146, height: 146, borderRadius: 73, border: `5px dashed ${C.ink}`, display: "flex", alignItems: "center", justifyContent: "center", fontFamily: MONO, fontWeight: 700, fontSize: 22, letterSpacing: "0.1em", textAlign: "center" }}>
                OUTCOME
                <br />?
              </div>
            </Land>
          </div>
        </div>
      </div>
      <Sfx at={w(2) - 2} name="stamp" volume={0.75} />
      <Sfx at={w(7)} name="stamp" volume={0.85} />
      <Sfx at={w(20)} name="stamp" volume={0.5} />
      <Sfx at={w(23)} name="pop" volume={0.4} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 4. Read: three sources in, echoes folded into the post they copy.
// ---------------------------------------------------------------------------

const SourceIcon: React.FC<{ kind: "telegram" | "bluesky" | "x"; size?: number }> = ({ kind, size = 54 }) => {
  if (kind === "telegram")
    return (
      <svg width={size} height={size} viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="12" fill="#2AABEE" />
        <path d="M5.5 11.6 17.3 7c.6-.2 1.1.1.9 1l-2 9.5c-.1.7-.6.8-1.1.5l-3-2.2-1.5 1.4c-.2.2-.3.3-.6.3l.2-3.1 5.6-5c.2-.2 0-.3-.4-.1l-6.9 4.3-3-.9c-.6-.2-.7-.7.1-1Z" fill="#fff" />
      </svg>
    );
  if (kind === "bluesky")
    return (
      <svg width={size} height={size} viewBox="0 0 24 24">
        <circle cx="12" cy="12" r="12" fill="#1185FE" />
        <path d="M8 7.5c1.5 1.1 3.1 3.4 3.7 4.6.6-1.2 2.2-3.5 3.7-4.6 1.1-.8 2.9-1.4 2.9.6 0 .4-.2 3.3-.4 3.8-.6 1.8-2.5 2.3-4.2 2 3 .5 3.7 2.2 2.1 3.9-3.1 3.2-4.4-.8-4.1-1.6-.3.8-1.1 4.8-4.1 1.6-1.6-1.7-.9-3.4 2.1-3.9-1.7.3-3.6-.2-4.2-2-.2-.5-.4-3.4-.4-3.8 0-2 1.8-1.4 2.9-.6Z" fill="#fff" />
      </svg>
    );
  return (
    <svg width={size} height={size} viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="12" fill="#171614" />
      <path d="M13.3 11 18 5.6h-1.1l-4.1 4.7-3.3-4.7H5.8l4.9 7.1-4.9 5.7h1.1l4.3-5 3.4 5h3.7L13.3 11Zm-1.5 1.8-.5-.7-4-5.7h1.7l3.2 4.6.5.7 4.2 6h-1.7l-3.4-4.9Z" fill="#fff" />
    </svg>
  );
};

const Skeleton: React.FC<{ widths: number[]; color: string }> = ({ widths, color }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
    {widths.map((wd, i) => (
      <div key={i} style={{ height: 14, width: `${wd}%`, borderRadius: 7, background: color }} />
    ))}
  </div>
);

const ECHOES = [
  { label: "REPOST", at: 10, y: -235 },
  { label: "FORWARD", at: 12, y: 0 },
  { label: "COPY + AD", at: 15, y: 235 },
];

export const Read: React.FC = () => {
  const frame = useCurrentFrame();
  const w = (i: number) => wordFrame("read", i);
  const fold = interpolate(frame, [w(21), w(21) + 22], [0, 1], { ...clamp, easing: easeInOut });
  const sources: { kind: "telegram" | "bluesky" | "x"; name: string; at: number }[] = [
    { kind: "telegram", name: "Telegram", at: w(5) },
    { kind: "bluesky", name: "Bluesky", at: w(6) },
    { kind: "x", name: "X", at: w(8) },
  ];
  const card: React.CSSProperties = {
    width: 430,
    padding: "24px 26px",
    borderRadius: 20,
    background: C.surface,
    border: "1px solid rgba(23,22,20,0.16)",
    boxShadow: "0 18px 40px rgba(23,22,20,0.12)",
  };
  const one = useEnter(w(23), 11);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 120, top: 90, display: "flex", gap: 36 }}>
        {sources.map((s) => (
          <Land key={s.kind} at={s.at} from={0.5} y={30} damping={12}>
            <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 22px 12px 14px", borderRadius: 40, background: C.surface, border: "1px solid rgba(23,22,20,0.14)" }}>
              <SourceIcon kind={s.kind} />
              <span style={{ fontSize: 34, fontWeight: 600 }}>{s.name}</span>
            </div>
          </Land>
        ))}
      </div>
      {/* the original post */}
      <div style={{ position: "absolute", left: 200, top: 300 }}>
        <Land at={w(1)} y={40}>
          <div style={{ ...card, width: 470, border: `3px solid ${C.ink}`, transform: `scale(${1 + fold * 0.06})` }}>
            <Eyebrow>original post</Eyebrow>
            <div style={{ height: 18 }} />
            <Skeleton widths={[96, 88, 62]} color="rgba(23,22,20,0.22)" />
            <div style={{ marginTop: 20, display: "flex", alignItems: "center", gap: 14, opacity: one }}>
              <div style={{ fontSize: 56, fontWeight: 700, color: C.pinkDeep, transform: `scale(${0.6 + 0.4 * one})` }}>1</div>
              <div style={{ fontFamily: MONO, fontSize: 22, letterSpacing: "0.1em" }}>INDEPENDENT VOICE</div>
            </div>
          </div>
        </Land>
      </div>
      {/* the echoes, joined to it and then folded into it */}
      <svg width={1920} height={1080} style={{ position: "absolute", left: 0, top: 0 }}>
        {ECHOES.map((e) => {
          const p = interpolate(frame, [w(e.at), w(e.at) + 14], [0, 1], { ...clamp, easing: easeOut });
          const y2 = 470 + e.y * (1 - fold);
          const x2 = 1080 - (1080 - 690) * fold;
          const d = `M 690 470 C 860 470, ${x2 - 160} ${y2}, ${x2} ${y2}`;
          const { strokeDasharray, strokeDashoffset } = evolvePath(p, d);
          return <path key={e.label} d={d} fill="none" stroke={C.pink} strokeWidth={5} strokeDasharray={strokeDasharray} strokeDashoffset={strokeDashoffset} opacity={1 - fold} />;
        })}
      </svg>
      {ECHOES.map((e) => {
        const x = 1080 - (1080 - 240) * fold;
        const y = 470 + e.y * (1 - fold) - 95;
        return (
          <div key={e.label} style={{ position: "absolute", left: x, top: y, opacity: interpolate(fold, [0, 0.7], [1, 0], clamp), transform: `scale(${1 - fold * 0.4})` }}>
            <Land at={w(e.at)} x={160} y={0} from={0.9}>
              <div style={{ ...card, background: "#F6E3EE", border: `2px solid ${C.pink}` }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
                  <Eyebrow color={C.pinkDeep}>{e.label}</Eyebrow>
                  <span style={{ fontFamily: MONO, fontSize: 17, color: C.pinkDeep }}>counts once</span>
                </div>
                <Skeleton widths={e.label === "COPY + AD" ? [96, 88, 62, 74] : [96, 88, 62]} color="rgba(162,48,127,0.28)" />
              </div>
            </Land>
          </div>
        );
      })}
      <div style={{ position: "absolute", right: 130, top: 300, width: 520, textAlign: "right" }}>
        <Rise at={w(25)}>
          <div style={{ fontSize: 120, fontWeight: 700, letterSpacing: "-0.04em", lineHeight: 1 }}>
            Not <span style={{ color: C.pinkDeep }}>two.</span>
          </div>
        </Rise>
      </div>
      {sources.map((s) => (
        <Sfx key={s.kind} at={s.at} name="pop" volume={0.35} />
      ))}
      {ECHOES.map((e) => (
        <Sfx key={e.label} at={w(e.at)} name="whoosh" volume={0.22} />
      ))}
      <Sfx at={w(21) + 18} name="stamp" volume={0.45} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 5. Decide: a real decision record prints.
// ---------------------------------------------------------------------------

const RECEIPT = {
  id: "dec_fbae6d1cd0ab19e6dc8d8aac",
  when: "BTC · sealed 24 Oct 2026, 23:21 UTC",
  voices: "WatcherGuru · bitcoin · cointelegraph · cryptovka.com",
  wrong: ["price falls below $68,368", "exit depth drops below $231M", "fewer than 2 independent voices"],
};

export const Decide: React.FC = () => {
  const frame = useCurrentFrame();
  const w = (i: number) => wordFrame("decide", i);
  const verdicts = [
    { label: "ENTER", at: w(3) },
    { label: "PASS", at: w(4) },
    { label: "CAN'T TELL", at: w(6) },
  ];
  const chosen = interpolate(frame, [w(10), w(10) + 10], [0, 1], clamp);
  const print = interpolate(frame, [w(10), w(10) + 40], [0, 1], { ...clamp, easing: easeOut });
  const wrongP = (k: number) => useEnter(w(15) + 4 + k * 7, 200, 14);
  const hl = interpolate(frame, [w(22), w(22) + 10], [0, 1], clamp);
  const row: React.CSSProperties = { display: "flex", justifyContent: "space-between", alignItems: "baseline" };
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 130, top: 150, display: "flex", flexDirection: "column", gap: 26 }}>
        <Eyebrow color="rgba(244,242,239,0.55)">it decides</Eyebrow>
        {verdicts.map((v, i) => {
          const on = i === 0 ? chosen : 0;
          return (
            <Land key={v.label} at={v.at} x={-80} y={0} from={1}>
              <div
                style={{
                  fontFamily: SANS,
                  fontWeight: 700,
                  fontSize: 92,
                  letterSpacing: "-0.03em",
                  color: i === 0 ? `rgba(244,242,239,${1 - on * 0.0})` : `rgba(244,242,239,${1 - chosen * 0.7})`,
                  display: "flex",
                  alignItems: "center",
                  gap: 22,
                }}
              >
                <div style={{ width: 22, height: 22, borderRadius: 11, background: i === 0 ? C.yellow : "rgba(244,242,239,0.3)", opacity: i === 0 ? on : 1 - chosen * 0.5 }} />
                {v.label}
              </div>
            </Land>
          );
        })}
      </div>
      {/* the slot the record prints from */}
      <div style={{ position: "absolute", left: 860, top: 96, width: 940, height: 16, borderRadius: 8, background: "#0B0A09", boxShadow: "inset 0 3px 6px rgba(0,0,0,0.7)", opacity: interpolate(frame, [w(9), w(10)], [0, 1], clamp) }} />
      <div style={{ position: "absolute", left: 890, top: 104, width: 880, height: 780, overflow: "hidden" }}>
        <div
          style={{
            transform: `translateY(${(1 - print) * -100}%)`,
            background: C.surface,
            color: C.ink,
            padding: "40px 48px 44px",
            fontFamily: MONO,
            fontSize: 25,
            lineHeight: 1.5,
            boxShadow: "0 30px 60px rgba(0,0,0,0.5)",
            backgroundImage: "repeating-linear-gradient(0deg, rgba(23,22,20,0.025) 0 2px, transparent 2px 6px)",
          }}
        >
          <div style={{ ...row, fontSize: 19, letterSpacing: "0.18em", color: C.muted }}>
            <span>HANKO · DECISION RECORD</span>
            <span>LIVE RUN</span>
          </div>
          <div style={{ fontSize: 20, color: C.muted, marginTop: 4 }}>{RECEIPT.when} · graded 27 Oct</div>
          <div style={{ borderTop: "2px dashed rgba(23,22,20,0.25)", margin: "18px 0" }} />
          <div style={{ ...row, fontFamily: SANS, fontWeight: 700, fontSize: 64, letterSpacing: "-0.02em" }}>
            <span>ENTER BTC</span>
            <span style={{ background: interpolate(frame, [w(11), w(11) + 8], [0, 1], clamp) > 0.5 ? C.yellow : "transparent", padding: "0 12px", borderRadius: 10 }}>
              <Counter from={0} to={2.38} at={w(11)} frames={22} decimals={2} suffix="%" />
            </span>
          </div>
          <div style={{ marginTop: 8 }}>confidence 0.48 · evidence quality 0.68</div>
          <div>4 independent voices</div>
          <div style={{ fontSize: 20, color: C.muted }}>{RECEIPT.voices}</div>
          <div style={{ borderTop: "2px dashed rgba(23,22,20,0.25)", margin: "18px 0" }} />
          <div style={{ fontSize: 21, letterSpacing: "0.18em", color: C.pinkDeep, fontWeight: 700 }}>WRONG IF, WITHIN 72 HOURS</div>
          {RECEIPT.wrong.map((t, k) => {
            const p = wrongP(k);
            return (
              <div key={t} style={{ opacity: p, transform: `translateX(${(1 - p) * 30}px)`, marginTop: 6, display: "flex", gap: 14 }}>
                <span style={{ color: C.pinkDeep }}>▸</span>
                <span style={{ background: `rgba(227,87,174,${0.28 * hl})`, padding: "0 6px", borderRadius: 6 }}>{t}</span>
              </div>
            );
          })}
          <div style={{ borderTop: "2px dashed rgba(23,22,20,0.25)", margin: "18px 0 12px" }} />
          <div style={{ ...row, fontSize: 18, color: C.muted }}>
            <span>{RECEIPT.id}</span>
          </div>
        </div>
      </div>
      <div style={{ position: "absolute", left: 1610, top: 610, transform: "rotate(-12deg)" }}>
        <Seal at={w(24) + 2} size={190} color={C.pink} label="SEALED · BEFORE" />
      </div>
      {verdicts.map((v) => (
        <Sfx key={v.label} at={v.at} name="tick" volume={0.7} />
      ))}
      <Sfx at={w(10)} name="whoosh" volume={0.35} />
      {RECEIPT.wrong.map((t, k) => (
        <Sfx key={t} at={w(15) + 4 + k * 7} name="tick" volume={0.45} />
      ))}
      <Sfx at={w(24) + 2} name="stamp" volume={0.7} />
    </AbsoluteFill>
  );
};
