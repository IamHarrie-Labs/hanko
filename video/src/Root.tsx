import React from "react";
import { Composition } from "remotion";
import { Main } from "./Main";
import { FPS, TEASER_IDS, TEASER_TOTAL, TOTAL } from "./timeline";

export const Root: React.FC = () => (
  <>
    <Composition id="HankoDemo" component={Main} durationInFrames={TOTAL} fps={FPS} width={1920} height={1080} />
    <Composition
      id="HankoTeaser"
      component={Main}
      defaultProps={{ ids: TEASER_IDS }}
      durationInFrames={TEASER_TOTAL}
      fps={FPS}
      width={1920}
      height={1080}
    />
  </>
);
