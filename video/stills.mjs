// Bundle once, render the listed frames as stills for review.
import { bundle } from "@remotion/bundler";
import { renderStill, selectComposition } from "@remotion/renderer";
import path from "path";

const frames = process.argv.slice(2).map(Number);
const browserExecutable = process.env.CHROME_PATH;
const serveUrl = await bundle({ entryPoint: path.resolve("src/index.ts") });
const composition = await selectComposition({ serveUrl, id: "HankoDemo", browserExecutable });
for (const frame of frames) {
  await renderStill({ composition, serveUrl, frame, output: `out/still_${frame}.png`, browserExecutable, scale: 0.5 });
  console.log("still", frame);
}
