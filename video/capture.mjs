// Screenshots of the live site, for the proof moments in the video.
import puppeteer from "puppeteer-core";

const CHROME = process.env.CHROME_PATH;
const BASE = "https://tryhanko.vercel.app";
const browser = await puppeteer.launch({ executablePath: CHROME, headless: true });
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 2 });

async function shot(path, name, prep) {
  await page.goto(BASE + path, { waitUntil: "networkidle0", timeout: 60000 });
  await page.evaluate(() => document.fonts.ready);
  if (prep) await prep();
  await new Promise((r) => setTimeout(r, 1200));
  await page.screenshot({ path: `public/shots/${name}.png` });
  console.log("captured", name);
}

async function scrollTo(sel, offset = 90) {
  await page.evaluate((s, o) => {
    const el = document.querySelector(s);
    window.scrollTo(0, el.getBoundingClientRect().top + window.scrollY - o);
  }, sel, offset);
}

await shot("/ledger", "ledger-top");
await shot("/ledger", "ledger-tokens", () => scrollTo("#ledger-tokens-h"));
await shot("/drill", "drill", async () => {
  await page.waitForFunction(() => document.querySelectorAll(".drill-card").length === 9, { timeout: 60000 });
  await scrollTo("#drill-summary", 110);
});
await shot("/try", "try-bonk", async () => {
  await page.select("#try-token", "BONK");
  await page.evaluate(() => { document.querySelector("#try-size").value = "50000"; });
  await page.click("#try-form button[type=submit], #try-form button");
  await page.waitForFunction(() => /quoted/.test(document.querySelector("#try-output").textContent), { timeout: 60000 });
  await scrollTo("#try-form", 100);
});
await shot("/echo", "echo");
await shot("/judges", "judges");
await shot("/workbench?exclude=voice_gamma", "workbench", async () => {
  await new Promise((r) => setTimeout(r, 3000));
});
await browser.close();
