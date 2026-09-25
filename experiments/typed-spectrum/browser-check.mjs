import { chromium } from '/home/ubuntu/xue/node_modules/playwright/index.mjs';
import { readFile, writeFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';
import path from 'node:path';

const output = process.argv[2] || '/home/ubuntu/xue-study/archive/typed-spectrum-v1';
const browser = await chromium.launch({
  executablePath: '/home/ubuntu/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',
  headless: true, args: ['--no-sandbox'],
});
const errors = [], checks = [];
const page = await browser.newPage({viewport: {width: 1440, height: 1100}});
page.on('pageerror', error => errors.push(error.message));
const assert = (value, message) => { if (!value) throw new Error(message); };
const set = async (id, value) => page.locator('#'+id).evaluate((element, value) => {
  element.value = String(value); element.dispatchEvent(new Event('input', {bubbles:true}));
}, value);
const canvases = async () => page.evaluate(() => ['initial','full','omitted'].map(id => document.getElementById(id).toDataURL()));
try {
  await page.goto(pathToFileURL(path.join(output, 'demo.html')).href);
  await page.waitForFunction(() => document.querySelectorAll('#fields tr').length === 15);
  let images = await canvases();
  assert(images[0] === images[2] && images[0] !== images[1], 'The driven field must move while the omitted-driver control stays fixed');
  const defaultRms = await page.locator('#rms').innerText();
  await page.screenshot({path: path.join(output, 'demo-desktop.png'), fullPage: true});
  checks.push({default_motion_and_control: true, default_rms: defaultRms, real_rows: 15});
  await set('time', 0);
  images = await canvases(); assert(images[0] === images[1], 't=0 fields disagree');
  await set('time', 1); await set('omega', 0);
  images = await canvases(); assert(images[0] === images[1], 'Zero wind should not transport');
  checks.push({zero_time_and_zero_driver: true});
  await set('omega', 1); await set('shape', 'quadrupole');
  images = await canvases(); const before = images[0];
  await set('view', -90);
  images = await canvases(); assert(before !== images[0], 'View control did not rotate the sphere');
  checks.push({shape_and_view_controls: true});
  const previous = await page.locator('#time').inputValue();
  await page.locator('#play').click();
  await page.waitForFunction(previous => document.getElementById('time').value !== previous, previous);
  await page.locator('#play').click();
  assert(await page.locator('#play').innerText() === '播放', 'Playback did not pause');
  checks.push({playback: true});
  await page.setViewportSize({width:390, height:844});
  await page.screenshot({path:path.join(output,'demo-mobile.png'), fullPage:true});
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'Mobile overflow');
  checks.push({mobile_no_horizontal_overflow: true});
  for (const file of ['report.json','synthetic.npz','era5-representation.npz']) {
    assert((await readFile(path.join(output,file))).length > 0, 'Missing download '+file);
  }
  assert(!errors.length, errors.join('; '));
  const report = {checks, browser_errors: errors};
  await writeFile(path.join(output,'browser-check.json'), JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
} finally { await browser.close(); }
