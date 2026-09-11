import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const navigation = fs.readFileSync(new URL('../../static/modules/navigation-stability.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

test('retired V37 duplicate sidebar setPage wrapper cannot return', () => {
  assert.equal(app.includes('const baseSetPage=window.setPage;'), false);
  assert.equal(
    app.includes('window.setPage=function(page){toggleMobileSidebarV37(false);baseSetPage(page)};'),
    false,
  );
});

test('V417 classic mobile-sidebar setPage owner cannot return', () => {
  assert.equal(app.includes('baseSetPage417'), false);
  assert.equal(
    app.includes('window.setPage=function(page){window.toggleMobileSidebarV37?.(false);return baseSetPage417?.(page)};'),
    false,
  );
  assert.equal(navigation.includes('beforeInvokeNavigation'), true, 'final navigation must own pre-invoke UI cleanup');
  assert.equal(
    main.includes('beforeInvokeNavigation: () => window.toggleMobileSidebarV37?.(false),'),
    true,
    'mobile sidebar close semantic wiring must remain in the named runtime',
  );
});

test('initial bootstrap setPage binding remains for its separate liveness audit', () => {
  assert.equal(app.includes('function setPage(p){state.page=p;render()} window.setPage=setPage;'), true);
});
