import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtemp,writeFile,mkdir,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {verifyVueOffline} from '../../tools/verify_vue_offline.mjs';
import {execFileSync} from 'node:child_process';

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

test('exact-SHA delivery includes both builds, preserves legacy packages and rejects a mismatched SPA',()=>{
 execFileSync('python',['-c',`
import hashlib,io,json,tempfile,zipfile
from pathlib import Path
from unittest.mock import patch
from tools.package_vue_offline import package
sha='a'*40
def archive(files,source=False):
 stream=io.BytesIO()
 with zipfile.ZipFile(stream,'w') as z:
  for name,data in files.items():z.writestr(name,data)
  if source:z.comment=sha.encode()
 return stream.getvalue()
with tempfile.TemporaryDirectory(prefix='vue-package-test-') as folder:
 root=Path(folder)
 def check(spa,bad=False,missing=False):
  source={'static/vendor/LICENSE':'keep'}
  if spa:source['frontend/vite.app.config.ts']='source'
  files={}
  for prefix in ['static/vue-catalog/']+(['static/vue-app/'] if spa and not missing else []):
   data=b'local-runtime'
   receipt={'sha':('b'*40 if bad and 'vue-app' in prefix else sha),'build_origin':'github-actions','assets':{'index.js':{'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}}}
   files[prefix+'index.js']=data;files[prefix+'offline-assets.json']=json.dumps(receipt)
  raw=archive(files);(root/'build.zip').write_bytes(raw)
  (root/'meta.json').write_text(json.dumps({'workflow_run':{'head_sha':sha},'name':'vue-catalog-preview-'+sha,'digest':'sha256:'+hashlib.sha256(raw).hexdigest()}))
  output=root/('output-'+str(spa)+str(bad)+str(missing)+'.zip')
  with patch('tools.package_vue_offline.subprocess.check_output',return_value=archive(source,True)):
   if bad or missing:
    try:package(sha,root/'build.zip',root/'meta.json',output)
    except ValueError:pass
    else:raise AssertionError('unverified SPA accepted')
    assert not output.exists()
   else:
    assert package(sha,root/'build.zip',root/'meta.json',output)['rebuilt'] is False
    with zipfile.ZipFile(output) as z:
     assert z.read('static/vendor/LICENSE')==b'keep'
     assert z.read('static/vue-catalog/index.js')==b'local-runtime'
     assert ('static/vue-app/index.js' in z.namelist()) is spa
 check(False);check(True);check(True,bad=True);check(True,missing=True)
 `],{stdio:'pipe'});
});
