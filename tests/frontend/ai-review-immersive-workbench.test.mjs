import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const html = readFileSync(new URL('../../static/index.html', import.meta.url), 'utf8');
const css = readFileSync(new URL('../../static/ai-review-immersive.css', import.meta.url), 'utf8');

test('沉浸式审核仅在原任务工作台内加载，原确认窗口层级仍高于它', () => {
  assert.match(html, /ai-review-immersive\.css\?v=42\.24\.579/);
  assert.ok(html.indexOf('ai-review-immersive.css') > html.indexOf('styles.css'));
  assert.match(css, /\.ai-review-page-shell\s*\{[^}]*position:\s*fixed\s*!important/s);
  assert.match(css, /z-index:\s*120\s*!important/);
  assert.match(css, /#ai60ReviewInspector\.open\s*\{\s*display:\s*block\s*!important/);
  assert.match(css, /@media\s*\(max-width:\s*768px\)/);
  assert.match(app, /#ai60ReviewGrid/);
  assert.match(app, /ai-review-card-grid/);
});

test('最常用五项筛选可见，低频筛选进更多菜单但入口仍保留', () => {
  const shell = app.slice(app.indexOf('function ensureReviewShell()'), app.indexOf('function aiReviewLabels60()'));
  for (const key of ['all', 'target', 'ambiguous', 'empty', 'failed']) {
    assert.match(shell, new RegExp('data-ai66-filter="' + key + '"'));
  }
  for (const key of ['edited', 'transferred', 'rejected', 'low', 'hard']) {
    assert.match(shell, new RegExp('data-ai66-filter="' + key + '"'));
  }
  assert.match(shell, /class="ai-review-filter-menu"/);
  assert.match(shell, /class="ai-review-filter-more"/);
});

test('勾选只清除过期预检反馈，不替换歧义面板或图片卡片', () => {
  const start = app.indexOf('  function invalidateAiSelectionPreview60(review){');
  const end = app.indexOf('  window.toggleAiSelection60=', start);
  assert.ok(start > 0 && end > start);
  const fn = app.slice(start, end);
  assert.doesNotMatch(fn, /outerHTML|renderReviewPage\(|patchAiAmbiguityPanel60\(/);

  const feedback = {children: ['old'], replaceChildren(...nodes) {this.children = nodes}};
  const newHint = {textContent: '预检已失效'};
  let selectionRenders = 0;
  const context = {
    document: {
      querySelector: selector => selector.includes('ai-review-ambiguity-feedback') ? feedback : null,
      createElement: () => ({
        set innerHTML(_) {},
        content: {querySelector: () => ({childNodes: [newHint]})}
      })
    },
    aiAmbiguityPanel60: () => '<section class="ai-review-ambiguity-panel"></section>',
    renderAiSelection60: () => {selectionRenders++}
  };
  vm.runInNewContext(fn + '\nthis.invalidate = invalidateAiSelectionPreview60;', context);
  const review = {ambiguityPreview: {actions: []}, ambiguityResult: '旧提示'};
  context.invalidate(review);
  assert.equal(review.ambiguityPreview, null);
  assert.equal(review.ambiguityResult, '');
  assert.equal(feedback.children[0], newHint);
  assert.equal(selectionRenders, 1);
});

test('跨页冻结选择与正式 GT 提交仍使用原有 Owner', () => {
  assert.match(app, /window\.selectAiFiltered60=async/);
  assert.match(app, /review\.selection\.excluded/);
  assert.match(app, /已排除 \$\{review\.selection\.excluded\?\.size\|\|0\} 张/);
  assert.match(app, /review-selection/);
  assert.match(app, /window\.approveAiSelected60=async/);
  assert.match(app, /commit_selected:true/);
  assert.match(app, /window\.previewAiAmbiguity60=async/);
  assert.match(app, /window\.applyAiAmbiguity60=async/);
  assert.doesNotMatch(css, /(?:\.main|\.side|\.top)\s*\{\s*display:\s*none/);
});
