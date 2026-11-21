import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {runInNewContext} from 'node:vm';

const app=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
const styles=readFileSync(new URL('../../static/styles.css',import.meta.url),'utf8');
const lifecycleStart=app.indexOf('function resetBaseModalPresentation(){');
const lifecycleEnd=app.indexOf(' let closeModal=closeModalBase;',lifecycleStart);
const openStart=app.indexOf('function modalBase(');
const openEnd=app.indexOf(' let modal=modalBase;',openStart);
assert.ok(lifecycleStart>=0&&lifecycleEnd>lifecycleStart);
assert.ok(openStart>=0&&openEnd>openStart);
const lifecycleSource=app.slice(lifecycleStart,lifecycleEnd);
const openSource=app.slice(openStart,openEnd);

function classList(...initial){
  const values=new Set(initial);
  return {
    add(...names){names.forEach(name=>values.add(name));},
    remove(...names){names.forEach(name=>values.delete(name));},
    contains(name){return values.has(name);},
    toggle(name,force){
      const next=force===undefined?!values.has(name):!!force;
      if(next)values.add(name);else values.delete(name);
      return next;
    }
  };
}
function fixture(){
  const focusCalls=[];
  const card={classList:classList('modal-card','wide','ai-review-workbench-modal','annotation-workbench-modal','training-create-modal-card')};
  const input={focus(options){focusCalls.push(options)}};
  const layer={classList:classList('modal','hidden','v424-modal-layer','ai-review-workbench-layer','annotation-workbench-layer','training-create-modal-layer','import350-modal','import350-minimized'),querySelector(selector){
    if(selector==='.modal-card')return card;
    if(selector.startsWith('#modalBody '))return input;
    return null;
  }};
  const body={innerHTML:'old dialog contents',scrollTop:260};
  const title={textContent:'old'};
  const nodes={'#modal':layer,'#modalBody':body,'#modalTitle':title,'#modal .modal-card':card};
  const context={
    $:selector=>nodes[selector]||null,
    window:{ModalContentRuntime:{replace(node,html){node.innerHTML=html;}}},
    state:{activeImage:'image-id'},
    requestAnimationFrame:callback=>callback(),
  };
  return {context,layer,card,body,title,focusCalls};
}
test('base modal close retires business layout classes but keeps infrastructure classes',()=>{
  const f=fixture();
  f.layer.classList.remove('hidden');
  runInNewContext(lifecycleSource+'\ncloseModalBase();',f.context);
  assert.equal(f.layer.classList.contains('hidden'),true);
  assert.equal(f.layer.classList.contains('modal'),true);
  assert.equal(f.layer.classList.contains('v424-modal-layer'),true);
  for(const name of ['ai-review-workbench-layer','annotation-workbench-layer','training-create-modal-layer','import350-modal','import350-minimized'])assert.equal(f.layer.classList.contains(name),false,name);
  for(const name of ['wide','ai-review-workbench-modal','annotation-workbench-modal','training-create-modal-card'])assert.equal(f.card.classList.contains(name),false,name);
  assert.equal(f.body.innerHTML,'');
  assert.equal(f.context.state.activeImage,null);
});
test('next base modal clears stale layout, resets scroll and focuses without scrolling',()=>{
  const f=fixture();
  runInNewContext(lifecycleSource+'\n'+openSource+'\nmodalBase("新弹窗","new contents",false);',f.context);
  assert.equal(f.layer.classList.contains('hidden'),false);
  assert.equal(f.layer.classList.contains('ai-review-workbench-layer'),false);
  assert.equal(f.card.classList.contains('ai-review-workbench-modal'),false);
  assert.equal(f.card.classList.contains('wide'),false);
  assert.equal(f.title.textContent,'新弹窗');
  assert.equal(f.body.innerHTML,'new contents');
  assert.equal(f.body.scrollTop,0);
  assert.equal(f.focusCalls.length,1);
  assert.equal(f.focusCalls[0]?.preventScroll,true);
});
test('active child modal can close on Escape without a visible base layer',()=>{
  assert.match(app,/if\(!window\.ModalContentRuntime\?\.activeLayer\?\.\(\)\)return;/);
  assert.match(app,/e\.preventDefault\(\);\s*void closeModal\(\);/);
});
test('modal scroll fallback is scoped and preserves specialized workbench overflow',()=>{
  assert.match(styles,/\.modal:not\(\.import350-minimized\)\{align-items:safe center;overflow-y:auto;overscroll-behavior:contain\}/);
  assert.match(styles,/\.modal:not\(\.import350-minimized\)>\.modal-card>\.modal-body\{min-height:0;overscroll-behavior:contain\}/);
  assert.match(styles,/\.ai-review-workbench-modal>\.modal-body\{[^}]*overflow:hidden!important/);
});
