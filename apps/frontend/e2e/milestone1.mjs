// Milestone 1 browser check: upload STEP -> analysis job -> features table -> 3D preview.
// Usage: node e2e/milestone1.mjs <model.step> <screenshot.png>   (API on :8000, Vite on :5173)
import { chromium } from "playwright";

const [, , modelPath, shot] = process.argv;
const base = process.env.E2E_BASE_URL ?? "http://localhost:5173";
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1600, height: 900 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(base);
await page.setInputFiles('[data-testid="file-input"]', modelPath);
await page.waitForSelector('[data-testid="feature-table"]', { timeout: 120_000 });
await page.waitForSelector('[data-testid="model-viewer"] canvas', { timeout: 30_000 });
const rows = await page.locator('[data-testid="feature-table"] tbody tr').allInnerTexts();
const bbox = await page.locator('[data-testid="bbox"]').innerText();
const pattern = page.locator('[data-testid="feature-table"] tbody tr', { hasText: "PATTERN" });
if (await pattern.count()) await pattern.first().click();
await page.waitForTimeout(500);
// sample the WebGL canvas to prove something was actually rendered
const nonBlank = await page.evaluate(() => {
  const c = document.querySelector('[data-testid="model-viewer"] canvas');
  const probe = document.createElement("canvas");
  probe.width = 64; probe.height = 64;
  const ctx = probe.getContext("2d");
  ctx.drawImage(c, 0, 0, 64, 64);
  const d = ctx.getImageData(0, 0, 64, 64).data;
  const colours = new Set();
  for (let i = 0; i < d.length; i += 4) colours.add(`${d[i]},${d[i + 1]},${d[i + 2]}`);
  return colours.size;
});
await page.screenshot({ path: shot });
await browser.close();
console.log(JSON.stringify({ bbox, features: rows.length, distinctColoursInViewer: nonBlank, pageErrors: errors }, null, 1));
if (errors.length || rows.length === 0 || nonBlank < 5) process.exit(1);
