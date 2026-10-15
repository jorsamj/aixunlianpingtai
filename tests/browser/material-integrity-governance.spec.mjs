import fs from 'node:fs';
import path from 'node:path';

import {test, expect} from '@playwright/test';


async function createProject(request) {
  const response = await request.post('/api/projects', {
    data: {
      name: `素材治理浏览器-${Date.now()}`,
      description: 'material integrity governance browser acceptance',
      labels: [{code: 'target', display_name: '目标', color: '#3b82f6'}],
    },
  });
  expect(response.ok()).toBeTruthy();
  return response.json();
}


test('global duplicate governance previews, confirms, reports progress, and invalidates the audit', async ({page, request}) => {
  await page.setViewportSize({width: 1366, height: 768});
  const project = await createProject(request);
  const auditId = 'audit-browser-governance';
  const planId = '0123456789abcdef0123456789abcdef';
  const taskId = 'delete-browser-governance';
  let planPayload = null;
  let executionPayload = null;
  let polls = 0;

  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', project.id);
    await route.fallback({url: url.toString()});
  });
  await page.route(`**/api/v62/projects/${project.id}/material-batches?limit=50`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({items: [{
      task_id: auditId,
      operation: 'AUDIT_MATERIAL_INTEGRITY',
      status: 'SUCCEEDED',
      result: {scanned_images: 15, affected_images: 8, issue_groups: 3, scan_failures: 0},
    }]}),
  }));
  await page.route(`**/api/v62/projects/${project.id}/material-integrity/audits/${auditId}/groups?limit=100`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      items: [{
        group_key: `DUPLICATE_IDENTICAL:${'a'.repeat(64)}`,
        issue_type: 'DUPLICATE_IDENTICAL',
        content_sha256: 'a'.repeat(64),
        image_count: 5,
      }],
      next_cursor: null,
    }),
  }));
  await page.route(`**/api/v62/projects/${project.id}/material-integrity/audits/${auditId}/dedup-plans`, async route => {
    planPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 201,
      contentType: 'application/json',
      body: JSON.stringify({
        plan_id: planId,
        confirmation_credential: 'browser-confirmation-credential',
        operation: 'DELETE_INDEX',
        included_groups: 1,
        kept_count: 1,
        delete_count: 4,
        skipped_groups: 2,
        skipped_item_count: 3,
        manual_required_groups: 1,
        protected_groups: 1,
        skip_reasons: {MANUAL_DECISION_REQUIRED: 1, MULTIPLE_PROTECTED_REFERENCES: 1},
        preview_groups: [{
          group_key: `DUPLICATE_IDENTICAL:${'a'.repeat(64)}`,
          keeper_image_id: 'keeper-image-001',
          keeper_reason: 'VERIFIED_SOURCE_AND_ANNOTATION',
          delete_count: 4,
        }],
        preview_groups_truncated: false,
      }),
    });
  });
  await page.route(`**/api/v62/projects/${project.id}/material-integrity/audits/${auditId}/dedup-plans/${planId}/execute`, async route => {
    executionPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 202,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: taskId,
        operation: 'DELETE_INDEX',
        status: 'QUEUED',
        total: 4,
        processed: 0,
        succeeded: 0,
        failed: 0,
        planned_groups: 1,
        completed_groups: 0,
        failed_groups: 0,
        kept_count: 1,
        skipped_groups: 2,
        material_integrity_audit_id: auditId,
        material_integrity_plan_id: planId,
      }),
    });
  });
  await page.route(`**/api/v62/projects/${project.id}/material-batches/${taskId}`, route => {
    polls += 1;
    const finished = polls > 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        task_id: taskId,
        operation: 'DELETE_INDEX',
        status: finished ? 'SUCCEEDED' : 'RUNNING',
        total: 4,
        processed: finished ? 4 : 1,
        succeeded: finished ? 4 : 1,
        failed: 0,
        planned_groups: 1,
        completed_groups: finished ? 1 : 0,
        failed_groups: 0,
        kept_count: 1,
        skipped_groups: 2,
        material_integrity_audit_id: auditId,
        material_integrity_plan_id: planId,
      }),
    });
  });
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '数据集'}));
  });

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: '重复与异常素材'}).click();
  const auditDialog = page.getByRole('dialog', {name: '重复与异常素材', exact: true});
  await expect(auditDialog).toBeVisible();
  const globalPreview = auditDialog.getByRole('button', {name: '批量去重 · 每组保留 1 张'});
  await expect(globalPreview).toBeVisible();
  await globalPreview.click();

  const previewDialog = page.getByRole('dialog', {name: '重复素材治理预览', exact: true});
  await expect(previewDialog).toBeVisible();
  await expect(previewDialog.getByText('keeper-image-001')).toBeVisible();
  await expect(previewDialog.getByText('确认删除 4 条索引')).toBeVisible();
  expect(planPayload).toEqual({scope: 'SAFE_ALL', group_keys: []});
  expect(JSON.stringify(planPayload)).not.toContain('image_ids');
  const previewBox = await previewDialog.boundingBox();
  expect(previewBox.y + previewBox.height).toBeLessThanOrEqual(768);

  const screenshotDir = path.join(
    process.env.USERPROFILE || process.cwd(), '.codex', 'visualizations',
    '2026', '10', '15', 'material-integrity-governance',
  );
  fs.mkdirSync(screenshotDir, {recursive: true});
  await page.screenshot({
    path: path.join(screenshotDir, 'dedup-plan-1366x768.png'),
    fullPage: false,
  });

  await previewDialog.getByRole('button', {name: '确认删除 4 条索引'}).click();
  expect(executionPayload).toEqual({confirmation_credential: 'browser-confirmation-credential'});
  await expect(page.locator('#toast')).toContainText('批量去重：处理中');
  await expect(page.locator('#toast')).toContainText('完成组 0/1');
  await expect.poll(() => polls, {timeout: 5_000}).toBeGreaterThan(1);
  await expect(page.locator('#toast')).toContainText('旧审计已失效');
});
