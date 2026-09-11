import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('retired V37 duplicate sidebar setPage wrapper cannot return', () => {
  assert.equal(app.includes('const baseSetPage=window.setPage;'), false);
  assert.equal(
    app.includes('window.setPage=function(page){toggleMobileSidebarV37(false);baseSetPage(page)};'),
    false,
  );
});

test('V417 remains the sole classic mobile-sidebar close owner in the final setPage chain', () => {
  assert.equal(app.includes('const baseSetPage417=window.setPage;'), true);
  assert.equal(
    app.includes('window.setPage=function(page){window.toggleMobileSidebarV37?.(false);return baseSetPage417?.(page)};'),
    true,
  );
});
