// Capture the running LOCAL demo without touching any cloud account.
import {chromium} from '@playwright/test';
import {readFileSync,mkdirSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../',import.meta.url));
const password=readFileSync(root+'.env','utf8').match(/^ADMIN_PASSWORD=(.+)$/m)?.[1];
if(!password) throw new Error('Local bootstrap required');
mkdirSync(root+'docs/screenshots',{recursive:true});
const browser=await chromium.launch();
try {
 const context=await browser.newContext({viewport:{width:1440,height:1000}});
 const page=await context.newPage();
 await page.goto('http://127.0.0.1:8180');
 await page.getByLabel('Password',{exact:true}).fill(password);
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.getByRole('heading',{name:'Your security, in focus.'}).waitFor();
 await page.locator('.stat strong').first().waitFor();
 await page.screenshot({path:root+'docs/screenshots/dashboard.png',fullPage:true});
 for(const [name,file,ready] of [['Event explorer','events','.event-list details'],['Detection rules','rules','tbody tr'],['Pipeline health','pipeline','.worker-line'],['Assets','assets','tbody tr']]) {
  await page.getByRole('button',{name,exact:true}).click();
  await page.locator(ready).first().waitFor();
  await page.screenshot({path:root+'docs/screenshots/'+file+'.png',fullPage:true});
 }
 const login=await context.request.post('http://127.0.0.1:3100/login',{data:{user:'admin',password}});
 if(!login.ok()) throw new Error('Local Grafana login failed');
 await page.goto('http://127.0.0.1:3100/d/sentinel-platform/sentinelai-platform-health');
 await page.getByText('SentinelAI platform health',{exact:true}).first().waitFor();
 await page.getByText('Stored events',{exact:true}).first().waitFor({timeout:45000});
 await page.waitForTimeout(1000);
 await page.screenshot({path:root+'docs/screenshots/grafana.png',fullPage:true});
 console.log('Captured dashboard, events, rules, pipeline, assets and Grafana.');
} finally {await browser.close();}
