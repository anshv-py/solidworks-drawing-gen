// Browser check: upload STEP -> analysis -> Generate drawing -> preview + QA + PDF download.
// Usage: node e2e/drawing.mjs <model.step> <screenshot.png>   (API on :8000, Vite on :5173)
import { chromium } from "playwright";

const [, , modelPath, shot] = process.argv;
const base = process.env.E2E_BASE_URL ?? "http://localhost:5173";
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(base);
await page.setInputFiles('[data-testid="file-input"]', modelPath);
await page.waitForSelector('[data-testid="feature-table"]', { timeout: 120_000 });
await page.click('[data-testid="generate"]');
await page.waitForSelector('[data-testid="drawing-preview"]', { timeout: 300_000 });
await page.waitForFunction(() => {
  const img = document.querySelector('[data-testid="drawing-preview"]');
  return img && img.complete && img.naturalWidth > 0;
}, null, { timeout: 60_000 });
const status = await page.locator('[data-testid="drawing-result"] span').first().innerText();
const pdfHref = await page.getAttribute('[data-testid="download-pdf"]', "href");
const pdf = await page.request.get(new URL(pdfHref, base).toString());
const pdfOk = pdf.ok() && (await pdf.body()).subarray(0, 5).toString() === "%PDF-";
await page.screenshot({ path: shot, fullPage: false });
await browser.close();
console.log(JSON.stringify({ status, pdfOk, pageErrors: errors }, null, 1));
if (errors.length || !pdfOk || !status.includes("passed")) process.exit(1);
