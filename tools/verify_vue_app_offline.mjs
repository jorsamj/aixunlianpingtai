import {readFile,writeFile} from 'node:fs/promises';
import {resolve,dirname} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
const root=resolve(dirname(fileURLToPath(import.meta.url)),'..'),directory=resolve(root,'static/vue-app');
const head=execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim();
if(process.env.GITHUB_SHA&&process.env.GITHUB_SHA!==head)throw new Error('SPA source SHA does not match checkout');
const manifest=JSON.parse(await readFile(resolve(directory,'manifest.json'),'utf8'));
const files=new Set(['manifest.json','index.html']);
for(const item of Object.values(manifest)){
 files.add(item.file);for(const name of [...item.css||[],...item.assets||[]])files.add(name);
 for(const dependency of [...item.imports||[],...item.dynamicImports||[]])if(!manifest[dependency])throw new Error(`Missing SPA dependency: ${dependency}`);
}
const entry=manifest['index.html'];if(!entry?.isEntry)throw new Error('Missing independent SPA entry');
const html=await readFile(resolve(directory,'index.html'),'utf8');
for(const [,url]of html.matchAll(/<(?:script|link)\b[^>]*(?:src|href)="([^"]+)"/g)){
 if(!url.startsWith('/app/')||!files.has(url.slice(5)))throw new Error(`Nonlocal/unlisted SPA entry resource: ${url}`);
}
const assets={};
for(const name of [...files].sort()){
 if(!name||name.includes('\\')||name.split('/').some(part=>part==='..')||name.startsWith('/')||name.includes(':'))throw new Error('Unsafe SPA asset');
 const bytes=await readFile(resolve(directory,name));if(!bytes.length)throw new Error(`Empty SPA asset ${name}`);
 if(/\.(?:js|css)$/.test(name)&&/(?:from\s*|import\s*\(|url\(\s*)['"]?https?:\/\//.test(bytes.toString()))throw new Error(`Remote runtime dependency in ${name}`);
 assets[name]={bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')};
}
await writeFile(resolve(directory,'offline-assets.json'),JSON.stringify({sha:process.env.GITHUB_SHA||null,checkout_sha:head,build_origin:process.env.GITHUB_ACTIONS==='true'?'github-actions':'local-check',assets},null,2)+'\n');
console.log(`Verified independent SPA: ${Object.keys(assets).length} local resources; checkout ${head}; ${process.env.GITHUB_ACTIONS==='true'?'CI-bound':'local-check'}`);
