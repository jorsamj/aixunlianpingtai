import {test, expect} from '@playwright/test';

test('frozen evaluation diagnoses zero-TP class and previews real GT/FP/FN layers', async ({page}) => {
  await page.route('**/evaluation/images/**', route => route.fulfill({
    status: 200, contentType: 'image/png',
    body: Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/0ioAAAAASUVORK5CYII=', 'base64')
  }));
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state?.uiReady && window.openVersionEvaluation429)), {timeout: 20000}).toBe(true);
  await page.evaluate(() => {
    state.algorithms = [{id: 'diagnostic-algo', name: '安全帽异常检测', versions: [{
      id: 'version-1', version_name: 'V1', evaluation: {
        status: 'succeeded', snapshot_id: 'a'.repeat(64), image_count: 283,
        error_sample_count: 205,
        metrics: {'metrics/mAP50(B)': 0.298, 'metrics/recall(B)': 0.272},
        per_class: [{class_id: 0, label: 'No_helmet', precision: 0, recall: 0, map50: 0.002,
          true_positive: 0, false_positive: 0, false_negative: 85, ground_truth_count: 85}],
        weak_labels: ['No_helmet'],
        error_samples: [
          {image: 'less-severe.jpg', fp_count: 1, fn_count: 0, fp_labels: ['helmet'], fn_labels: []},
          {image: 'highest-severity.jpg', fp_count: 1, fn_count: 85, fp_labels: ['helmet'], fn_labels: ['No_helmet'],
            image_width: 100, image_height: 80,
            gt_boxes: [{box: [10, 10, 40, 45], label: 'No_helmet', matched: false}],
            pred_boxes: [{box: [51, 10, 70, 30], label: 'helmet', matched: false, confidence: 0.8}]}
        ]
      },
      iteration_decision: {
        decision_id: 'b'.repeat(64), decision: 'review_required', requires_confirmation: true,
        critical_labels: ['No_helmet'], quality_gate: {metric: 'map50', stop_threshold: 0.9, metric_value: 0.298},
        reason_codes: ['critical_class_zero_true_positives'],
        recommended_actions: ['inspect_class_mapping', 'inspect_prediction_threshold', 'review_fp_fn_samples'],
        class_diagnostics: [{label: 'No_helmet', severity: 'critical',
          code: 'zero_true_positives', true_positive: 0, false_positive: 0, false_negative: 85, recall: 0,
          recommended_actions: ['inspect_class_mapping', 'inspect_prediction_threshold']}],
        signals: {false_positive: 88, false_negative: 249, error_sample_count: 205}
      }
    }]}];
    window.openVersionEvaluation429('diagnostic-algo', 'version-1');
  });
  const dialog = page.getByRole('dialog', {name: '独立评测'});
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('.evaluation429-diagnosis-grid')).toContainText('No_helmet');
  await expect(dialog.locator('.evaluation429-diagnosis-grid')).toContainText('关键类别未检出');
  await expect(dialog.locator('.evaluation429-gallery')).toContainText('共 205 张问题图片');
  await expect(dialog.locator('.evaluation429-image-card').first()).toContainText('highest-severity.jpg');
  await expect(dialog.locator('.evaluation429-thumb img')).toHaveCount(2);
  await expect(dialog.locator('.evaluation429-image-card').first().locator('.evaluation429-thumb img'))
    .toHaveAttribute('src', /evaluation\/images\/highest-severity\.jpg$/);
  await dialog.locator('.evaluation429-image-card').first().click();
  const preview = page.getByRole('dialog', {name: '问题图片核验'});
  await expect(preview).toBeVisible();
  await expect(preview.locator('.evaluation429-stage img')).toBeVisible();
  await expect(preview.locator('[data-layer="gt"]')).toHaveCount(1);
  await expect(preview.locator('[data-layer="pred"]')).toHaveCount(1);
  await preview.getByLabel('GT 真实框（红色漏检）').uncheck();
  await expect(preview.locator('[data-layer="gt"]')).toHaveCSS('display','none');
  await expect(preview.locator('[data-layer="pred"]')).not.toHaveCSS('display','none');
  await expect(preview).toContainText('不能直接加入训练集');
  await preview.getByRole('button', {name: '返回独立评测'}).click();
  await expect(page.getByRole('dialog', {name: '独立评测'})).toBeVisible();
  await page.getByRole('dialog', {name: '独立评测'}).getByLabel('问题图片排序').selectOption('fp');
  await expect(page.getByRole('dialog', {name: '独立评测'}).locator('.evaluation429-image-card').first()).toContainText('highest-severity.jpg');
});

test('legacy error records never invent GT overlays or silently claim a preview exists', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state?.uiReady && window.openVersionEvaluation429)), {timeout: 20000}).toBe(true);
  await page.evaluate(() => {
    state.algorithms = [{id: 'legacy-a', name: '旧版模型', versions: [{
      id: 'legacy-v', version_name: '历史版本',
      evaluation: {status: 'succeeded', image_count: 2, error_samples: [{
        image: 'legacy-test.jpg', fp_count: 1, fn_count: 2
      }]}, iteration_decision: {}
    }]}];
    window.openVersionEvaluation429('legacy-a','legacy-v');
  });
  await page.getByRole('dialog', {name: '独立评测'}).locator('.evaluation429-image-card').first().click();
  const preview = page.getByRole('dialog', {name: '问题图片核验'});
  await expect(preview).toContainText('历史评测仅有 FP/FN 数量');
  await expect(preview.locator('.evaluation429-overlay')).toHaveCount(0);
});


test('failed frozen-image preview hides stale GT and prediction overlays', async ({page}) => {
  await page.route('**/evaluation/images/**', route => route.fulfill({
    status: 409, contentType: 'text/plain', body: 'snapshot mismatch'
  }));
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state?.uiReady && window.openVersionEvaluation429)), {timeout: 20000}).toBe(true);
  await page.evaluate(() => {
    state.algorithms = [{id: 'guarded-algo', name: '安全帽', versions: [{
      id: 'guarded-version', evaluation: {status: 'succeeded', error_sample_count: 1,
        error_samples: [{image: 'drift.jpg', image_width: 100, image_height: 80,
          fp_count: 1, fn_count: 1,
          gt_boxes: [{box: [10, 10, 40, 40], label: 'No_helmet', matched: false}],
          pred_boxes: [{box: [60, 10, 90, 40], label: 'helmet', matched: false, confidence: 0.9}]}]},
      iteration_decision: {}
    }]}];
    window.openVersionEvaluation429('guarded-algo','guarded-version');
  });
  await page.getByRole('dialog', {name: '独立评测'}).locator('.evaluation429-image-card').first().click();
  const dialog = page.getByRole('dialog', {name: '问题图片核验'});
  await expect(dialog.locator('.evaluation429-image-error')).toBeVisible();
  await expect(dialog.locator('.evaluation429-overlay')).toBeHidden();
  await expect(dialog.locator('.evaluation429-media img')).toBeHidden();
});
