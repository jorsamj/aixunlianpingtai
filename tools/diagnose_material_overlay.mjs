// Test-only probes; never writes the original acceptance or business JavaScript.
import {writeFileSync,readFileSync,unlinkSync,existsSync,mkdirSync} from 'node:fs';
import {spawnSync} from 'node:child_process';
import {resolve} from 'node:path';
import {createHash} from 'node:crypto';
import {instrumentApp,instrumentPagination} from './material-overlay-probes.mjs';
const protectedFiles=['tests/browser/material-workflows.spec.mjs','static/app.js','static/modules/material-pagination-runtime.js'];
const hashes=()=>Object.fromEntries(protectedFiles.map(p=>[p,createHash('sha256').update(readFileSync(p)).digest('hex')]));
const before=hashes();
const app=instrumentApp(readFileSync(protectedFiles[1],'utf8'));
const pagination=instrumentPagination(readFileSync(protectedFiles[2],'utf8'));
for(const [name,source] of [['app',app],['pagination',pagination]]){
 const check=spawnSync(process.execPath,['--check','--input-type='+(name==='pagination'?'module':'commonjs')],{input:source,encoding:'utf8'});
 if(check.status!==0)throw new Error(`OVERLAY_INJECTION_FAILED ${name}: ${check.stderr}`);
}
if(process.argv.includes('--verify-only')){
 console.log('OVERLAY_INJECTION_VERIFIED '+JSON.stringify({hashes:before,selector:'.material-box-toggle input'}));
}else{
 const target=resolve('tests/browser/overlay-causality.diagnostic.spec.mjs');
 const output='test-results/material-overlay-diagnostic';
 if(existsSync(target))throw new Error('Refusing to overwrite existing diagnostic file');
 mkdirSync(output,{recursive:true});
 const source=`import {test} from '@playwright/test';
import {readFileSync,appendFileSync} from 'node:fs';
import {instrumentApp,instrumentPagination,installOverlayDiagnostics,finishOverlayDiagnostics} from '../../tools/material-overlay-probes.mjs';
import './material-workflows.spec.mjs';
test.beforeEach(installOverlayDiagnostics);
test.afterEach(finishOverlayDiagnostics);
`;
 let status=1;
 try{
  writeFileSync(target,source);
  status=spawnSync(process.execPath,['node_modules/@playwright/test/cli.js','test',target,'-g','manual annotation saves, survives reload, and updates the thumbnail','--output='+output,'--trace=on'],{stdio:'inherit'}).status??1;
 }finally{
  if(existsSync(target))unlinkSync(target);
  const after=hashes();
  writeFileSync(output+'/integrity.json',JSON.stringify({before,after,temporaryRemoved:!existsSync(target)},null,2));
  if(JSON.stringify(before)!==JSON.stringify(after))throw new Error('Protected original file bytes changed');
 }
 process.exitCode=status;
}
