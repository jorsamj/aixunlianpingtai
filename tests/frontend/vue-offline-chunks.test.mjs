import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {verifyVueOffline} from '../../tools/verify_vue_offline.mjs';

test('offline closure includes lazy and shared chunks and rejects missing or escaped files',async()=>{
 const dir=await mkdtemp(join(tmpdir(),'vue-chunks-'));
 try{
  await mkdir(join(dir,'chunks'));
  const manifest={entry:{file:'catalog-preview.js',isEntry:true,dynamicImports:['page']},page:{file:'chunks/page-hash.js',isDynamicEntry:true,imports:['shared']},shared:{file:'chunks/shared-hash.js'}};
  for(const file of ['catalog-preview.js','catalog-preview.css','chunks/page-hash.js','chunks/shared-hash.js'])await writeFile(join(dir,file),'local bytes');
  const save=()=>writeFile(join(dir,'manifest.json'),JSON.stringify(manifest));await save();
  const receipt=await verifyVueOffline(dir,{requirePages:false,sha:'exact-sha'});
  assert.equal(receipt.sha,'exact-sha');assert.equal(Object.keys(receipt.assets).length,5);assert.match(receipt.assets['chunks/shared-hash.js'].sha256,/^[a-f0-9]{64}$/);
  await rm(join(dir,'chunks/shared-hash.js'));await assert.rejects(()=>verifyVueOffline(dir,{requirePages:false}),/ENOENT/);
  manifest.shared.file='../outside.js';await save();await assert.rejects(()=>verifyVueOffline(dir,{requirePages:false}),/Unsafe/);
  manifest.shared.file='https://cdn.invalid/runtime.js';await save();await assert.rejects(()=>verifyVueOffline(dir,{requirePages:false}),/Unsafe/);
  delete manifest.shared;await save();await assert.rejects(()=>verifyVueOffline(dir,{requirePages:false}),/Missing manifest dependency/);
 }finally{await rm(dir,{recursive:true,force:true})}
});
