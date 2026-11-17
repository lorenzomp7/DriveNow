/** Exercise the actual Playwriter MCP tools against a fresh Chrome profile. */
import {spawn} from 'node:child_process';
import {mkdtemp, readFile, rm, mkdir, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
import net from 'node:net';
import {fileURLToPath} from 'node:url';
import {Client} from '@modelcontextprotocol/sdk/client/index.js';
import {StdioClientTransport} from '@modelcontextprotocol/sdk/client/stdio.js';
import {startPlayWriterCDPRelayServer} from 'playwriter';

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, '../..');
const url = process.argv[2];
if (!url || !['http:', 'https:'].includes(new URL(url).protocol)) throw new Error('Provide the demo HTTP URL');
const chrome = process.env.DRIVENOW_CHROMIUM;
if (!chrome) throw new Error('Set DRIVENOW_CHROMIUM to the Chrome/Chromium executable');
const output = path.join(root, 'test-results/playwriter');
await mkdir(output, {recursive: true});
const temp = await mkdtemp(path.join(tmpdir(), 'drivenow-playwriter-'));
const port = await new Promise(resolve => {const server = net.createServer(); server.listen(0, '127.0.0.1', () => {const p = server.address().port; server.close(() => resolve(p));});});
const relay = await startPlayWriterCDPRelayServer({port, host:'127.0.0.1', sessionCounterFile:path.join(temp,'counter.json')});
const args = ['--headless=new', '--remote-debugging-address=127.0.0.1', '--remote-debugging-port=0', `--user-data-dir=${temp}/chrome`, '--no-first-run', '--no-default-browser-check', '--disable-background-networking', '--disable-component-update', '--disable-default-apps', '--disable-dev-shm-usage', '--disable-gpu', '--password-store=basic', 'about:blank'];
if (process.env.DRIVENOW_CHROME_NO_SANDBOX === '1') args.unshift('--no-sandbox');
const browser = spawn(chrome, args, {stdio:['ignore','ignore','pipe']});
let browserError = '';
browser.stderr.on('data', data => {browserError = (browserError + data).slice(-12000);});
browser.on('error', error => {browserError = error.message;});
const client = new Client({name:'drivenow-playwriter-check', version:'1.0.0'});
const transport = new StdioClientTransport({command:process.execPath, args:[path.join(here,'node_modules/playwriter/bin.js')],
  env:{...process.env, PLAYWRITER_PORT:String(port), PLAYWRITER_TELEMETRY:'0', DO_NOT_TRACK:'1'}});
const checks = [];
async function call(name, arguments_) {
  const result = await client.callTool({name, arguments:arguments_}, undefined, {timeout:60000});
  const text = result.content?.filter(item => item.type === 'text').map(item => item.text).join('\n') || '';
  if (result.isError) throw new Error(`Playwriter ${name}: ${text}`);
  return text;
}
async function execute(code, check) {
  const text = await call('execute', {code, timeout:45000});
  if (check) {checks.push(check); console.log(`PASS: ${check}`);}
  return text;
}
try {
  let endpoint;
  for (let attempt=0; attempt<600; attempt++) {
    if (browser.exitCode !== null || browser.signalCode !== null || browserError.includes('spawn ')) throw new Error(`Chrome exited: ${browserError}`);
    try {const [p, ws] = (await readFile(path.join(temp,'chrome/DevToolsActivePort'),'utf8')).trim().split('\n'); endpoint = `ws://127.0.0.1:${p}${ws}`; break;} catch {}
    await new Promise(resolve => setTimeout(resolve,100));
  }
  if (!endpoint) throw new Error(`Chrome debugging endpoint unavailable: ${browserError}`);
  await client.connect(transport);
  await call('session_new', {direct:endpoint});
  await execute('state.page = await context.newPage(); state.errors = []; state.page.on("pageerror", e => state.errors.push(String(e)))');
  for (const [width,height] of [[1440,900],[390,844]]) {
    const label = `${width}x${height}`;
    await execute(`await state.page.setViewportSize({width:${width},height:${height}}); await state.page.goto(${JSON.stringify(url)}, {waitUntil:"domcontentloaded"}); await state.page.waitForFunction(() => document.querySelector("#live").classList.contains("on") && document.querySelector("#clock").textContent !== "00:00", {timeout:15000})`, `live demo ${label}`);
    await execute('await state.page.waitForFunction(() => document.querySelector("#veh-tag").textContent === "Segue DriveNow" && document.querySelector("#target").textContent !== "—"); const box = await state.page.locator("#map").boundingBox(); if (!box || box.width < 100 || box.height < 100) throw new Error("Map is not visible")', `map and vehicle advice ${label}`);
    await execute('await state.page.locator("#btn-fit").click(); if (await state.page.locator("#btn-follow").getAttribute("aria-pressed") !== "false") throw new Error("Fit did not stop following"); await state.page.locator("#btn-follow").click(); if (await state.page.locator("#btn-follow").getAttribute("aria-pressed") !== "true") throw new Error("Follow toggle failed"); state.oldSelected = await state.page.evaluate(() => selected); await state.page.locator("#btn-next").click(); await state.page.waitForFunction(old => selected !== old, state.oldSelected)', `vehicle selection and follow ${label}`);
    await execute('const response = state.page.waitForResponse(r => r.url().endsWith("/api/settings") && r.request().method() === "POST"); await state.page.locator("[data-speed=\"2\"]").click(); if (!(await response).ok()) throw new Error("Settings request failed"); await state.page.waitForFunction(() => document.querySelector("#speed-seg .on")?.dataset.speed === "2")', `simulation speed ${label}`);
    await execute('state.nextPen = Number(await state.page.locator("#pen").inputValue()) > 0 ? 0 : 100; const response = state.page.waitForResponse(r => r.url().endsWith("/api/settings") && r.request().postDataJSON()?.penetration === state.nextPen/100); await state.page.locator("#pen").focus(); await state.page.locator("#pen").press(state.nextPen === 0 ? "Home" : "End"); if (!(await response).ok()) throw new Error("Penetration setting failed")', `penetration slider ${label}`);
    await execute('state.oldZoom = await state.page.evaluate(() => view.s); await state.page.locator("#map").hover(); await state.page.mouse.wheel(0,-200); await state.page.waitForFunction(old => view.s !== old, state.oldZoom); if (state.errors.length) throw new Error(state.errors.join("; "))', `zoom and JavaScript errors ${label}`);
    await execute(`await state.page.screenshot({path:${JSON.stringify(path.join(output,`${label}.png`))}, fullPage:true})`);
  }
  await call('session_delete', {closeTabs:true});
  await writeFile(path.join(output,'report.json'), JSON.stringify({status:'passed', playwriter:'0.12.0', transport:'real MCP, direct CDP', checks, personalBrowserUsed:false}, null, 2)+'\n');
  console.log('DRIVENOW_PLAYWRITER_OK');
} finally {
  await writeFile(path.join(output,'chrome-stderr.log'), browserError);
  await client.close().catch(()=>{});
  await relay.close();
  if (browser.pid && browser.exitCode === null && browser.signalCode === null) {
    browser.kill('SIGTERM');
    await new Promise(resolve => {const timer = setTimeout(()=>{browser.kill('SIGKILL'); resolve();},3000); browser.once('exit',()=>{clearTimeout(timer); resolve();});});
  }
  await rm(temp,{recursive:true,force:true,maxRetries:5,retryDelay:200});
}
