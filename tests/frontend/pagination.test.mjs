import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {
  normalizePagination,
  paginationTokens,
  renderPagination,
  validatePageInput,
} from '../../static/modules/pagination.js';


test('pagination normalizes zero and clamps display metadata', () => {
  assert.deepEqual(normalizePagination({page: 9, pageSize: 20, total: 0}), {
    page: 1,
    pageSize: 20,
    total: 0,
    totalPages: 1,
    hasPrevious: false,
    hasNext: false,
    loading: false,
    error: '',
  });
  assert.deepEqual(normalizePagination({page: 3, pageSize: 10, total: 28}), {
    page: 3,
    pageSize: 10,
    total: 28,
    totalPages: 3,
    hasPrevious: true,
    hasNext: false,
    loading: false,
    error: '',
  });
});


test('pagination tokens keep endpoints and use ellipsis for large ranges', () => {
  assert.deepEqual(paginationTokens(1, 2), [1, 2]);
  assert.deepEqual(paginationTokens(1, 28), [1, 2, 3, 4, 5, 'ellipsis', 28]);
  assert.deepEqual(paginationTokens(14, 28), [1, 'ellipsis', 12, 13, 14, 15, 16, 'ellipsis', 28]);
  assert.deepEqual(paginationTokens(28, 28), [1, 'ellipsis', 24, 25, 26, 27, 28]);
});


test('page jump validation rejects empty, fractional, negative and overflow values', () => {
  assert.equal(validatePageInput('', 28).ok, false);
  assert.equal(validatePageInput('1.5', 28).ok, false);
  assert.equal(validatePageInput('-2', 28).ok, false);
  assert.equal(validatePageInput('abc', 28).ok, false);
  assert.match(validatePageInput('99999', 28).error, /1-28/);
  assert.deepEqual(validatePageInput(' 15 ', 28), {ok: true, page: 15, error: ''});
});


test('rendered pagination exposes accessible controls and authoritative totals', () => {
  const html = renderPagination({page: 3, pageSize: 50, total: 1379});
  assert.match(html, /data-pagination-page="2"/);
  assert.match(html, /aria-current="page"[^>]*>3</);
  assert.match(html, /data-pagination-page="28"/);
  assert.match(html, /前往/);
  assert.match(html, /data-pagination-jump/);
  assert.match(html, /共 1379 条 · 28 页 · 当前第 3 页/);
  assert.match(html, /aria-label="分页导航"/);
});


test('loading state disables navigation and optional page-size remains bounded', () => {
  const html = renderPagination(
    {page: 2, pageSize: 20, total: 80, loading: true},
    {showPageSize: true, pageSizes: [10, 20, 50, 100]},
  );
  assert.match(html, /aria-busy="true"/);
  assert.match(html, /data-pagination-page="1"[^>]*disabled/);
  assert.match(html, /data-pagination-size[^>]*disabled/);
  assert.match(html, /<option value="20" selected>/);
});


test('pagination component stays presentation-only without a business API or data owner', () => {
  const source = fs.readFileSync(
    new URL('../../static/modules/pagination.js', import.meta.url),
    'utf8',
  );
  assert.doesNotMatch(source, /\bfetch\s*\(/);
  assert.doesNotMatch(source, /\/api\//);
  assert.doesNotMatch(source, /items\s*=/);
  assert.match(source, /onPageChange/);
  assert.match(source, /onPageSizeChange/);
});


test('shared pagination styles cover focus, disabled, loading and narrow containers', () => {
  const styles = fs.readFileSync(
    new URL('../../static/styles.css', import.meta.url),
    'utf8',
  );
  assert.match(styles, /\.platform-pagination\{/);
  assert.match(styles, /\.platform-pagination button:focus-visible/);
  assert.match(styles, /\.platform-pagination button:disabled/);
  assert.match(styles, /\.platform-pagination\.is-loading/);
  assert.match(styles, /@media\(max-width:700px\)[\s\S]*\.platform-pagination__controls/);
});
