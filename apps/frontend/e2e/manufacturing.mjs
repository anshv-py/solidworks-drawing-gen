// Browser check: enter manufacturing information (material, tolerance, datum A + flatness on a
// face) in the form, generate, and confirm the drawing passes QA.
// Usage: node e2e/manufacturing.mjs <model.step> <screenshot.png>   (API on :8000, Vite on :5173)
import { chromium } from "playwright";

const [, , modelPath, shot] = process.argv;
const base = process.env.E2E_BASE_URL ?? "http://localhost:5173";
const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH, args: ["--use-angle=swiftshader", "--enable-unsafe-swiftshader"] });
const page = await browser.newPage({ viewport: { width: 1600, height: 1200 } });
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(base);
await page.setInputFiles('[data-testid="file-input"]', modelPath);
await page.waitForSelector('[data-testid="manufacturing-form"]', { timeout: 120_000 });
const form = page.locator('[data-testid="manufacturing-form"]');
await page.selectOption('[data-testid="drawing-kind"]', "MANUFACTURING");
await form.locator("summary", { hasText: "Title block" }).click();
await page.fill('[data-testid="tb-title"]', "E2E PART");
await form.locator("summary", { hasText: "Material" }).click();
await page.fill('[data-testid="material"]', "AISI 304");
await page.fill('[data-testid="general-tol"]', "ISO 2768-mK");
await form.locator("summary", { hasText: "Drawing notes" }).click();
if (!(await page.isChecked('[data-testid="notes-enabled"]'))) throw new Error("default notes should be on");
await form.locator("summary", { hasText: "Datums" }).click();
await page.waitForSelector('[data-testid="datum-suggestion"]', { timeout: 30_000 });
const suggestion = await page.locator('[data-testid="datum-suggestion"]').innerText();
await form.getByRole("button", { name: "+ datum" }).click();
const datumTarget = form.locator("details", { hasText: "Datums" }).locator("select").nth(1);
const faceOption = await datumTarget.locator("option").nth(1).getAttribute("value");
await datumTarget.selectOption(faceOption);
await form.locator("summary", { hasText: "GD&T" }).click();
await form.getByRole("button", { name: "+ frame" }).click();
const frame = form.locator("details", { hasText: "GD&T" });
await frame.locator("select").first().selectOption("FLATNESS");
await frame.locator('input[type="checkbox"]').first().uncheck();
await frame.locator("select").nth(2).selectOption(faceOption);
await page.click('[data-testid="generate"]');
await page.waitForSelector('[data-testid="drawing-preview"]', { timeout: 300_000 });
await page.waitForFunction(() => {
  const img = document.querySelector('[data-testid="drawing-preview"]');
  return img && img.complete && img.naturalWidth > 0;
}, null, { timeout: 60_000 });
const status = await page.locator('[data-testid="drawing-result"] span').first().innerText();
await page.screenshot({ path: shot, fullPage: false });
await browser.close();
console.log(JSON.stringify({ status, suggestion: suggestion.split("\n").slice(0, 4), pageErrors: errors }, null, 1));
if (errors.length || !status.includes("passed")) process.exit(1);
