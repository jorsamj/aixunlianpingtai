import {test, expect} from '@playwright/test';

const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR4nGP8z8DAwMDAxMDAwMAAAAwBAQDJ/pLvAAAAAElFTkSuQmCC',
  'base64',
);

async function createProject(request) {
  const response = await request.post('/api/projects', {
    data: {name: `远程清洗UI-${Date.now()}`, labels: []},
  });
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function uploadLocal(request, projectId) {
  const response = await request.post(`/api/projects/${projectId}/images`, {
    multipart: {
      dataset_id: 'default',
      files: {name: 'local-clean.png', mimeType: 'image/png', buffer: PNG},
    },
  });
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  return body.uploaded[0];
}

async function selectProject(page, projectId) {
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', projectId);
    await route.continue({url: url.toString()});
  });
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '数据集'}));
  });
}

async function waitForCleanRuntime(page) {
  await expect.poll(
    () => page.evaluate(() => ({
      ready: typeof window.createClean427 === 'function',
      uiReady: typeof state !== 'undefined' ? !!state.uiReady : false,
    })),
    {timeout: 20_000},
  ).toEqual({ready: true, uiReady: true});
}

test('cleaning execution picker disables Agent for local material and submits explicit Agent mode when available', async ({page, request}) => {
  const project = await createProject(request);
  const image = await uploadLocal(request, project.id);
  await selectProject(page, project.id);
  await page.goto('/');
  await waitForCleanRuntime(page);

  await page.evaluate(imageId => window.createClean427({image_ids: [imageId]}), image.id);
  let dialog = page.getByRole('dialog', {name: '创建自动清洗任务'});
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText('执行位置')).toBeVisible();
  await expect(dialog.locator('input[name="cl427Execution"][value="local"]')).toBeChecked();
  await expect(dialog.locator('input[name="cl427Execution"][value="agent"]')).toBeDisabled();
  await dialog.getByRole('button', {name: '取消'}).click();

  let submitted = null;
  await page.route(`**/api/v47/projects/${project.id}/clean-runtime/preflight`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        local_available: true,
        default_execution_mode: 'local',
        agent_available: true,
        reason: '',
        selected_count: 1,
        eligible_nodes: [
          {node_id: 'clean-agent-a', display_name: '清洗节点 A', build_id: 'build-a'},
          {node_id: 'clean-agent-b', display_name: '清洗节点 B', build_id: 'build-b'},
        ],
      }),
    });
  });
  await page.route(`**/api/v47/projects/${project.id}/clean-tasks`, async route => {
    if (route.request().method() === 'POST') {
      submitted = route.request().postDataJSON();
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          id: 'remote-clean-ui',
          status: 'queued',
          status_text: '排队中',
          execution_mode: 'agent',
        }),
      });
      return;
    }
    await route.continue();
  });

  await page.evaluate(imageId => window.createClean427({image_ids: [imageId]}), image.id);
  dialog = page.getByRole('dialog', {name: '创建自动清洗任务'});
  await expect(dialog.locator('input[name="cl427Execution"][value="agent"]')).toBeEnabled();
  await expect(dialog.getByText('已检测到 2 个可用节点')).toBeVisible();
  await dialog.locator('input[name="cl427Execution"][value="agent"]').check();
  await dialog.getByRole('button', {name: '开始清洗'}).click();

  await expect.poll(() => submitted).not.toBeNull();
  expect(submitted.execution_mode).toBe('agent');
  expect(submitted.image_ids).toEqual([image.id]);
});
