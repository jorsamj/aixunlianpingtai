import test from 'node:test';import assert from 'node:assert/strict';import{readFileSync}from'node:fs';
const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
test('审核工作台使用服务端草稿与跨页冻结选择',()=>{assert.match(source,/\/draft`/);assert.match(source,/review-selection/);assert.match(source,/negative-transfer/);assert.match(source,/ai60ReviewInspector/);assert.match(source,/review\.selected/)});
