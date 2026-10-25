import React from "react";
import { AbsoluteFill, Img, interpolate, staticFile, useCurrentFrame } from "remotion";
import { evolvePath } from "@remotion/paths";
import { C, MONO, SANS } from "./theme";
import { wordFrame } from "./timeline";
import { BrowserFrame, Counter, Eyebrow, Land, Rise, Seal, Sfx, Typewriter, clamp, easeInOut, easeOut, useDrift, useEnter } from "./kit";

// ---------------------------------------------------------------------------
// 6. Seal: digest, Bitcoin block, one changed byte, and the check anyone can run.
// ---------------------------------------------------------------------------

const DIGEST = "7c6301912e2e30d38056779c9d3e172ec9b84e27dfaf32d3e6d4c1eb55090329";
const FLIP = 21; // the character that changes

export const SealScene: React.FC = () => {
  const frame = useCurrentFrame();
  const w = (i: number) => wordFrame("seal", i);
  const chain = interpolate(frame, [w(5), w(8)], [0, 1], { ...clamp, easing: easeInOut });
  const flipped = frame >= w(11);
  const glitch = frame >= w(11) && frame < w(11) + 12 ? Math.sin(frame * 9) * 6 : 0;
  const term = useEnter(w(17) - 4, 200, 20);
  const out = (k: number) => interpolate(frame, [w(20) + k * 9, w(20) + k * 9 + 6], [0, 1], clamp);
  const leftShift = term * -60;
  const chainPath = "M 440 330 L 440 600";
  const cp = evolvePath(chain, chainPath);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 120 + leftShift, top: 120, width: 760 }}>
        <Land at={w(0)} y={30}>
          <div style={{ background: C.surface, borderRadius: 22, padding: "30px 34px", border: "1px solid rgba(23,22,20,0.16)", boxShadow: "0 20px 50px rgba(23,22,20,0.14)", transform: `translateX(${glitch}px)` }}>
            <Eyebrow color={C.muted}>run manifest · sha256</Eyebrow>
            <div style={{ fontFamily: MONO, fontSize: 30, lineHeight: 1.45, marginTop: 14, wordBreak: "break-all" }}>
              {DIGEST.split("").map((ch, i) =>
                i === FLIP && flipped ? (
                  <span key={i} style={{ background: C.pink, color: C.ink, borderRadius: 4 }}>
                    0
                  </span>
                ) : (
                  <span key={i} style={{ opacity: interpolate(frame, [w(0) + i * 0.45, w(0) + i * 0.45 + 2], [0, 1], clamp) }}>
                    {ch}
                  </span>
                ),
              )}
            </div>
          </div>
        </Land>
      </div>
      <div style={{ position: "absolute", left: 830 + leftShift, top: 20 }}>
        <Seal at={w(3)} size={200} color={C.pinkDeep} label={frame >= w(16) ? "BROKEN" : "SEALED"} crack={w(15)} />
      </div>
      <svg width={1920} height={1080} style={{ position: "absolute", left: leftShift, top: 0 }}>
        <path d={chainPath} stroke={C.ink} strokeWidth={6} strokeDasharray={cp.strokeDasharray} strokeDashoffset={cp.strokeDashoffset} />
      </svg>
      <div style={{ position: "absolute", left: 160 + leftShift, top: 600 }}>
        <Land at={w(8)} y={40} damping={13}>
          <div style={{ display: "flex", alignItems: "center", gap: 26, background: C.ink, color: C.white, borderRadius: 22, padding: "26px 34px", boxShadow: "0 24px 50px rgba(23,22,20,0.3)" }}>
            <div style={{ width: 74, height: 74, borderRadius: 37, background: "#F7931A", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 46, fontWeight: 700, color: C.white }}>₿</div>
            <div>
              <div style={{ fontFamily: MONO, fontSize: 20, letterSpacing: "0.16em", color: "rgba(244,242,239,0.6)" }}>ANCHORED IN BITCOIN BLOCK</div>
              <div style={{ fontSize: 58, fontWeight: 700, letterSpacing: "-0.02em" }}>
                <Counter from={972000} to={972817} at={w(8)} frames={26} />
              </div>
              <div style={{ fontFamily: MONO, fontSize: 18, color: "rgba(244,242,239,0.55)" }}>mined 23 Oct 2026, 18:40 UTC</div>
            </div>
          </div>
        </Land>
      </div>
      {frame >= w(16) ? (
        <div style={{ position: "absolute", left: 560 + leftShift, top: 330 }}>
          <Land at={w(16)} from={1.4} y={0} damping={10}>
            <div style={{ fontFamily: MONO, fontWeight: 700, fontSize: 30, letterSpacing: "0.14em", color: C.white, background: C.pinkDeep, padding: "8px 18px", borderRadius: 10, transform: "rotate(-4deg)" }}>
              ONE BYTE CHANGED
            </div>
          </Land>
        </div>
      ) : null}
      {/* anyone can check it */}
      <div style={{ position: "absolute", left: 1000, top: 150, width: 800, opacity: term, transform: `translateX(${(1 - term) * 200}px)` }}>
        <div style={{ background: "#12110F", color: "#DCD8D2", borderRadius: 20, padding: "26px 30px 32px", fontFamily: MONO, fontSize: 25, lineHeight: 1.7, boxShadow: "0 40px 80px rgba(23,22,20,0.4)" }}>
          <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
            {["#E06C5D", "#E5B54A", "#5CB46A"].map((c) => (
              <div key={c} style={{ width: 13, height: 13, borderRadius: 7, background: c }} />
            ))}
            <span style={{ marginLeft: 14, fontSize: 17, color: "rgba(220,216,210,0.5)" }}>a fresh clone · no account · no key</span>
          </div>
          <div>
            <span style={{ color: C.pinkLift }}>$ </span>
            <Typewriter text="hanko verify-run runs/run_836b9767.json" at={w(17)} cps={44} caret={frame < w(20)} />
          </div>
          {["ok  manifest digest recomputes", "ok  4 decisions replay from the bundle", "ok  proof anchored in block 972817"].map((l, k) => (
            <div key={l} style={{ opacity: out(k) }}>
              <span style={{ color: "#7FD39A" }}>{l.slice(0, 2)}</span>
              {l.slice(2)}
            </div>
          ))}
          <div style={{ opacity: out(3), marginTop: 8, fontSize: 40, fontWeight: 700, color: "#7FD39A" }}>verified</div>
        </div>
      </div>
      <Sfx at={w(3)} name="stamp" volume={0.75} />
      <Sfx at={w(8)} name="pop" volume={0.4} />
      <Sfx at={w(11)} name="glitch" volume={0.55} />
      <Sfx at={w(15)} name="glitch" volume={0.6} />
      <Sfx at={w(17) - 4} name="whoosh" volume={0.3} />
      {[0, 1, 2].map((k) => (
        <Sfx key={k} at={w(20) + k * 9} name="tick" volume={0.5} />
      ))}
      <Sfx at={w(20) + 27} name="chime" volume={0.5} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 7. Exit: the quote against the formula, and the real page.
// ---------------------------------------------------------------------------

export const Exit: React.FC = () => {
  const frame = useCurrentFrame();
  const w = (i: number) => wordFrame("exit", i);
  const quoteBar = interpolate(frame, [w(14), w(14) + 26], [0, 2.6 / 7.6], { ...clamp, easing: easeOut });
  const modelBar = interpolate(frame, [w(23), w(23) + 26], [0, 1], { ...clamp, easing: easeOut });
  const shot = useEnter(w(18), 200, 30);
  const d = useDrift("exitshot", 5);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 120, top: 100 }}>
        <Rise at={w(3)}>
          <div style={{ fontSize: 110, fontWeight: 700, letterSpacing: "-0.04em", lineHeight: 1 }}>
            Can it <span style={{ color: C.pink }}>sell?</span>
          </div>
        </Rise>
        <div style={{ height: 30 }} />
        <Rise at={w(8)}>
          <Eyebrow color="rgba(244,242,239,0.6)">$50,000 of BONK · exit cost</Eyebrow>
        </Rise>
      </div>
      <div style={{ position: "absolute", left: 120, top: 380, width: 900 }}>
        <div style={{ opacity: interpolate(frame, [w(14) - 4, w(14)], [0, 1], clamp) }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 24 }}>
            <div style={{ fontSize: 170, fontWeight: 700, letterSpacing: "-0.05em", lineHeight: 1, color: C.yellow }}>
              <Counter from={0} to={2.6} at={w(14)} frames={26} decimals={2} suffix="%" />
            </div>
            <Eyebrow color="rgba(244,242,239,0.75)" style={{ fontSize: 20 }}>
              real quote
              <br />
              jupiter · 25 oct
            </Eyebrow>
          </div>
          <div style={{ marginTop: 18, height: 26, width: 860, borderRadius: 13, background: "rgba(244,242,239,0.08)" }}>
            <div style={{ height: 26, width: `${quoteBar * 100}%`, borderRadius: 13, background: C.yellow }} />
          </div>
        </div>
        <div style={{ marginTop: 44, opacity: interpolate(frame, [w(23) - 4, w(23)], [0, 1], clamp) }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 24 }}>
            <div style={{ fontSize: 96, fontWeight: 700, letterSpacing: "-0.04em", lineHeight: 1, color: "rgba(244,242,239,0.45)", position: "relative" }}>
              <Counter from={0} to={7.6} at={w(23)} frames={26} decimals={2} suffix="%" />
              <div style={{ position: "absolute", left: -6, right: -6, top: "54%", height: 8, borderRadius: 4, background: C.pink, transform: `scaleX(${interpolate(frame, [w(27), w(27) + 10], [0, 1], clamp)})`, transformOrigin: "left" }} />
            </div>
            <Eyebrow color="rgba(244,242,239,0.5)" style={{ fontSize: 20 }}>
              textbook formula
              <br />
              2.9× too high
            </Eyebrow>
          </div>
          <div style={{ marginTop: 18, height: 26, width: 860, borderRadius: 13, background: "rgba(244,242,239,0.08)" }}>
            <div style={{ height: 26, width: `${modelBar * 100}%`, borderRadius: 13, background: "rgba(244,242,239,0.35)" }} />
          </div>
        </div>
      </div>
      <div
        style={{
          position: "absolute",
          left: 1080,
          top: 150,
          opacity: shot,
          transform: `perspective(1800px) translate(${(1 - shot) * 300 + d.x}px, ${d.y}px) rotateY(${-14 + shot * 6}deg) rotateX(4deg)`,
        }}
      >
        <BrowserFrame src="shots/try-bonk.png" url="tryhanko.vercel.app/try" width={780} crop={130} zoom={1.65} focus={[330, 500]} />
      </div>
      <Sfx at={w(3)} name="whoosh" volume={0.3} />
      <Sfx at={w(14)} name="riser" volume={0.25} />
      <Sfx at={w(17)} name="pop" volume={0.5} />
      <Sfx at={w(18)} name="whoosh" volume={0.25} />
      <Sfx at={w(27)} name="tick" volume={0.6} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 8. Drill: nine failures injected, nine held.
// ---------------------------------------------------------------------------

const FAILURES = [
  { t: "Market data down", word: 6 },
  { t: "Every source down", word: 6 },
  { t: "Quote venue rate-limits", word: 8 },
  { t: "Post reader offline", word: 6 },
  { t: "A post plants an instruction", word: 10 },
  { t: "Evidence edited afterwards", word: 13 },
  { t: "Sealed run rewritten", word: 13 },
  { t: "Source dies mid-run", word: 6 },
  { t: "Restart runs twice", word: 15 },
];

export const Drill: React.FC = () => {
  const frame = useCurrentFrame();
  const w = (i: number) => wordFrame("drill", i);
  const held = (k: number) => w(17) + k * 4;
  const big = useEnter(held(8) + 8, 12);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 120, top: 84 }}>
        <Rise at={w(1)}>
          <div style={{ fontSize: 76, fontWeight: 700, letterSpacing: "-0.03em" }}>We broke it on purpose.</div>
        </Rise>
      </div>
      <div style={{ position: "absolute", left: 120, top: 220, display: "grid", gridTemplateColumns: "repeat(3, 540px)", gap: 22 }}>
        {FAILURES.map((f, k) => {
          const isHeld = frame >= held(k);
          const named = frame >= w(f.word) && frame < w(f.word) + 18;
          const flip = interpolate(frame, [held(k), held(k) + 8], [0, 1], clamp);
          return (
            <Land key={f.t} at={w(2) + k * 3} y={30} from={0.9}>
              <div
                style={{
                  height: 168,
                  borderRadius: 18,
                  padding: "22px 26px",
                  background: isHeld ? C.surface : "#F3DDE9",
                  border: `3px solid ${isHeld ? C.goodDark : named ? C.pinkDeep : "rgba(162,48,127,0.35)"}`,
                  transform: `scale(${named ? 1.04 : 1}) rotateX(${(1 - Math.abs(flip * 2 - 1)) * 70}deg)`,
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  boxShadow: named ? "0 18px 40px rgba(162,48,127,0.25)" : "0 10px 24px rgba(23,22,20,0.08)",
                }}
              >
                <div style={{ fontSize: 34, fontWeight: 600, lineHeight: 1.15 }}>{f.t}</div>
                <div style={{ fontFamily: MONO, fontWeight: 700, fontSize: 22, letterSpacing: "0.16em", color: isHeld ? C.goodDark : C.pinkDeep }}>
                  {isHeld ? "✓ HELD" : "FAILURE INJECTED"}
                </div>
              </div>
            </Land>
          );
        })}
      </div>
      <div style={{ position: "absolute", right: 110, top: 70, opacity: big, transform: `scale(${0.6 + 0.4 * big}) rotate(-6deg)` }}>
        <div style={{ background: C.goodDark, color: C.white, borderRadius: 24, padding: "14px 34px", fontFamily: SANS, fontWeight: 700, fontSize: 84, letterSpacing: "-0.02em" }}>9 / 9 held</div>
      </div>
      {FAILURES.map((f, k) => (
        <Sfx key={f.t} at={held(k)} name="tick" volume={0.45} />
      ))}
      <Sfx at={held(8) + 8} name="chime" volume={0.6} />
      <Sfx at={held(8) + 8} name="stamp" volume={0.5} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 9. Ledger: a run every three hours, graded three days later.
// ---------------------------------------------------------------------------

const RUNS = ["run_3c3566b9d25801fa", "run_7257d19b98403293", "run_090f755ea6270ddc", "run_34b5b076ad632c2d", "run_9e333fafdd5c3c93", "run_5523fe6f67d21485"];

export const Ledger: React.FC = () => {
  const frame = useCurrentFrame();
  const w = (i: number) => wordFrame("ledger", i);
  const ticks = 8;
  const lit = interpolate(frame, [w(2), w(5) + 10], [0, ticks], clamp);
  const timeline = interpolate(frame, [w(11), w(17)], [0, 1], { ...clamp, easing: easeInOut });
  const shot = useEnter(w(9), 200, 30);
  const R = 170;
  return (
    <AbsoluteFill>
      {/* the clock: eight sealed runs a day */}
      <div style={{ position: "absolute", left: 150, top: 110, width: 2 * R + 60, height: 2 * R + 60 }}>
        <svg width={2 * R + 60} height={2 * R + 60}>
          <circle cx={R + 30} cy={R + 30} r={R} fill="none" stroke="rgba(244,242,239,0.12)" strokeWidth={4} />
          {Array.from({ length: ticks }).map((_, k) => {
            const a = (k / ticks) * Math.PI * 2 - Math.PI / 2;
            const on = Math.min(1, Math.max(0, lit - k));
            return (
              <g key={k}>
                <circle cx={R + 30 + Math.cos(a) * R} cy={R + 30 + Math.sin(a) * R} r={10 + on * 12} fill={on > 0 ? C.pink : "rgba(244,242,239,0.2)"} opacity={0.4 + on * 0.6} />
              </g>
            );
          })}
        </svg>
        <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
          <div style={{ fontSize: 120, fontWeight: 700, letterSpacing: "-0.04em", lineHeight: 1 }}>3h</div>
          <Eyebrow color="rgba(244,242,239,0.6)" style={{ fontSize: 18 }}>
            sealed, no key
          </Eyebrow>
        </div>
      </div>
      {/* the commits, in public */}
      <div style={{ position: "absolute", left: 640, top: 130, fontFamily: MONO, fontSize: 22, lineHeight: 1.85 }}>
        <Eyebrow color="rgba(244,242,239,0.5)" style={{ fontSize: 17, marginBottom: 6 }}>
          github.com/IamHarrie-Labs/hanko · commits
        </Eyebrow>
        {RUNS.map((r, k) => (
          <div key={r} style={{ opacity: interpolate(frame, [w(6) + k * 4, w(6) + k * 4 + 6], [0, 1], clamp), transform: `translateX(${interpolate(frame, [w(6) + k * 4, w(6) + k * 4 + 8], [30, 0], clamp)}px)` }}>
            <span style={{ color: C.pinkLift }}>●</span> Sealed run {r}
          </div>
        ))}
      </div>
      {/* sealed now, graded in 72 hours */}
      <div style={{ position: "absolute", left: 150, right: 900, top: 650 }}>
        <div style={{ position: "relative", height: 120, opacity: interpolate(frame, [w(11) - 6, w(11)], [0, 1], clamp) }}>
          <div style={{ position: "absolute", left: 0, right: 0, top: 54, height: 6, borderRadius: 3, background: "rgba(244,242,239,0.15)" }} />
          <div style={{ position: "absolute", left: 0, top: 54, height: 6, borderRadius: 3, width: `${timeline * 100}%`, background: C.yellow }} />
          <div style={{ position: "absolute", left: 0, top: 0, fontFamily: MONO, fontSize: 20, letterSpacing: "0.14em" }}>SEALED</div>
          <div style={{ position: "absolute", left: "45%", top: 76, fontFamily: MONO, fontSize: 20, color: "rgba(244,242,239,0.6)" }}>72 hours</div>
          <div style={{ position: "absolute", right: 0, top: 0, opacity: timeline > 0.98 ? 1 : 0.3 }}>
            <span style={{ fontFamily: MONO, fontSize: 20, letterSpacing: "0.14em", color: C.yellow }}>GRADED: HELD / PROVED WRONG</span>
          </div>
        </div>
      </div>
      <div style={{ position: "absolute", left: 1150, top: 300, opacity: shot, transform: `perspective(1800px) translateY(${(1 - shot) * 200}px) rotateY(-10deg) rotateX(3deg)` }}>
        <BrowserFrame src="shots/ledger-tokens.png" url="tryhanko.vercel.app/ledger" width={680} crop={40} zoom={1.45} focus={[320, 250]} />
      </div>
      <div style={{ position: "absolute", left: 1150, top: 160, opacity: shot }}>
        <div style={{ fontSize: 44, fontWeight: 700 }}>
          <Counter from={0} to={32} at={w(9)} frames={24} /> decisions · <Counter from={0} to={8} at={w(9)} frames={24} /> runs
        </div>
        <Eyebrow color="rgba(244,242,239,0.5)" style={{ fontSize: 17, marginTop: 6 }}>
          first day · 24 to 25 Oct 2026
        </Eyebrow>
      </div>
      {Array.from({ length: 8 }).map((_, k) => (
        <Sfx key={k} at={Math.round(w(2) + (k * (w(5) + 10 - w(2))) / 8)} name="tick" volume={0.35} />
      ))}
      <Sfx at={w(9)} name="whoosh" volume={0.3} />
      <Sfx at={w(17)} name="pop" volume={0.45} />
    </AbsoluteFill>
  );
};

// ---------------------------------------------------------------------------
// 10. Close.
// ---------------------------------------------------------------------------

export const Close: React.FC = () => {
  const frame = useCurrentFrame();
  const w = (i: number) => wordFrame("close", i);
  const end = useEnter(w(7) + 14, 200, 24);
  return (
    <AbsoluteFill>
      <div style={{ position: "absolute", left: 150, top: 190 }}>
        <Seal at={w(0) - 2} size={300} color={C.ink} label="HANKO · SEAL" />
      </div>
      <div style={{ position: "absolute", left: 540, top: 215 }}>
        <Rise at={w(1)}>
          <div style={{ fontSize: 120, fontWeight: 700, letterSpacing: "-0.045em", lineHeight: 1 }}>Don't trust the call.</div>
        </Rise>
        <Rise at={w(5)}>
          <div style={{ fontSize: 120, fontWeight: 700, letterSpacing: "-0.045em", lineHeight: 1.05, color: C.white }}>Check the receipt.</div>
        </Rise>
      </div>
      <div style={{ position: "absolute", left: 140, right: 140, top: 600, opacity: end, transform: `translateY(${(1 - end) * 40}px)`, display: "flex", alignItems: "center", gap: 50 }}>
        <div style={{ background: C.ink, color: C.white, borderRadius: 22, padding: "22px 34px", fontFamily: MONO, fontSize: 44, fontWeight: 700 }}>tryhanko.vercel.app</div>
        <div style={{ fontFamily: MONO, fontSize: 26, lineHeight: 1.6, color: C.ink }}>
          github.com/IamHarrie-Labs/hanko
          <br />
          RYO-CHAN Hackathon 2026 · Tracks 1, 2 and 3
        </div>
      </div>
      <Sfx at={w(0) - 2} name="stamp" volume={0.85} />
      <Sfx at={w(7) + 14} name="chime" volume={0.4} />
    </AbsoluteFill>
  );
};
