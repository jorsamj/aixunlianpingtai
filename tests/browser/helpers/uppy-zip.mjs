import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {expect} from '@playwright/test';
function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function storedZip(entries) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const [name, raw] of entries) {
    const data = Buffer.isBuffer(raw) ? raw : Buffer.from(raw);
    const filename = Buffer.from(name);
    const crc = crc32(data);
    const local = Buffer.alloc(30 + filename.length);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(filename.length, 26);
    filename.copy(local, 30);
    locals.push(local, data);

    const central = Buffer.alloc(46 + filename.length);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(filename.length, 28);
    central.writeUInt32LE(offset, 42);
    filename.copy(central, 46);
    centrals.push(central);
    offset += local.length + data.length;
  }
  const centralOffset = offset;
  const centralData = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(centralData.length, 12);
  end.writeUInt32LE(centralOffset, 16);
  return Buffer.concat([...locals, centralData, end]);
}


const image=execFileSync('python',['-c',"from PIL import Image; import io,sys; b=io.BytesIO(); Image.new('RGB',(32,32),'white').save(b,format='JPEG'); sys.stdout.buffer.write(b.getvalue())"]);
export function archive(name='sample',padding=0,label='object'){return storedZip([[`images/train/${name}.jpg`,image],[`labels/train/${name}.txt`,'0 0.5 0.5 0.5 0.5\n'],['data.yaml',`train: images/train\nnames: [${label}]\n`],...(padding?[['padding.bin',Buffer.alloc(padding,77)]]:[])]);}
export async function setup(page,request){
 const r=await request.post('/api/projects',{data:{name:`Uppy隔离-${Date.now()}-${Math.random()}`,labels:[{code:'object',display_name:'对象',color:'#3b82f6'}]}});expect(r.ok()).toBeTruthy();const project=await r.json();
 await page.route('**/api/v53/bootstrap/snapshot**',route=>{const u=new URL(route.request().url());u.searchParams.set('preferred_project_id',project.id);return route.continue({url:u.toString()});});
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady && window.ZipImportRuntime))).toBe(true);
 return project;
}
export async function open(page){await page.evaluate(async()=>{const {openUppyZipView}=await import('/static/modules/uppy-zip-view.js');await openUppyZipView({poc:true});});await expect(page.locator('.uppy-Dashboard-input').first()).toBeAttached();await expect(page.locator('[data-uppy-zip-target] > .loading')).toHaveCount(0);}
const inputDirectories=[];
export function cleanupInputs(){for(const dir of inputDirectories.splice(0))fs.rmSync(dir,{recursive:true,force:true});}
export async function add(page,files){const dir=fs.mkdtempSync(path.join(os.tmpdir(),'uppy-browser-input-'));inputDirectories.push(dir);const paths=files.map(f=>{const p=path.join(dir,f.name);fs.writeFileSync(p,f.buffer);return p;});await page.locator('.uppy-Dashboard-input').first().setInputFiles(paths);}
export async function upload(page){await page.locator('.uppy-StatusBar-actionBtn--upload').click();}
export async function watch(page){await page.evaluate(()=>{window.__zipEvents=[];window.__zipOff?.();window.__zipOff=window.ZipImportRuntime.subscribeTransfers(e=>window.__zipEvents.push({type:e.type,uploadId:e.uploadId,jobId:e.jobId,name:e.file?.name,loaded:e.loaded,total:e.total}));});}
export async function successes(page,n){await expect.poll(()=>page.evaluate(()=>window.__zipEvents.filter(e=>e.type==='success').length),{timeout:60000}).toBe(n);return page.evaluate(()=>window.__zipEvents.filter(e=>e.type==='success'));}
export async function jobs(request,id){return (await (await request.get(`/api/v19/projects/${id}/import/jobs`)).json()).items||[];}
export function gateParts(page){let release;const gate=new Promise(r=>release=r);const urls=[];const install=page.route('**/api/v19/projects/*/import/uploads/*/parts/*',async route=>{urls.push(route.request().url());await gate;await route.continue().catch(()=>{});});return {urls,release,install};}
