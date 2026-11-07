// Copy the official browser distribution and audit installed dependency licenses offline.
import {readFile,writeFile,mkdir,readdir} from 'node:fs/promises';
import {resolve,dirname,join,relative} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
const output=join(root,'static/vendor/uppy'),check=process.argv.includes('--check');
const hash=data=>createHash('sha256').update(data).digest('hex');
const json=async path=>JSON.parse(await readFile(path,'utf8'));
const lock=await json(join(root,'package-lock.json')),project=await json(join(root,'package.json'));
const pins={'@uppy/core':'6.3.0','@uppy/dashboard':'6.0.2','@uppy/locales':'5.3.1',uppy:'6.0.5'};
const entries=new Map(),inventory=new Map();
const artifact=(path,data)=>entries.set(path,Buffer.isBuffer(data)?data:Buffer.from(data));
async function findPackage(name,from=root){
 let at=from;
 while(true){const dir=join(at,'node_modules',name);try{const p=await json(join(dir,'package.json'));if(p.name===name)return{dir,p};}catch{}
 const next=dirname(at);if(next===at)throw new Error('Missing installed package '+name);at=next;}
}
for(const [name,version]of Object.entries(pins)){
 if((project.dependencies?.[name]||project.devDependencies?.[name])!==version)throw new Error('Exact project pin required: '+name);
 const {p}=await findPackage(name);if(p.version!==version)throw new Error('Installed version differs: '+name);
}
async function notice(dir,name){
 const files=await readdir(dir);
 const file=files.find(x=>/^(license|copying)(\.(md|txt))?$/i.test(x));
 if(file)return readFile(join(dir,file));
 // These official packages carry the complete license in README, not a LICENSE file.
 if(['wildcard','mime-match','is-mobile'].includes(name)){
  const text=await readFile(join(dir,'README.md'),'utf8');
  if(!/Permission (is hereby granted|to use)/.test(text)||!/Copyright/.test(text))throw new Error('Incomplete README license: '+name);
  return Buffer.from(text.slice(text.search(/^## License/m)));
 }
 // These legacy, unused aggregate dependencies publish only a license declaration.
 // Retain their complete authoritative declaration/author metadata, without fabricating a notice.
 if(['combine-errors','custom-error-instance'].includes(name)){
  const p=await json(join(dir,'package.json'));
  if(!((name==='combine-errors'&&p.version==='3.0.3')||(name==='custom-error-instance'&&p.version==='2.1.1')))throw new Error('Review legacy notice '+name);
  return Buffer.from(await readFile(join(dir,'package.json'),'utf8')+'\n'+await readFile(join(dir,name==='combine-errors'?'Readme.md':'README.md'),'utf8'));
 }
 if(name==='@transloadit/types'){
  const p=await json(join(dir,'package.json'));if(p.version!=='4.5.0')throw new Error('Review missing types license for new version');
  return readFile(join(root,'tools/third_party_notices/uppy/transloadit-types-4.5.0-LICENSE'));
 }
 if(name.startsWith('@uppy/')){
  const readme=await readFile(join(dir,'README.md'),'utf8');
  if(!readme.includes('https://github.com/transloadit/uppy/blob/main/LICENSE'))throw new Error('Missing Uppy shared license reference: '+name);
  return readFile(join(root,'node_modules/uppy/LICENSE'));
 }
 throw new Error('Missing license notice for '+name);
}
async function visit(name,from=root){
 const {dir,p}=await findPackage(name,from),key=p.name+'@'+p.version;if(inventory.has(key))return;
 const declaredLicense=p.name==='combine-errors'&&p.version==='3.0.3'&&/^## License\s+MIT\s*$/m.test(await readFile(join(dir,'Readme.md'),'utf8'))?'MIT':p.license;
 if(!['MIT','ISC','BSD-2-Clause','BSD-3-Clause','Apache-2.0','0BSD'].includes(declaredLicense))throw new Error('Unreviewed license '+key+': '+p.license);
 const license=await notice(dir,name),file='licenses/'+name.replaceAll('/','__')+'-'+p.version+'.txt';
 const lockKey=relative(root,dir).replaceAll('\\','/');
 if(!lock.packages[lockKey]?.integrity)throw new Error('Missing lock integrity: '+key);
 inventory.set(key,{name:p.name,version:p.version,license:declaredLicense,...(p.name==='@transloadit/types'?{notice_source:await json(join(root,'tools/third_party_notices/uppy/transloadit-types-4.5.0-source.json'))}:{}),notice_scope:['combine-errors','custom-error-instance'].includes(p.name)?'Published declaration and author metadata only; no standalone upstream license text; unused by browser artifact':'Full upstream license notice',integrity:lock.packages[lockKey].integrity,notice:file,notice_sha256:hash(license)});
 artifact(file,license);
 for(const dep of Object.keys(p.dependencies||{}).sort())await visit(dep,dir);
}
await visit('uppy');await visit('@uppy/locales');
const files={};
const officialHashes={"uppy.min.mjs":"4f77fed780378c09bb9c1cb818b9cadd21ab0f644070de1731e46013c352c37c","uppy.min.mjs.map":"ed1d2ff7c08e332196630bf6e17c9a14057027b31c39c6ee0a430bd67ccd1e0e","uppy.min.css":"eca17b3a6c95940f50ffac04e26122e22ff92df1d58b6a0c46f8e2f40414b892","uppy.min.css.map":"9bb57141ce821b9f2ababbe929b7824e6e4b59f21ea8f3d31f2774258ae2475c","zh_CN.mjs":"be6d395d2059d8775314d9b56af6f51ae4a89cb52124b7be1d401e244b2f3b3b"};

for(const file of ['uppy.min.mjs','uppy.min.mjs.map','uppy.min.css','uppy.min.css.map']){
 const data=await readFile(join(root,'node_modules/uppy/dist',file));if(hash(data)!==officialHashes[file])throw new Error('Official artifact hash differs: '+file);artifact(file,data);files[file]={bytes:data.length,sha256:hash(data)};
}
const locale=await readFile(join(root,'node_modules/@uppy/locales/lib/zh_CN.js'));
if(/^\s*(import|export\s+.*from)\s/m.test(locale.toString()))throw new Error('Chinese locale is no longer standalone');
if(hash(locale)!==officialHashes['zh_CN.mjs'])throw new Error('Chinese locale hash differs');
artifact('zh_CN.mjs',locale);files['zh_CN.mjs']={bytes:locale.length,sha256:hash(locale)};
const map=await json(join(root,'node_modules/uppy/dist/uppy.min.mjs.map'));
const embeddedVersions={};
for(const [i,path]of map.sources.entries())if(path.endsWith('/package.json')){
 const p=JSON.parse(map.sourcesContent[i]);if(p.license!=='MIT')throw new Error('Embedded manifest license requires review: '+p.name);
 embeddedVersions[p.name]=p.version;
 const {p:installed}=await findPackage(p.name);if(installed.version!==p.version)throw new Error('Embedded Uppy version differs: '+p.name);
}
for(const name of ['@uppy/core','@uppy/dashboard'])if(embeddedVersions[name]!==pins[name])throw new Error('Missing embedded version evidence: '+name);
const embeddedNames=[...new Set(map.sources.filter(x=>x.includes('node_modules/')).map(x=>x.split('node_modules/')[1]).map(x=>x.startsWith('@')?x.split('/').slice(0,2).join('/'):x.split('/')[0]))].sort();
for(const name of embeddedNames)if(![...inventory.values()].some(x=>x.name===name))throw new Error('Embedded package lacks audited notice: '+name);
const supplemental=[];
for(const [name,version,scope]of [['compressorjs','1.3.0','embedded banner'],['cropperjs','1.6.2','embedded banner'],['node-polyglot','2.6.0','BSD-2-Clause interpolation adaptation; embedded exact version unknown'],['regenerator-runtime','0.14.1','MIT generated runtime attribution; embedded exact version unknown']]){
 const base=join(root,'tools/third_party_notices/uppy',name+'-'+version),license=await readFile(base+'-LICENSE'),source=await json(base+'-source.json');
 if(!['MIT','BSD-2-Clause'].includes(source.license))throw new Error('Supplemental license requires review: '+name);
 const file='licenses/'+name+'-'+version+'-embedded.txt';artifact(file,license);
 supplemental.push({name,notice_source_version:version,scope,license:source.license,source,notice:file,notice_sha256:hash(license)});
}
const manifest={package:'uppy',version:pins.uppy,license:'MIT',method:'Exact official npm prebuilt ESM/CSS copy; local standalone Chinese locale; no network or bundler',files,
 embedded_versions:embeddedVersions,locale:{package:'@uppy/locales',version:pins['@uppy/locales'],source:'lib/zh_CN.js',output:'zh_CN.mjs'},
 embedded_dependency_notices:embeddedNames.map(name=>{const installed=[...inventory.values()].find(p=>p.name===name),historical=supplemental.find(p=>p.name===name);return {name,embedded_version:historical?historical.notice_source_version:null,version_evidence:historical?'Official embedded source banner':'Exact version not independently proven; source map identifies package',license:historical?.license||installed.license,notice:historical?.notice||installed.notice};}),
 dependencies:[...inventory.values()].sort((a,b)=>a.name.localeCompare(b.name,'en')),embedded_package_names:embeddedNames,embedded_modules:map.sources,supplemental_notices:supplemental,
 note:'dependencies records actual installed closure, including unused aggregate plugins. This is not the embedded build inventory. Source-map manifests prove listed Uppy embedded versions; compressorjs/cropperjs banners prove 1.3.0/1.6.2. Other embedded third-party versions (including Preact) are not independently proven; corresponding permissive notices are retained, with historical notices for known drift. No Tus/Companion/plugin is instantiated by these artifacts.'};
artifact('manifest.json',JSON.stringify(manifest,null,2)+'\n');
artifact('NOTICE.txt','Uppy 6.0.5 — MIT — Copyright (c) 2018 Transloadit\nOfficial source: https://github.com/transloadit/uppy and https://registry.npmjs.org/uppy/6.0.5\nThe complete official distribution includes unused plugin code. Only consuming code chooses plugins.\nIncludes Preact and other MIT/ISC/BSD dependencies; all audited notices are retained in licenses/.\nIncludes Airbnb Polyglot BSD-2-Clause interpolation adaptation and Facebook regenerator-runtime attribution.\nSee manifest.json for exact artifact hashes, installed versus embedded version limits, and supplemental source notices.\n');
for(const [path,data]of entries){const target=join(output,path);if(check){if(!data.equals(await readFile(target)))throw new Error('Vendored artifact differs: '+path);}else{await mkdir(dirname(target),{recursive:true});await writeFile(target,data);}}
console.log(`${check?'Verified':'Vendored'} Uppy ${pins.uppy}: ${entries.size} local artifacts/notices; ${inventory.size} installed packages audited`);
