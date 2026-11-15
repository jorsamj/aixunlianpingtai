// Reproduce the official browser distribution locally; no bundler or network.
import {readFile, writeFile, mkdir} from 'node:fs/promises';
import {resolve, dirname, join, relative} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const output=join(root,'static/vendor/annotorious');
const check=process.argv.includes('--check');
const hash=data=>createHash('sha256').update(data).digest('hex');
const json=async path=>JSON.parse(await readFile(path,'utf8'));
const lock=await json(join(root,'package-lock.json'));
const pkg=await json(join(root,'node_modules/@annotorious/annotorious/package.json'));
if(pkg.version!=='3.9.5')throw new Error('Annotorious must be pinned to 3.9.5');
const entries=new Map(),inventory=new Map();
async function artifact(path,data){
  entries.set(path,Buffer.isBuffer(data)?data:Buffer.from(data));
}
async function findPackage(name,from=root){
  let at=from;
  while(true){
    const dir=join(at,'node_modules',name);
    try{const p=await json(join(dir,'package.json'));if(p.name===name)return {dir,p};}catch{}
    const next=dirname(at);if(next===at)throw new Error('Missing installed package '+name);at=next;
  }
}
async function notice(dir,name){
  for(const file of ['LICENSE','LICENSE.md','LICENSE.txt','license','license.md','COPYING']){
    try{return await readFile(join(dir,file));}catch{}
  }
  if(name.startsWith('@annotorious/'))return readFile(join(root,'tools/third_party_notices/annotorious-LICENSE'));
  throw new Error('Missing license notice for '+name);
}
async function visit(name,from=root){
  const {dir,p}=await findPackage(name,from),key=p.name+'@'+p.version;
  if(inventory.has(key))return;
  if(!['BSD-3-Clause','BSD-2-Clause','MIT','ISC'].includes(p.license))throw new Error('Unreviewed license '+key+': '+p.license);
  const license=await notice(dir,p.name),file='licenses/'+p.name.replaceAll('/','__')+'-'+p.version+'.txt';
  const lockKey=relative(root,dir).replaceAll('\\','/');
  inventory.set(key,{name:p.name,version:p.version,license:p.license,integrity:lock.packages[lockKey]?.integrity,notice:file,notice_sha256:hash(license)});
  await artifact(file,license);
  for(const dep of Object.keys(p.dependencies||{}).sort())await visit(dep,dir);
}
await visit('@annotorious/annotorious');
const files={};
const patchedUpstreamSha='66a2ac758870234b7102b5e6ad93082c4f8bb23d0d47b296df7e032f2c92a1c5';
const firstHistoryFrom="if(v-r>gs)o.splice(i+1),o.push(y),i=o.length-1;else{const w=o.length-1;o[w]=fs(o[w],y)}";
const firstHistoryTo="if(v-r>gs||o.length===0)o.splice(i+1),o.push(y),i=o.length-1;else{const w=o.length-1;o[w]=fs(o[w],y)}";
for(const file of ['annotorious.js','annotorious.css','annotorious.js.map']){
  let data=await readFile(join(root,'node_modules/@annotorious/annotorious/dist',file));
  if(file==='annotorious.js'){
    // Official 3.9.5 can merge the first change into an empty undo history if
    // performance.now() <= 250ms, throwing in its own undo coalescer.
    // Verify exact upstream bytes and apply ONLY this reviewed one-site guard.
    if(hash(data)!==patchedUpstreamSha)throw new Error('Unreviewed upstream Annotorious bytes');
    const upstream=data.toString('utf8');
    if(upstream.split(firstHistoryFrom).length!==2)
      throw new Error('Annotorious first-history patch site was not unique');
    data=Buffer.from(upstream.replace(firstHistoryFrom,firstHistoryTo),'utf8');
  }
  await artifact(file,data);files[file]={bytes:data.length,sha256:hash(data)};
}
const map=await json(join(root,'node_modules/@annotorious/annotorious/dist/annotorious.js.map'));
const versionAt=map.sources.findIndex(p=>p.endsWith('svelte/src/shared/version.js'));
if(versionAt<0||!map.sourcesContent[versionAt].includes("VERSION = '4.2.20'"))throw new Error('Embedded Svelte version requires review');
const svelteLicense=await readFile(join(root,'tools/third_party_notices/svelte-4.2.20-LICENSE.md'));
await artifact('licenses/svelte-4.2.20.txt',svelteLicense);
const manifest={
  package:pkg.name,version:pkg.version,license:pkg.license,
  upstream_git_head:'f780879410ff4f2d4fd0b2cb1ae1bd596a40fe65',
  method:'Pinned official npm browser artifact plus one audited first-history guard patch; no network or new bundler',
  patches:{'annotorious.js':{
    upstream_sha256:patchedUpstreamSha,
    description:'History coalescer must append, not merge, when there is no previous change and first input arrives before 250ms',
    original:firstHistoryFrom,
    replacement:firstHistoryTo,
    source_map_note:'Unmodified upstream source map; generated offsets after the insertion may differ',
  }},
  files,dependencies:[...inventory.values()].sort((a,b)=>a.name<b.name?-1:a.name>b.name?1:0),
  embedded_svelte:{version:'4.2.20',license:'MIT',evidence:'Official source map shared/version.js',notice:'licenses/svelte-4.2.20.txt',notice_sha256:hash(svelteLicense)},
  embedded_modules:map.sources.filter(p=>p.includes('node_modules')).sort(),
  note:'Installed dependency inventory is from the lockfile; upstream artifact checksum is verified before applying the one-site patch. The unchanged official source map may have shifted generated offsets after the patch; this is not a claim of byte-identical upstream JS.'
};
await artifact('manifest.json',JSON.stringify(manifest,null,2)+'\n');
await artifact('NOTICE.txt','Annotorious 3.9.5, BSD-3-Clause, Copyright (c) 2023 Rainer Simon.\nOfficial source: https://github.com/annotorious/annotorious/tree/f780879410ff4f2d4fd0b2cb1ae1bd596a40fe65\nLocal modification: one first-history empty-stack guard in annotorious.js; exact upstream SHA256 and patch recorded in manifest.json.\nOfficial source map retained unmodified; offsets beyond the local insertion may differ.\nIncludes Svelte 4.2.20 (MIT) and additional dependency notices under licenses/.\nUpstream license notices retained without modification.\n');
for(const [path,data] of entries){
  const target=join(output,path);
  if(check){
    if(!data.equals(await readFile(target)))throw new Error('Vendored artifact differs: '+path);
  }else{await mkdir(dirname(target),{recursive:true});await writeFile(target,data);}
}
console.log(`${check?'Verified':'Vendored'} Annotorious ${pkg.version}: ${entries.size} local artifacts and notices`);
