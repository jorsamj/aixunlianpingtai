import {mkdir} from 'node:fs/promises';
import {join} from 'node:path';
import {test, expect} from '@playwright/test';

const screenshotDir = join(process.cwd(), 'docs', 'screenshots', '2026-09-23-enterprise-lists');

test.beforeAll(async () => {
  await mkdir(screenshotDir, {recursive: true});
});

async function ready(page) {
  await page.addInitScript(() => localStorage.removeItem('cl_v427_advanced'));
  await page.setViewportSize({width: 1440, height: 900});
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady))).toBe(true);
}

function navItem(page, name) {
  return page.locator('#nav .nav-btn').filter({hasText: name});
}

test('advanced navigation hides entries without changing current page and service node stays unique', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(String(error)));
  await page.route('**/api/v63/service-nodes', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({items: [], supported_capabilities: []}),
  }));
  await ready(page);

  await expect(navItem(page, '训练资源')).toHaveCount(0);
  await expect(navItem(page, '服务节点')).toHaveCount(0);
  await page.locator('#nav .nav-advanced427 button').click();
  await expect(navItem(page, '训练资源')).toHaveCount(1);
  await expect(navItem(page, '服务节点')).toHaveCount(1);

  await navItem(page, '训练资源').click();
  await expect(page.locator('#title')).toHaveText('训练资源');
  await expect.poll(async () => page.evaluate(() => state.page)).toBe('训练资源');
  await page.locator('#nav .nav-advanced427 button').click();
  await expect(navItem(page, '训练资源')).toHaveCount(0);
  await expect(page.locator('#title')).toHaveText('训练资源');
  await expect(page.locator('#view')).not.toContainText('当前页面模块尚未就绪');
  await expect.poll(async () => page.evaluate(() => state.page)).toBe('训练资源');

  await page.locator('#nav .nav-advanced427 button').click();
  await expect(navItem(page, '训练资源')).toHaveClass(/active/);
  await navItem(page, '服务节点').click();
  await expect(page.locator('#title')).toHaveText('服务节点');
  await expect(navItem(page, '服务节点')).toHaveCount(1);
  await page.locator('#nav .nav-advanced427 button').click();
  await expect(navItem(page, '服务节点')).toHaveCount(0);
  await expect(page.locator('#title')).toHaveText('服务节点');
  await expect.poll(async () => page.evaluate(() => state.page)).toBe('服务节点');
  await page.locator('#nav .nav-advanced427 button').click();
  await expect(navItem(page, '服务节点')).toHaveCount(1);
  await expect(navItem(page, '服务节点')).toHaveClass(/active/);

  await navItem(page, '总览').click();
  await page.locator('#nav .nav-advanced427 button').click();
  await expect(navItem(page, '训练资源')).toHaveCount(0);
  await page.reload();
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect(navItem(page, '服务节点')).toHaveCount(0);
  await page.locator('#nav .nav-advanced427 button').click();
  await expect(navItem(page, '服务节点')).toHaveCount(1);
  expect(pageErrors).toEqual([]);
});

test('algorithm list uses real category ids with draft and applied selection', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(String(error)));
  await ready(page);
  await page.evaluate(() => window.setPage('算法列表'));
  await expect(page.locator('[data-algorithm-list-owner="AlgorithmListRuntime"]')).toBeVisible();

  await page.evaluate(() => {
    state.algorithms = [
      {id: 'local-vehicle', name: '本地车辆检测', industry: '交通', algorithm_type: 'yolo_ultralytics', versions: []},
      {id: 'external-car', name: '畅联机动车检测', industry: '交通', algorithm_type: 'yolo_ultralytics', source_type: 'EXTERNAL', provider_type: 'CHANG_LIAN', external_category_id: 'car', external_active: true, versions: [{id: 'v1', version_name: 'V1', map50: .926, created_at: '2026-09-23T08:00:00Z'}]},
      {id: 'external-fire', name: '畅联烟火检测', industry: '安全', algorithm_type: 'yolo_ultralytics', source_type: 'EXTERNAL', provider_type: 'CHANG_LIAN', external_category_id: 'fire', external_active: true, versions: []},
    ];
    state.jobs = [{id: 'job-ui-1', status: 'running', asset_algorithm_id: 'external-car'}];
    const categoryRows = [
      {id: 'vehicle', name: '车辆相关', parentId: '', path: '车辆相关', ancestorIds: [], hasChildren: true},
      {id: 'motor', name: '机动车识别检测', parentId: 'vehicle', path: '车辆相关 / 机动车识别检测', ancestorIds: ['vehicle'], hasChildren: true},
      {id: 'car', name: '机动车检测', parentId: 'motor', path: '车辆相关 / 机动车识别检测 / 机动车检测', ancestorIds: ['vehicle', 'motor'], hasChildren: false},
      {id: 'safety', name: '安全生产', parentId: '', path: '安全生产', ancestorIds: [], hasChildren: true},
      {id: 'fire', name: '烟火检测', parentId: 'safety', path: '安全生产 / 烟火检测', ancestorIds: ['safety'], hasChildren: false},
    ];
    window.AlgorithmListRuntime.setExternalProvider({
      snapshot: () => ({categories: categoryRows, categoryRows, externalMode: true}),
      meta: algorithm => ({external: algorithm.source_type === 'EXTERNAL', sourceLabel: algorithm.source_type === 'EXTERNAL' ? '新畅联' : '本平台', readiness: {ready: true, status: 'current', message: ''}}),
      matches: (algorithm, filters) => {
        const external = algorithm.source_type === 'EXTERNAL';
        if (filters.source === 'internal' && external) return false;
        if (filters.source === 'external' && !external) return false;
        if (!filters.selectedCategoryIds.length) return true;
        return Boolean(algorithm.external_category_id) && filters.selectedCategoryIds.includes(String(algorithm.external_category_id));
      },
    });
    window.AlgorithmListRuntime.render();
  });

  await expect(page.locator('#alg412List')).toContainText('本地车辆检测');
  await expect(page.locator('#alg412List')).toContainText('畅联机动车检测');
  await page.screenshot({path: join(screenshotDir, '01-algorithm-list.png'), fullPage: true});

  await page.locator('[data-category-picker-toggle]').click();
  await expect(page.locator('[data-category-popover]')).toBeVisible();
  await page.locator('[data-category-id="vehicle"] [data-category-drill]').click();
  await page.locator('[data-category-id="motor"] [data-category-drill]').click();
  await page.locator('[data-category-check="car"]').check();
  await expect(page.locator('#alg412List')).toContainText('本地车辆检测');
  await page.screenshot({path: join(screenshotDir, '02-algorithm-category-cascader.png'), fullPage: true});
  await page.locator('[data-category-confirm]').click();
  await expect(page.locator('#alg412List')).toContainText('畅联机动车检测');
  await expect(page.locator('#alg412List')).not.toContainText('本地车辆检测');
  await expect(page.locator('#alg412List')).not.toContainText('畅联烟火检测');
  expect(pageErrors).toEqual([]);
});

test('training list view state does not replace durable truth and create still reads hidden resources', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(String(error)));
  const jobs = [
    {id: 'run-1', task_name: '车辆夜间训练', asset_algorithm_name: '车辆检测', status: 'running', queue_priority: 20, progress_percent: 33, current_epoch: 10, total_epochs: 30, elapsed_seconds: 8590, eta_seconds: 15156, task_stage: 'training', started_at: '2026-09-23T08:20:00Z'},
    {id: 'queue-1', task_name: '行人检测训练', asset_algorithm_name: '行人检测', status: 'queued', queue_priority: 30, progress_percent: 0, resource_pool_label: 'GPU 自动', created_at: '2026-09-23T08:10:00Z'},
    {id: 'done-1', task_name: '车辆检测训练', asset_algorithm_name: '车辆检测', status: 'completed', queue_priority: 70, progress_percent: 100, current_epoch: 30, total_epochs: 30, elapsed_seconds: 11598, started_at: '2026-09-22T14:04:03Z'},
    {id: 'fail-1', task_name: '人脸识别训练', asset_algorithm_name: '人脸识别', status: 'failed', queue_priority: 20, progress_percent: 58, current_epoch: 18, total_epochs: 30, failure_stage: 'training_process', started_at: '2026-09-22T12:03:21Z'},
    {id: 'stop-1', task_name: '图像分割训练', asset_algorithm_name: '图像分割', status: 'stopped', queue_priority: 40, progress_percent: 76, started_at: '2026-09-21T11:20:36Z'},
  ];
  await page.route('**/api/projects/*/jobs', route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(jobs)}));
  await page.route('**/api/v62/training-devices', route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({options: [{id: 'cuda:0', label: 'GPU 0', available: true}], recommended: 'cuda:0'})}));
  await ready(page);
  await page.evaluate(input => {
    state.jobs = input;
    state.algorithms = [{id: 'algo-create-ui', name: '车辆检测', industry: '交通', algorithm_type: 'yolo_ultralytics', versions: []}];
    state.targets = [{id: 'target-ui', name: 'A800 训练资源', status: 'ready', framework: 'ultralytics', algorithms: [{key: 'yolo11', name: 'YOLO11'}], base_models: []}];
    window.setPage('训练任务');
    window.TrainingTaskVisibilityRuntime.render();
  }, jobs);

  await expect(page.locator('.training-task-page')).toBeVisible();
  await expect(page.locator('[data-training-create]')).toBeVisible();
  await expect(page.locator('[data-training-create]')).toBeEnabled();
  await expect(page.locator('[data-training-count="all"]')).toHaveText('5');
  await expect(page.locator('.train428-table tbody tr')).toHaveCount(5);
  const trainingLayout = await page.evaluate(() => {
    const wrap = document.querySelector('.training-table-surface .table-wrap');
    const create = document.querySelector('[data-training-create]');
    const rect = create?.getBoundingClientRect();
    return {
      tableFits: Boolean(wrap) && wrap.scrollWidth <= wrap.clientWidth + 1,
      createFits: Boolean(rect) && rect.left >= 0 && rect.right <= window.innerWidth,
    };
  });
  expect(trainingLayout.tableFits).toBe(true);
  expect(trainingLayout.createFits).toBe(true);
  await page.screenshot({path: join(screenshotDir, '03-training-task-list.png'), fullPage: true});

  await page.locator('[data-training-tab="running"]').click();
  await expect(page.locator('.train428-table tbody tr')).toHaveCount(1);
  await expect(page.locator('.train428-table tbody')).toContainText('车辆夜间训练');
  expect(await page.evaluate(() => state.jobs.length)).toBe(5);
  await page.screenshot({path: join(screenshotDir, '04-training-task-running.png'), fullPage: true});

  await expect(navItem(page, '训练资源')).toHaveCount(0);
  await page.evaluate(() => window.openTrainingCreateCanonical429('algo-create-ui'));
  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#tr429Target')).toContainText('A800 训练资源');
  await page.locator('#modal .modal-head .icon').click();
  expect(pageErrors).toEqual([]);
});
