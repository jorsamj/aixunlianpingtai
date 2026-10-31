import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile,writeFile,mkdtemp,mkdir,cp,symlink,unlink,rm,readdir} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {execFileSync} from 'node:child_process';
const root=new URL('../../',import.meta.url);
const dir=new URL('static/vendor/uppy/',root);
test('Uppy official offline artifact pins Core, Dashboard and Chinese with audited hashed notices',async()=>{
 const pkg=JSON.parse(await readFile(new URL('package.json',root)));
 assert.equal(pkg.dependencies['@uppy/core'],'6.3.0');
 assert.equal(pkg.dependencies['@uppy/dashboard'],'6.0.2');
 assert.equal(pkg.dependencies['@uppy/locales'],'5.3.1');
 const manifest=JSON.parse(await readFile(new URL('manifest.json',dir)));
 for(const [name,entry] of Object.entries(manifest.files)){
  const bytes=await readFile(new URL(name,dir));
  assert.equal(bytes.length,entry.bytes,name);
  assert.equal(createHash('sha256').update(bytes).digest('hex'),entry.sha256,name);
 }
 assert.equal(manifest.embedded_versions['@uppy/core'],'6.3.0');
 assert.equal(manifest.embedded_versions['@uppy/dashboard'],'6.0.2');
 assert.ok(manifest.dependencies.length>20);
 for(const dependency of manifest.dependencies){
  assert.ok(['MIT','ISC','BSD-2-Clause','BSD-3-Clause','Apache-2.0','0BSD'].includes(dependency.license));
  assert.equal(createHash('sha256').update(await readFile(new URL(dependency.notice,dir))).digest('hex'),dependency.notice_sha256);
 }
 for(const dependency of manifest.supplemental_notices){
  assert.ok(['MIT','BSD-2-Clause'].includes(dependency.license));
  assert.equal(createHash('sha256').update(await readFile(new URL(dependency.notice,dir))).digest('hex'),dependency.notice_sha256);
 }
 assert.ok(manifest.embedded_dependency_notices.some(p=>p.name==='preact'&&p.license==='MIT'&&p.embedded_version===null));
 for(const dependency of manifest.embedded_dependency_notices)assert.ok((await readFile(new URL(dependency.notice,dir))).length>0);
 const api=await import(new URL('uppy.min.mjs',dir));
 const locale=(await import(new URL('zh_CN.mjs',dir))).default;
 assert.equal(typeof api.Uppy,'function');assert.equal(typeof api.Dashboard,'function');
 assert.equal(typeof locale.strings.browseFiles,'string');assert.match(locale.strings.browseFiles,/[\u3400-\u9fff]/);
});
test('Uppy vendor verification reproduces local package bytes without network',()=>{
 execFileSync(process.execPath,[fileURLToPath(new URL('tools/vendor_uppy.mjs',root)),'--check'],{cwd:root,encoding:'utf8'});
});

test('Uppy verifier rejects corrupted assets, missing notices and inexact pins in isolated fixtures',async()=>{
 const fixture=await mkdtemp(join(tmpdir(),'uppy-vendor-'));
 try{
  await mkdir(join(fixture,'tools'),{recursive:true});
  for(const file of ['package.json','package-lock.json','tools/vendor_uppy.mjs'])await cp(new URL(file,root),join(fixture,file));
  await cp(new URL('tools/third_party_notices',root),join(fixture,'tools/third_party_notices'),{recursive:true});
  await cp(dir,join(fixture,'static/vendor/uppy'),{recursive:true});
  await symlink(fileURLToPath(new URL('node_modules',root)),join(fixture,'node_modules'),process.platform==='win32'?'junction':'dir');
  const verify=()=>execFileSync(process.execPath,[join(fixture,'tools/vendor_uppy.mjs'),'--check'],{cwd:fixture,encoding:'utf8',stdio:'pipe'});
  verify();
  const asset=join(fixture,'static/vendor/uppy/uppy.min.css'),original=await readFile(asset);
  await writeFile(asset,'corrupt');assert.throws(verify,/Vendored artifact differs/);await writeFile(asset,original);
  const manifest=JSON.parse(await readFile(new URL('manifest.json',dir)));
  const notice=join(fixture,'static/vendor/uppy',manifest.dependencies[0].notice),noticeBytes=await readFile(notice);
  await unlink(notice);assert.throws(verify,/ENOENT/);await writeFile(notice,noticeBytes);
  const pkg=JSON.parse(await readFile(join(fixture,'package.json')));pkg.dependencies['@uppy/core']='^6.3.0';
  await writeFile(join(fixture,'package.json'),JSON.stringify(pkg));assert.throws(verify,/Exact project pin required/);
  pkg.dependencies['@uppy/core']='6.3.0';await writeFile(join(fixture,'package.json'),JSON.stringify(pkg));
  await unlink(join(fixture,'node_modules'));await mkdir(join(fixture,'node_modules'));
  for(const entry of await readdir(new URL('node_modules/',root),{withFileTypes:true})){
   if(!entry.isDirectory()||entry.name==='uppy')continue;
   await symlink(fileURLToPath(new URL('node_modules/'+entry.name,root)),join(fixture,'node_modules',entry.name),process.platform==='win32'?'junction':'dir');
  }
  await cp(new URL('node_modules/uppy/',root),join(fixture,'node_modules/uppy'),{recursive:true});
  const upstream=JSON.parse(await readFile(join(fixture,'node_modules/uppy/package.json')));upstream.license='UNKNOWN';
  await writeFile(join(fixture,'node_modules/uppy/package.json'),JSON.stringify(upstream));
  assert.throws(verify,/Unreviewed license uppy@6.0.5: UNKNOWN/);
 }finally{await rm(fixture,{recursive:true,force:true});}
});
