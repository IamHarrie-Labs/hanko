import React from "react";
import {
  AbsoluteFill,
  Audio,
  Easing,
  Img,
  Sequence,
  interpolate,
  spring,
  staticFile,
  useCurrentFrame,
  useVideoConfig,
} from "remotion";
import { noise2D } from "@remotion/noise";
import { BG, C, FG, MONO, SANS, SERIF_JP, Tone } from "./theme";
import { OVERLAP } from "./timeline";

export const clamp = { extrapolateLeft: "clamp", extrapolateRight: "clamp" } as const;
export const easeOut = Easing.bezier(0.16, 1, 0.3, 1);
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);

/** 0..1 spring that starts at `at`. Critically damped unless told otherwise. */
export const useEnter = (at: number, damping = 200, durationInFrames?: number) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  return spring({ frame: frame - at, fps, config: { damping, mass: 0.9 }, durationInFrames });
};

/** 0..1 eased progress between two frames. */
export const useProgress = (from: number, to: number, ease = easeOut) => {
  const frame = useCurrentFrame();
  return interpolate(frame, [from, to], [0, 1], { ...clamp, easing: ease });
};

export type Entrance = "circle" | "wipe-right" | "wipe-up" | "diagonal" | "iris-left" | "none";

/**
 * Every scene owns its own entrance: a clip-path reveal over the scene
 * underneath, plus a slow push-in so nothing ever sits dead still.
 */
export const SceneShell: React.FC<{
  tone: Tone;
  entrance: Entrance;
  duration: number;
  children: React.ReactNode;
}> = ({ tone, entrance, duration, children }) => {
  const frame = useCurrentFrame();
  const p = interpolate(frame, [0, OVERLAP + 4], [0, 1], { ...clamp, easing: easeInOut });
  let clipPath: string | undefined;
  if (entrance === "circle") clipPath = `circle(${p * 120}% at 50% 55%)`;
  if (entrance === "wipe-right") clipPath = `inset(0 ${100 - p * 100}% 0 0)`;
  if (entrance === "wipe-up") clipPath = `inset(${100 - p * 100}% 0 0 0)`;
  if (entrance === "iris-left") clipPath = `circle(${p * 160}% at 0% 50%)`;
  if (entrance === "diagonal") {
    const x = -40 + p * 180;
    clipPath = `polygon(0 0, ${x}% 0, ${x - 40}% 100%, 0 100%)`;
  }
  const push = interpolate(frame, [0, duration], [1.04, 1], { ...clamp, easing: Easing.out(Easing.quad) });
  return (
    <AbsoluteFill style={{ backgroundColor: BG[tone], color: FG[tone], clipPath, fontFamily: SANS }}>
      <AbsoluteFill style={{ transform: `scale(${push})` }}>{children}</AbsoluteFill>
      <Vignette tone={tone} />
    </AbsoluteFill>
  );
};

export const Vignette: React.FC<{ tone: Tone }> = ({ tone }) => (
  <AbsoluteFill
    style={{
      pointerEvents: "none",
      background:
        tone === "dark"
          ? "radial-gradient(ellipse at 50% 40%, rgba(255,255,255,0.05) 0%, rgba(0,0,0,0) 45%, rgba(0,0,0,0.45) 100%)"
          : "radial-gradient(ellipse at 50% 40%, rgba(255,255,255,0.18) 0%, rgba(0,0,0,0) 50%, rgba(0,0,0,0.12) 100%)",
    }}
  />
);

/** Film grain: a turbulence field whose seed moves every other frame. */
export const Grain: React.FC = () => {
  const frame = useCurrentFrame();
  const seed = Math.floor(frame / 2) % 12;
  return (
    <AbsoluteFill style={{ pointerEvents: "none", opacity: 0.11, mixBlendMode: "overlay" }}>
      <svg width="100%" height="100%">
        <filter id={`g${seed}`}>
          <feTurbulence type="fractalNoise" baseFrequency="0.85" numOctaves="2" seed={seed} stitchTiles="stitch" />
          <feColorMatrix type="saturate" values="0" />
        </filter>
        <rect width="100%" height="100%" filter={`url(#g${seed})`} />
      </svg>
    </AbsoluteFill>
  );
};

/** Text that rises out of a mask, the way a line of type is set. */
export const Rise: React.FC<{ at: number; children: React.ReactNode; style?: React.CSSProperties; distance?: number }> = ({
  at,
  children,
  style,
  distance = 110,
}) => {
  const p = useEnter(at, 200, 22);
  return (
    <div style={{ overflow: "hidden", display: "inline-block", verticalAlign: "bottom", paddingBottom: 6, ...style }}>
      <div style={{ transform: `translateY(${(1 - p) * distance}%)`, opacity: p > 0 ? 1 : 0 }}>{children}</div>
    </div>
  );
};

/** Scale-and-fade in with a little overshoot, for objects that land. */
export const Land: React.FC<{
  at: number;
  children: React.ReactNode;
  style?: React.CSSProperties;
  from?: number;
  y?: number;
  x?: number;
  rotate?: number;
  damping?: number;
}> = ({ at, children, style, from = 0.86, y = 40, x = 0, rotate = 0, damping = 14 }) => {
  const p = useEnter(at, damping);
  const o = useEnter(at, 200, 10);
  return (
    <div
      style={{
        opacity: o,
        transform: `translate(${(1 - p) * x}px, ${(1 - p) * y}px) scale(${from + (1 - from) * p}) rotate(${(1 - p) * rotate}deg)`,
        ...style,
      }}
    >
      {children}
    </div>
  );
};

/** Gentle organic drift for things that are resting on screen. */
export const useDrift = (seed: string, amount = 6, speed = 0.012) => {
  const frame = useCurrentFrame();
  return {
    x: noise2D(seed + "x", frame * speed, 0) * amount,
    y: noise2D(seed + "y", 0, frame * speed) * amount,
  };
};

export const Typewriter: React.FC<{ text: string; at: number; cps?: number; caret?: boolean; style?: React.CSSProperties }> = ({
  text,
  at,
  cps = 38,
  caret = true,
  style,
}) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const n = Math.max(0, Math.floor(((frame - at) / fps) * cps));
  const shown = text.slice(0, n);
  const typing = n > 0 && n < text.length;
  const blink = Math.floor(frame / 15) % 2 === 0;
  return (
    <span style={style}>
      {shown}
      {caret && frame >= at && (typing || blink) ? <span style={{ opacity: 0.8 }}>▍</span> : null}
    </span>
  );
};

export const Counter: React.FC<{
  from: number;
  to: number;
  at: number;
  frames: number;
  decimals?: number;
  prefix?: string;
  suffix?: string;
  style?: React.CSSProperties;
}> = ({ from, to, at, frames, decimals = 0, prefix = "", suffix = "", style }) => {
  const frame = useCurrentFrame();
  const v = interpolate(frame, [at, at + frames], [from, to], { ...clamp, easing: easeOut });
  return (
    <span style={{ fontVariantNumeric: "tabular-nums", ...style }}>
      {prefix}
      {v.toLocaleString("en-US", { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}
      {suffix}
    </span>
  );
};

/**
 * The hanko itself: a round seal with 判子 in the middle. Slams down from
 * above at `at`, leaving an ink ring that spreads.
 */
export const Seal: React.FC<{
  at: number;
  size: number;
  color?: string;
  paper?: string;
  label?: string;
  crack?: number; // frame at which it splits, if it does
}> = ({ at, size, color = C.pinkDeep, paper = "transparent", label = "SEALED", crack }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const t = frame - at;
  const drop = interpolate(t, [-8, 0], [2.6, 1], { ...clamp, easing: Easing.in(Easing.cubic) });
  const squash = spring({ frame: t, fps, config: { damping: 9, stiffness: 260 } });
  const scale = t < 0 ? drop : 1 + (1 - squash) * 0.08;
  const opacity = interpolate(t, [-8, -2], [0, 1], clamp);
  const ring = interpolate(t, [0, 26], [0.9, 1.9], { ...clamp, easing: easeOut });
  const ringO = interpolate(t, [0, 26], [0.55, 0], clamp);
  const split = crack === undefined ? 0 : interpolate(frame, [crack, crack + 16], [0, 1], { ...clamp, easing: easeOut });
  const half = (side: -1 | 1) => (
    <div
      style={{
        position: "absolute",
        inset: 0,
        clipPath: side < 0 ? "polygon(0 0, 54% 0, 44% 100%, 0 100%)" : "polygon(54% 0, 100% 0, 100% 100%, 44% 100%)",
        transform: `translate(${side * split * size * 0.16}px, ${split * size * 0.05}px) rotate(${side * split * 9}deg)`,
      }}
    >
      <SealFace size={size} color={color} paper={paper} label={label} />
    </div>
  );
  return (
    <div style={{ position: "relative", width: size, height: size, opacity }}>
      <div
        style={{
          position: "absolute",
          inset: 0,
          borderRadius: "50%",
          border: `${size * 0.03}px solid ${color}`,
          transform: `scale(${ring})`,
          opacity: t >= 0 ? ringO : 0,
        }}
      />
      <div style={{ position: "absolute", inset: 0, transform: `scale(${scale})` }}>
        {crack === undefined ? <SealFace size={size} color={color} paper={paper} label={label} /> : <>{half(-1)}{half(1)}</>}
      </div>
    </div>
  );
};

const SealFace: React.FC<{ size: number; color: string; paper: string; label: string }> = ({ size, color, paper, label }) => (
  <svg width={size} height={size} viewBox="0 0 200 200" style={{ display: "block" }}>
    <defs>
      <filter id="inkEdge">
        <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed="3" result="n" />
        <feDisplacementMap in="SourceGraphic" in2="n" scale="5" />
      </filter>
      <path id="sealArc" d="M 100 100 m -72 0 a 72 72 0 1 1 144 0" />
    </defs>
    <g filter="url(#inkEdge)">
      <circle cx="100" cy="100" r="94" fill={paper} stroke={color} strokeWidth="9" />
      <circle cx="100" cy="100" r="80" fill="none" stroke={color} strokeWidth="2.5" />
      <text x="100" y="128" textAnchor="middle" fontFamily={SERIF_JP} fontWeight={900} fontSize="74" fill={color}>
        判子
      </text>
      <text fontFamily={MONO} fontWeight={700} fontSize="15" letterSpacing="5" fill={color}>
        <textPath href="#sealArc" startOffset="50%" textAnchor="middle">
          {label}
        </textPath>
      </text>
    </g>
  </svg>
);

/** A browser window, for showing the real pages. */
export const BrowserFrame: React.FC<{
  src: string;
  url: string;
  width: number;
  crop?: number;
  zoom?: number;
  focus?: [number, number]; // top-left of the region to show, in the 2880x1800 capture
  style?: React.CSSProperties;
}> = ({ src, url, width, crop = 0, zoom = 1, focus = [0, 0], style }) => (
  <div
    style={{
      width,
      borderRadius: 18,
      overflow: "hidden",
      background: C.surface,
      boxShadow: "0 40px 90px rgba(0,0,0,0.35), 0 8px 24px rgba(0,0,0,0.18)",
      border: "1px solid rgba(23,22,20,0.18)",
      ...style,
    }}
  >
    <div style={{ height: 44, display: "flex", alignItems: "center", gap: 9, padding: "0 18px", background: "#D9D7D1" }}>
      {["#E06C5D", "#E5B54A", "#5CB46A"].map((c) => (
        <div key={c} style={{ width: 13, height: 13, borderRadius: 7, background: c }} />
      ))}
      <div
        style={{
          marginLeft: 16,
          flex: 1,
          height: 26,
          borderRadius: 13,
          background: C.surface,
          fontFamily: MONO,
          fontSize: 15,
          color: C.muted,
          display: "flex",
          alignItems: "center",
          paddingLeft: 16,
        }}
      >
        {url}
      </div>
    </div>
    <div style={{ overflow: "hidden", height: (width * 1800) / 2880 - crop }}>
      <Img
        src={staticFile(src)}
        style={{
          width: width * zoom,
          display: "block",
          transform: `translate(${(-focus[0] * width * zoom) / 2880}px, ${(-focus[1] * width * zoom) / 2880}px)`,
        }}
      />
    </div>
  </div>
);

export const Sfx: React.FC<{ at: number; name: string; volume?: number }> = ({ at, name, volume = 0.5 }) => (
  <Sequence from={Math.max(0, at)} durationInFrames={90} layout="none">
    <Audio src={staticFile(`sfx/${name}.wav`)} volume={volume} />
  </Sequence>
);

/** A small mono label, the site's eyebrow style. */
export const Eyebrow: React.FC<{ children: React.ReactNode; color?: string; style?: React.CSSProperties }> = ({
  children,
  color,
  style,
}) => (
  <div style={{ fontFamily: MONO, fontSize: 22, letterSpacing: "0.22em", textTransform: "uppercase", color, ...style }}>
    {children}
  </div>
);

export const mono = MONO;
