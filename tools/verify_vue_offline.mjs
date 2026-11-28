import {readFile,writeFile,readdir} from 'node:fs/promises';
import {resolve,dirname,relative,sep} from 'node:path';
import {fileURLToPath,pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';

const root=resolve(dirname(fileURLToPath(import.meta.url)),'..');
export async function verifyVueOffline(directory,{requirePages=true,sha=process.env.GITHUB_SHA||null}={}) {
  directory=resolve(directory);
  const safe=name=>{
    if(typeof name!=='string'||!name||name.includes('\\')||/^[/.]|^[a-z]+:/i.test(name))throw new Error(`Unsafe Vue asset: ${name}`);
    const path=resolve(directory,name);
    if(relative(directory,path).startsWith('..'+sep))throw new Error(`Escaped Vue asset: ${name}`);
    return path;
  };
  const manifest=JSON.parse(await readFile(safe('manifest.json'),'utf8'));
  const entries=Object.values(manifest).filter(item=>item.isEntry);
  if(entries.length!==1||entries[0].file!=='catalog-preview.js')throw new Error('Expected one stable Vue entry');
  const files=new Set(['manifest.json','catalog-preview.css']);
  for(const [key,item]of Object.entries(manifest)){
    files.add(item.file);
    for(const file of [...item.css||[],...item.assets||[]])files.add(file);
    for(const dependency of [...item.imports||[],...item.dynamicImports||[]])if(!manifest[dependency])throw new Error(`Missing manifest dependency: ${key} -> ${dependency}`);
  }
  if(requirePages){
    const pages=(await readdir(resolve(root,'frontend/src/views'))).filter(name=>name.endsWith('.vue'));
    for(const page of pages)if(!manifest[`src/views/${page}`]?.isDynamicEntry)throw new Error(`Page is not dynamically loaded: ${page}`);
  }
  const assets={};
  for(const file of [...files].sort()){
    const bytes=await readFile(safe(file));
    if(!bytes.length)throw new Error(`Empty Vue asset: ${file}`);
    assets[file]={bytes:bytes.length,sha256:createHash('sha256').update(bytes).digest('hex')};
  }
  return {sha,build_origin:process.env.GITHUB_ACTIONS==='true'?'github-actions':'local-check',assets};
}
if(process.argv[1]&&import.meta.url===pathToFileURL(resolve(process.argv[1])).href){
  const directory=resolve(root,'static/vue-catalog');
  const receipt=await verifyVueOffline(directory);
  await writeFile(resolve(directory,'offline-assets.json'),JSON.stringify(receipt,null,2)+'\n');
  console.log(`Verified ${Object.keys(receipt.assets).length} local Vue files, including every dynamic page and shared chunk`);
}
