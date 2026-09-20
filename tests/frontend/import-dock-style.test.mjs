import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const css = readFileSync(new URL('../../static/styles.css', import.meta.url), 'utf8');

test('material import dock uses the normal light UI surface', () => {
  const button = css.match(/\.import-dock-btn\{([^}]*)\}/);
  assert.ok(button, 'import dock button style must exist');
  assert.match(button[1], /background:#fff/);
  assert.match(button[1], /color:#0f172a/);
  assert.doesNotMatch(button[1], /background:#111827/);

  const secondary = css.match(/\.import-dock-btn small\{([^}]*)\}/);
  assert.ok(secondary, 'import dock secondary text style must exist');
  assert.match(secondary[1], /color:#64748b/);
});
