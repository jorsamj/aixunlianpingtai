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
for(const file of ['annotorious.js','annotorious.css','annotorious.js.map']){
  const data=await readFile(join(root,'node_modules/@annotorious/annotorious/dist',file));
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
  method:'Exact official npm browser artifact copy; no network, compile or second bundler',
  files,dependencies:[...inventory.values()].sort((a,b)=>a.name<b.name?-1:a.name>b.name?1:0),
  embedded_svelte:{version:'4.2.20',license:'MIT',evidence:'Official source map shared/version.js',notice:'licenses/svelte-4.2.20.txt',notice_sha256:hash(svelteLicense)},
  embedded_modules:map.sources.filter(p=>p.includes('node_modules')).sort(),
  note:'Installed dependency inventory is from the lockfile; it is not a claim about every embedded dependency build version. Official artifact checksums are authoritative.'
};
await artifact('manifest.json',JSON.stringify(manifest,null,2)+'\n');
await artifact('NOTICE.txt','Annotorious 3.9.5, BSD-3-Clause, Copyright (c) 2023 Rainer Simon.\nOfficial source: https://github.com/annotorious/annotorious/tree/f780879410ff4f2d4fd0b2cb1ae1bd596a40fe65\nIncludes Svelte 4.2.20 (MIT) and additional dependency notices under licenses/.\nSource notices are retained without modification. See manifest.json for hashes and inventory.\n');
for(const [path,data] of entries){
  const target=join(output,path);
  if(check){
    if(!data.equals(await readFile(target)))throw new Error('Vendored artifact differs: '+path);
  }else{await mkdir(dirname(target),{recursive:true});await writeFile(target,data);}
}
console.log(`${check?'Verified':'Vendored'} Annotorious ${pkg.version}: ${entries.size} local artifacts and notices`);
