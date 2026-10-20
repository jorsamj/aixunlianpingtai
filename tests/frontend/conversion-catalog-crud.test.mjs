import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
test('deployment catalog has one embedded CRUD owner and no retired bulk editor',()=>{
 const app=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
 const main=readFileSync(new URL('../../static/main.mjs',import.meta.url),'utf8');
 assert.match(app,/conversion-catalog-host/);
 assert.match(main,/installConversionCatalogRuntime/);
 assert.doesNotMatch(app,/let conversionCatalogSession428=/);
});

test('catalog cleanup runs inside the existing actual navigation owner before page mutation',()=>{
 const main=readFileSync(new URL('../../static/main.mjs',import.meta.url),'utf8');
 assert.ok(main.includes('beforeInvokeNavigation: () => window.toggleMobileSidebarV37?.(false),'));
 const start=main.indexOf('performNavigation: page => {'),end=main.indexOf('\n  },',start),owner=main.slice(start,end);
 assert.ok(owner.indexOf('conversionCatalogRuntime.leave();')>=0);
 assert.ok(owner.indexOf('conversionCatalogRuntime.leave();')<owner.indexOf('state.page = page;'));
});
