import React from "react";
import { AbsoluteFill, Audio, Sequence, interpolate, staticFile } from "remotion";
import { Captions } from "./Captions";
import { Entrance, Grain, SceneShell } from "./kit";
import { Decide, Hook, Problem, Read, Reveal } from "./scenes1";
import { Close, Drill, Exit, Ledger, SealScene } from "./scenes2";
import { FPS, LEAD, SCENES, SceneTiming, build, totalOf } from "./timeline";

const SCENE: Record<string, { C: React.FC; entrance: Entrance }> = {
  hook: { C: Hook, entrance: "none" },
  problem: { C: Problem, entrance: "wipe-up" },
  reveal: { C: Reveal, entrance: "circle" },
  read: { C: Read, entrance: "diagonal" },
  decide: { C: Decide, entrance: "wipe-right" },
  seal: { C: SealScene, entrance: "iris-left" },
  exit: { C: Exit, entrance: "diagonal" },
  drill: { C: Drill, entrance: "wipe-up" },
  ledger: { C: Ledger, entrance: "wipe-right" },
  close: { C: Close, entrance: "circle" },
};

const musicVolumeFor = (scenes: SceneTiming[]) => {
  // Voice windows, so the music can sit back while someone is talking.
  const VOICE = scenes.map((s) => [s.from + LEAD, s.from + LEAD + Math.ceil(s.words[s.words.length - 1].end * FPS)]);
  const TOTAL = totalOf(scenes);
  return (f: number) => {
  const talking = VOICE.some(([a, b]) => f >= a - 6 && f <= b + 6);
  const base = talking ? 0.13 : 0.26;
  const fadeIn = interpolate(f, [0, 45], [0, 1], { extrapolateRight: "clamp" });
  const fadeOut = interpolate(f, [TOTAL - 75, TOTAL], [1, 0], { extrapolateLeft: "clamp", extrapolateRight: "clamp" });
  return base * fadeIn * fadeOut;
  };
};

export const Main: React.FC<{ ids?: string[] }> = ({ ids }) => {
  const scenes = React.useMemo(() => (ids ? build(ids) : SCENES), [ids]);
  return (
  <AbsoluteFill style={{ backgroundColor: "#171614" }}>
    {scenes.map((s) => {
      const { C, entrance } = SCENE[s.id];
      return (
        <Sequence key={s.id} from={s.from} durationInFrames={s.duration} premountFor={30}>
          <SceneShell tone={s.tone} entrance={entrance} duration={s.duration}>
            <C />
          </SceneShell>
        </Sequence>
      );
    })}
    {scenes.map((s) => (
      <Sequence key={"v" + s.id} from={s.from + LEAD} layout="none">
        <Audio src={staticFile(`voice/${s.id}.mp3`)} volume={1} />
      </Sequence>
    ))}
    <Audio src={staticFile("music.wav")} volume={musicVolumeFor(scenes)} />
    <Captions scenes={scenes} />
    <Grain />
  </AbsoluteFill>
  );
};
