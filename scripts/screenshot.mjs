import { chromium } from "@playwright/test";
const b = await chromium.launch({ channel: "chrome", headless: true,
  args: ["--no-sandbox","--disable-gpu-sandbox","--use-angle=swiftshader","--enable-unsafe-swiftshader"] });
const p = await b.newPage({ viewport: { width: 1400, height: 800 } });
await p.goto(process.argv[2], { waitUntil: "commit", timeout: 60000 });
for (const t of [30, 60, 100, 150]) {
  await p.waitForTimeout(t === 30 ? 30000 : (t === 60 ? 30000 : (t === 100 ? 40000 : 50000)));
  const txt = await p.evaluate(() => document.body.innerText.replace(/\s+/g," ").slice(0,150));
  console.log(`t=${t}s: ${txt}`);
}
await p.screenshot({ path: process.argv[3] });
await b.close();
