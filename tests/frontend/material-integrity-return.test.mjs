import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
function helper(name) {
 const begin=source.indexOf('  function '+name+'(');
 assert.ok(begin>=0, name+' exists');
 const end=source.indexOf('\n  }',begin)+4;
 return source.slice(begin,end);
}
test('audit return retains the original paginated DOM and scroll, scoped to audit and project',()=>{
 const content={scrollTop:215,firstElementChild:{querySelector:s=>s==='#materialIntegrityGroupList47'?{}:null}};
 const audit={projectId:'p',task:{task_id:'t'}};
 const context={state:{materialIntegrityAudit47:audit},pid:()=> 'p'};
 vm.createContext(context);vm.runInContext(helper('rememberMaterialIntegrityList47'),context);
 context.rememberMaterialIntegrityList47(content);
 assert.equal(audit.listView47.node,content.firstElementChild);
 assert.equal(audit.listView47.scrollTop,215);
 context.state.materialIntegrityAudit47={projectId:'other'};
 context.rememberMaterialIntegrityList47(content);
 assert.equal(context.state.materialIntegrityAudit47.listView47,undefined);
});
test('return restores immediately while checking snapshot validity without starting a scan',()=>{
 const block=source.slice(source.indexOf('  window.openMaterialIntegrityAudit47='),source.indexOf('  window.filterMaterialIntegrityGroups47='));
 assert.match(block,/restoreMaterialIntegrityList47\(\)/);
 assert.match(source,/rememberMaterialIntegrityList47\(content\)/);
 assert.match(source,/groups\?limit=1/);
});
