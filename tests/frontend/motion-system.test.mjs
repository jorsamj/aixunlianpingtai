import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const styles = fs.readFileSync(new URL('../../static/styles.css', import.meta.url), 'utf8');

test('active UI motion uses one compact token system', () => {
  for (const token of [
    '--motion-fast:.14s',
    '--motion-base:.16s',
    '--motion-panel:.18s',
    '--motion-progress:.24s',
    '--motion-ease:cubic-bezier(.22,1,.36,1)',
  ]) {
    assert.equal(styles.includes(token), true, 'missing motion token: ' + token);
  }

  assert.match(styles, /\.progress424 i\{[^}]*transition:transform var\(--motion-progress\) var\(--motion-ease\)/);
  assert.match(styles, /\.op427-progress>i>em\{[^}]*transition:transform var\(--motion-progress\) var\(--motion-ease\)/);
  assert.match(styles, /\.boot413-progress>i>em\{[^}]*transition:transform var\(--motion-progress\) var\(--motion-ease\)/);
  assert.equal(styles.includes('animation:algCategoryIn var(--motion-base) var(--motion-ease)'), true);
  assert.equal(styles.includes('animation:algVersionReveal var(--motion-panel) var(--motion-ease)'), true);
  assert.equal(styles.includes('animation:train428BatchIn var(--motion-base) var(--motion-ease)'), true);
});

test('active motion still respects reduced-motion preference', () => {
  assert.equal(styles.includes('prefers-reduced-motion: reduce'), true);
  assert.equal(styles.includes('.progress424 i'), true);
  assert.equal(styles.includes('.boot413-progress>i>em'), true);
  assert.equal(styles.includes('.alg-category-popover{animation:none}'), true);
  assert.equal(styles.includes('.alg428-asset-row .alg428-versions{animation:none}'), true);
});
