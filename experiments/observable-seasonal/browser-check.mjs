import { chromium } from '/home/ubuntu/xue/node_modules/playwright/index.mjs';
import { createServer } from 'node:http';
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(here, 'docs/.observable/dist');
const output = path.resolve(here, '../../archive/observable-seasonal-v3');
await mkdir(output, {recursive:true});
const mime = {'.html':'text/html', '.js':'text/javascript', '.json':'application/json', '.css':'text/css', '.woff2':'font/woff2'};
const server = createServer(async (req, res) => {
  const file = path.resolve(root, '.'+decodeURIComponent(new URL(req.url,'http://localhost').pathname));
  try {
    if (!file.startsWith(root+path.sep)) throw Error('outside root');
    const bytes = await readFile(file);
    res.writeHead(200, {'Content-Type':mime[path.extname(file)] || 'application/octet-stream'});
    res.end(bytes);
  } catch { res.writeHead(404); res.end('Not found'); }
});
await new Promise(resolve => server.listen(0,'127.0.0.1',resolve));
const browser = await chromium.launch({executablePath:'/home/ubuntu/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
const errors = [], page = await browser.newPage({viewport:{width:1280,height:1000}});
page.on('pageerror', e=>errors.push(e.message));
const assert = (v,m) => {if(!v) throw Error(m)};
try {
  await page.goto(`http://127.0.0.1:${server.address().port}/annual-spectrum.html`);
  await page.waitForFunction(()=>document.querySelectorAll('select').length===2 && document.querySelectorAll('svg').length>=2 && document.querySelector('table'),{},{timeout:25000});
  assert((await page.locator('table').first().innerText()).includes('0.25'),'additive peak');
  const selectors=page.locator('select');
  await selectors.nth(0).selectOption({label:'改变年周期强度'});
  await page.waitForFunction(()=>document.querySelector('table')?.innerText.includes('0.75'));
  assert((await page.locator('table').first().innerText()).includes('1.25'),'amplitude sidebands');
  await page.screenshot({path:path.join(output,'notebook-desktop.png'),fullPage:true});
  await selectors.nth(0).selectOption({label:'改变年周期相位'});
  await page.waitForFunction(()=>document.querySelector('table')?.querySelectorAll('tbody tr').length===5);
  await selectors.nth(1).selectOption({label:'8'});
  await page.waitForFunction(()=>document.querySelector('table')?.innerText.includes('0.875'));
  await page.locator('input[type=range]').evaluate(el=>{el.value='0';el.dispatchEvent(new Event('input',{bubbles:true}))});
  await page.waitForFunction(()=>document.querySelector('table')?.innerText.includes('No results.'));
  const text = await page.locator('body').innerText();
  assert(await page.locator('.observablehq--error').count() === 0, 'cell error');
  assert(text.includes('trainingOnlyFit'),'attachment not displayed');
  const status = await page.locator('[data-calibration-status]').innerText();
  assert(status.includes('附件已读取') && status.includes('384') && status.includes('true'), 'Calibration values require expansion or are absent');
  await page.setViewportSize({width:390,height:844});
  await page.screenshot({path:path.join(output,'notebook-mobile.png'),fullPage:true});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'mobile overflow');
  assert(!errors.length,errors.join('\n'));
  const report={notebook_kit:'2.6.4',build:'passed',reactive_modes:true,period_control:true,zero_control:true,attachment_loaded:true,calibration_visible_without_expansion:true,mobile_no_overflow:true,browser_errors:errors,observable_account_publication:false};
  await writeFile(path.join(output,'browser-check.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
} catch(e) {
  console.log((await page.locator('body').innerText()).slice(-5000));
  throw e;
} finally {await browser.close();await new Promise(resolve=>server.close(resolve));}
