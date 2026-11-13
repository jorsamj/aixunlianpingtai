import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createNavigationPresentation} from '../../static/modules/navigation-presentation.js';

function setup(withNav=false) {
  const calls=[],summary={innerHTML:'before'},view={innerHTML:'before'},footer={textContent:'before'};
  const button={querySelector:()=>({textContent:'算力与节点'}),classList:{toggle:(name,active)=>calls.push([name,active])}};
  const nav=withNav?{querySelectorAll:()=>[button],querySelector:()=>footer}:null;
  const present=createNavigationPresentation({
    getState:()=>({page:'训练资源',versionInfo:{version:'42.24.592'}}),
    advancedPageInfo:()=>({title:'算力与节点'}),
    advancedNavigation:{render:()=>calls.push('advanced')},
    documentRoot:{getElementById:id=>({nav,summary,view})[id]||null},
    windowRoot:{
      renderNav:()=>calls.push('nav'),
      renderTop:()=>calls.push('top'),
      renderSummary:()=>calls.push('summary'),
    },
  });
  return {present,calls,summary,view,footer};
}

test('no nav DOM preserves classic fallback and paint order',()=>{
  const {present,calls}=setup();
  present.renderChrome();
  assert.deepEqual(calls,['nav','top','summary','advanced']);
});

test('existing nav DOM highlights the advanced page and retains server version',()=>{
  const {present,calls,footer}=setup(true);
  present.renderChrome();
  assert.deepEqual(calls,[['active',true],'top','summary','advanced']);
  assert.equal(footer.textContent,'v42.24.592');
});

test('unknown page clears summary and strips unsafe attribute characters',()=>{
  const {present,calls,summary,view}=setup();
  present.renderUnknown("<a&>\"'");
  assert.equal(summary.innerHTML,'');
  assert.equal(view.innerHTML,'<section class="empty" data-unknown-page="a">当前页面不存在或已下线</section>');
  assert.deepEqual(calls,['nav','top','summary','advanced']);
});

test('ESM view owns presentation only; canonical router and entry cache remain intact',()=>{
  const main=readFileSync(new URL('../../static/main.mjs',import.meta.url),'utf8');
  const html=readFileSync(new URL('../../static/index.html',import.meta.url),'utf8');
  const source=readFileSync(new URL('../../static/modules/navigation-presentation.js',import.meta.url),'utf8');
  assert.match(main,/createNavigationPresentation\(\{getState:\(\)=>state,advancedPageInfo,advancedNavigation\}\)/);
  assert.match(main,/navigationPresentation\.renderChrome\(\)/);
  assert.match(main,/navigationPresentation\.renderUnknown\(page\)/);
  assert.doesNotMatch(main,/function renderNavigationChrome\(\)/);
  assert.doesNotMatch(main,/function renderUnknownPage\(page\)/);
  assert.doesNotMatch(source,/registerPageOwner|addEventListener|setPage|window\.PlatformCore/);
  assert.match(html,/main\.mjs\?v=42\.25\.595/);
});
