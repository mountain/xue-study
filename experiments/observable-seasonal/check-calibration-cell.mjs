import {chromium} from '/home/ubuntu/xue/node_modules/playwright/index.mjs';
import {readFile, writeFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const here=path.dirname(fileURLToPath(import.meta.url));
const source=await readFile(path.join(here,'docs/annual-spectrum.html'),'utf8');
const cell=source.match(/<script id="8"[^>]*>([\s\S]*?)<\/script>/)[1];
const valid=JSON.parse(await readFile(path.join(here,'docs/annual-check.json'),'utf8'));
const browser=await chromium.launch({executablePath:'/home/ubuntu/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome',headless:true,args:['--no-sandbox']});
try {
  const page=await browser.newPage();
  const results=await page.evaluate(async ({cell,valid})=>{
    const {html}=await import('https://cdn.jsdelivr.net/npm/htl/+esm');
    const AsyncFunction=Object.getPrototypeOf(async function(){}).constructor;
    const run=new AsyncFunction('FileAttachment','display','html',cell);
    const cases={
      valid:()=>({json:async()=>valid}),
      missing:()=>{throw Error('File not found: annual-check.json')},
      network:()=>({json:async()=>{throw Error('Failed to fetch')}}),
      invalid_json:()=>({json:async()=>{throw SyntaxError('Unexpected token')}}),
      wrong_schema:()=>({json:async()=>({sample_count:384})}),
    };
    const out={};
    for(const [name,FileAttachment] of Object.entries(cases)){
      let panel,initial;
      await run(FileAttachment,node=>{panel=node;initial=node.textContent},html);
      out[name]={loading_shown:initial.includes('读取中'),text:panel.textContent.replace(/\s+/g,' ').trim()};
      if(!out[name].loading_shown)throw Error(name+' did not show loading');
      if(name==='valid'){
        if(!out[name].text.includes('附件已读取')||!out[name].text.includes('384')||!out[name].text.includes('true'))throw Error('valid data invisible');
      }else if(!out[name].text.includes('读取失败')||out[name].text.includes('附件已读取'))throw Error(name+' masked failure');
    }
    return out;
  },{cell,valid});
  await writeFile(path.resolve(here,'../../archive/observable-seasonal-v3/calibration-cell-check.json'),JSON.stringify(results,null,2)+'\n');
  console.log(JSON.stringify(results,null,2));
}finally{await browser.close()}
