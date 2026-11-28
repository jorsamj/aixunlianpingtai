import test from 'node:test';import assert from 'node:assert/strict';import{readFileSync}from'node:fs';
const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
test('审核工作台使用服务端草稿与跨页冻结选择',()=>{assert.match(source,/\/draft`/);assert.match(source,/review-selection/);assert.match(source,/negative-transfer/);assert.match(source,/ai60ReviewInspector/);assert.match(source,/review\.selected/)});

test('final review omits mappings used only by excluded candidates',async()=>{const {default:vm}=await import('node:vm');const start=source.indexOf('const label_mapping=Object.fromEntries',source.indexOf('window.completeAiReview60=async'));const end=source.indexOf(';',start);const context={review:{labelMapping:new Map([['transferred_old','person'],['remaining_old','person']]),labelSummary:[{label:'remaining_old'}]},result:null};vm.runInNewContext(source.slice(start,end).replace('const label_mapping=','result='),context);assert.equal(context.result.transferred_old,undefined);assert.equal(context.result.remaining_old,'person')});

test('review header never confuses adoption defaults with selected transfer count',()=>{assert.doesNotMatch(source,/本页已选择 \$\{selected\}/);assert.match(source,/ai60SelectionCount/)});
