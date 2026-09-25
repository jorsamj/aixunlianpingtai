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
        idle_nodes: 1,
        busy_nodes: 1,
        eligible_nodes: [
          {
            node_id: 'clean-agent-a', display_name: '清洗节点 A', build_id: 'build-a',
            idle: true, active_count: 0, active_tasks: [], preemptible: false,
            resources: {cpu: {logical_cores: 16}, memory: {available_bytes: 17179869184}, disk: {}},
          },
          {
            node_id: 'clean-agent-b', display_name: '清洗节点 B', build_id: 'build-b',
            idle: false, active_count: 1, preemptible: true,
            active_tasks: [{task_id:'train-1',kind:'TRAINING',status:'RUNNING',stage:'training',progress:42,preemptible:true}],
            resources: {cpu: {logical_cores: 32}, memory: {available_bytes: 34359738368}, disk: {}},
          },
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
  await expect(dialog.locator('#cl427SchedulingSection')).toBeVisible();
  await expect(dialog.getByText('当前空闲')).toBeVisible();
  await dialog.locator('input[name="cl427SchedulingMode"][value="node"]').check();
  await dialog.locator('input[name="cl427Node"][value="clean-agent-b"]').check();
  await expect(dialog.getByText('训练 42%')).toBeVisible();
  await dialog.locator('input[name="cl427QueuePolicy"][value="preempt"]').check();
  await dialog.getByRole('button', {name: '开始清洗'}).click();

  await expect.poll(() => submitted).not.toBeNull();
  expect(submitted.execution_mode).toBe('agent');
  expect(submitted.scheduling_mode).toBe('node');
  expect(submitted.target_node_id).toBe('clean-agent-b');
  expect(submitted.queue_policy).toBe('preempt');
  expect(submitted.image_ids).toEqual([image.id]);
});


test('cleaning range switches preflight and submission by formal annotation_state', async ({page, request}) => {
  const project = await createProject(request);
  await selectProject(page, project.id);

  const preflights = [];
  let submitted = null;
  await page.route(`**/api/v47/projects/${project.id}/clean-runtime/preflight`, async route => {
    preflights.push(route.request().postDataJSON());
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        local_available: true,
        default_execution_mode: 'local',
        agent_available: false,
        reason: '测试仅使用中央 Worker',
        selected_count: 0,
        eligible_nodes: [],
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
          id: 'scope-clean-ui',
          status: 'queued',
          status_text: '排队中',
          execution_mode: 'local',
          clean_scope: 'annotated',
        }),
      });
      return;
    }
    await route.continue();
  });

  await page.goto('/');
  await waitForCleanRuntime(page);
  await page.evaluate(() => window.createClean427());

  const dialog = page.getByRole('dialog', {name: '创建自动清洗任务'});
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('input[name="cl427Scope"][value="all"]')).toBeChecked();
  await expect(dialog.locator('input[name="cl427Scope"][value="annotated"]')).toBeEnabled();
  await expect(dialog.locator('input[name="cl427Scope"][value="unannotated"]')).toBeEnabled();
  await expect(dialog.locator('input[name="cl427Scope"][value="confirmed_empty"]')).toBeEnabled();
  await expect(dialog.locator('input[name="cl427Scope"][value="selected"]')).toBeDisabled();
  await expect(dialog.locator('#cl427AnnotationAuditSection')).toBeVisible();
  await expect(dialog.locator('#cl427AnnotationAudit')).toBeChecked();

  await dialog.locator('input[name="cl427Scope"][value="unannotated"]').check();
  await expect(dialog.locator('#cl427AnnotationAuditSection')).toBeHidden();
  await expect.poll(() => preflights.at(-1)?.clean_scope).toBe('unannotated');

  await dialog.locator('input[name="cl427Scope"][value="annotated"]').check();
  await expect.poll(() => preflights.at(-1)?.clean_scope).toBe('annotated');
  expect(preflights.at(-1)?.image_ids).toEqual([]);
  await expect(dialog.getByRole('button', {name: '开始清洗'})).toBeEnabled();
  await dialog.getByRole('button', {name: '开始清洗'}).click();

  await expect.poll(() => submitted).not.toBeNull();
  expect(submitted.clean_scope).toBe('annotated');
  expect(submitted.image_ids).toEqual([]);
  expect(submitted.execution_mode).toBe('local');
  expect(submitted.annotation_audit).toBe(true);
});


test('cleaning progress refresh preserves task row and progress bar nodes', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  let current = {
    id:'clean-perf-1',
    name:'清洗性能任务',
    status:'running',
    status_text:'清洗中',
    progress:12,
    processed_images:12,
    total_images:100,
    flagged_images:2,
    execution_mode:'local',
    phase:'analyzing',
    current_item:'image-12',
    created_at:'2026-09-22T00:00:00Z',
  };

  await page.route('**/api/v47/projects/*/clean-tasks', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status:200,
      contentType:'application/json',
      body:JSON.stringify({items:[current]}),
    });
  });

  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state.uiReady)), {timeout:15_000}).toBe(true);
  await page.evaluate(async () => {
    state.v427OpsTab = 'clean';
    window.setPage('自动标注及清洗');
    await window.renderOps427();
  });

  const row = page.locator('#clean427TaskRows [data-task-id="clean-perf-1"]');
  await expect(row).toBeVisible();
  await expect(row).toContainText('12.0%');
  await page.evaluate(() => {
    window.__stableCleanRow = document.querySelector('#clean427TaskRows [data-task-id="clean-perf-1"]');
    window.__stableCleanProgress = window.__stableCleanRow?.querySelector('.opprog427 i') || null;
  });

  current = {
    ...current,
    progress:57,
    processed_images:57,
    flagged_images:9,
    current_item:'image-57',
  };
  await page.evaluate(() => window.refreshCleanOps427Delta());

  await expect(row).toContainText('57.0%');
  await expect(row).toContainText('9');
  await expect(row.locator('.opprog427 i')).toHaveAttribute('data-progress', '57.00');
  expect(await page.evaluate(() => ({
    row: window.__stableCleanRow === document.querySelector('#clean427TaskRows [data-task-id="clean-perf-1"]'),
    progress: window.__stableCleanProgress === document.querySelector('#clean427TaskRows [data-task-id="clean-perf-1"] .opprog427 i'),
  }))).toEqual({row:true, progress:true});
  expect(pageErrors).toEqual([]);
});


test('cleaning detail progress stays in-place and hands off to review without raw modal polling', async ({page, request}) => {
  const project = await createProject(request);
  await selectProject(page, project.id);

  let current = {
    id:'clean-modal-1',
    name:'清洗详情轮询',
    status:'running',
    status_text:'清洗中',
    progress:12,
    processed_images:12,
    total_images:100,
    flagged_images:2,
    execution_mode:'local',
    phase:'analyzing',
    current_item:'image-12',
    created_at:'2026-09-23T00:00:00Z',
  };

  await page.route(`**/api/v47/projects/${project.id}/clean-tasks`, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status:200,
      contentType:'application/json',
      body:JSON.stringify({items:[current]}),
    });
  });

  await page.route(`**/api/v47/projects/${project.id}/clean-tasks/clean-modal-1/result`, async route => {
    await route.fulfill({
      status:200,
      contentType:'application/json',
      body:JSON.stringify({
        task:{...current,status:'awaiting_confirmation',status_text:'待确认'},
        result:{
          items:Array.from({length:65},(_,index)=>({
            image_id:`clean-image-${index+1}`,
            filename:`clean-image-${index+1}.jpg`,
            url:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR4nGP8z8DAwMDAxMDAwMAAAAwBAQDJ/pLvAAAAAElFTkSuQmCC',
            annotation_state:index%2===0?'annotated':'unannotated',
            annotation_provenance:index%2===0?'manual':'unannotated',
            status:index===64?'failed':'done',
            item_state:index===64?'failed':'completed',
            suggest_delete:index%3===0,
            issues:index===64?[]:[index%2===0
              ?{code:'exact_duplicate',name:'重复图',detail:'与另一张图片完全相同',related_image_id:'clean-image-1'}
              :{code:'blur',name:'疑似模糊',detail:'清晰度偏低'}],
          })),
          rules:{},
          annotation_audit:{
            enabled:true,
            audited_images:1,
            review_images:1,
            warning_count:2,
            state_counts:{annotated:1,unannotated:0,confirmed_empty:0},
            provenance_counts:{manual:1},
            issue_counts:{box_tiny:1,box_duplicate_exact:1},
            class_balance:[{label:'smoke',count:2,share:1}],
            heatmap:{grid:5,cells:[2,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0]},
            items:[{
              image_id:'ann-1',
              filename:'annotated.jpg',
              url:'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFElEQVR4nGP8z8DAwMDAxMDAwMAAAAwBAQDJ/pLvAAAAAElFTkSuQmCC',
              annotation_state:'annotated',
              annotation_provenance:'manual',
              box_count:2,
              labels:['smoke'],
              issues:[
                {code:'box_tiny',name:'疑似极小框',detail:'面积占比过小'},
                {code:'box_duplicate_exact',name:'完全重复框',detail:'两个框完全重复'},
              ],
            }],
            next_cursor:null,
          },
        },
      }),
    });
  });

  await page.goto('/');
  await waitForCleanRuntime(page);
  await page.evaluate(() => {
    state.v427OpsTab = 'clean';
    window.setPage('自动标注及清洗');
  });

  await page.evaluate(() => window.showTaskProgress427('clean','clean-modal-1'));
  const dialog = page.getByRole('dialog',{name:'自动清洗'});
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('[data-clean-progress-percent]')).toHaveText('12.0%');
  await page.evaluate(() => {
    window.__stableCleanModalProgress = document.querySelector('[data-clean-progress-task="clean-modal-1"]');
    window.__stableCleanModalBar = window.__stableCleanModalProgress?.querySelector('[data-clean-progress-bar]') || null;
  });
  await expect.poll(async () => page.evaluate(() =>
    window.PollRegistryRuntime?.snapshot?.().some(entry => entry.key === 'clean-task-progress:clean-modal-1') || false
  )).toBe(true);

  current = {
    ...current,
    progress:57,
    processed_images:57,
    flagged_images:9,
    current_item:'image-57',
  };

  await expect(dialog.locator('[data-clean-progress-percent]')).toHaveText('57.0%',{timeout:5000});
  await expect(dialog.locator('[data-clean-progress-counts]')).toHaveText('57/100');
  await expect(dialog.locator('[data-clean-progress-flagged]')).toHaveText('9');
  expect(await page.evaluate(() => ({
    root: window.__stableCleanModalProgress === document.querySelector('[data-clean-progress-task="clean-modal-1"]'),
    bar: window.__stableCleanModalBar === document.querySelector('[data-clean-progress-task="clean-modal-1"] [data-clean-progress-bar]'),
  }))).toEqual({root:true,bar:true});

  current = {
    ...current,
    status:'awaiting_confirmation',
    status_text:'待确认',
    progress:100,
    processed_images:100,
  };

  const review = page.getByRole('dialog',{name:'清洗任务详情'});
  await expect(review).toBeVisible({timeout:5000});
  await expect(review.getByRole('button',{name:'确认清洗结果'})).toBeVisible();
  const imagePanel = review.locator('[data-clean-quality-panel="image"]');
  const imageCards = imagePanel.locator('#cleanImageReviewItems429 .review427-card');
  await expect(imageCards).toHaveCount(60);
  await expect(imagePanel.locator('#cleanImageReviewCount429')).toHaveText('显示 60 / 65 · 全部 65');
  await imagePanel.getByRole('button',{name:/加载更多 5 张/}).click();
  await expect(imageCards).toHaveCount(65);
  await imagePanel.getByRole('button',{name:/扫描失败/}).click();
  await expect(imageCards).toHaveCount(1);
  await expect(imagePanel.locator('#cleanImageReviewCount429')).toHaveText('显示 1 / 1 · 全部 65');
  await imagePanel.getByRole('button',{name:/全部 65/}).click();
  await imagePanel.locator('#cleanImageReviewIssue429').selectOption('exact_duplicate');
  await expect(imageCards).toHaveCount(32);
  await expect(imagePanel.locator('#cleanImageReviewCount429')).toHaveText('显示 32 / 32 · 全部 65');
  await expect(review.getByRole('button',{name:/标注质量/})).toBeVisible();
  await review.getByRole('button',{name:/标注质量/}).click();
  const annotationPanel = review.locator('[data-clean-quality-panel="annotation"]');
  await expect(annotationPanel.getByText('正式已标注')).toBeVisible();
  await expect(annotationPanel.locator('.clean429-audit-tags').getByText('人工标注')).toBeVisible();
  await expect(annotationPanel.getByText('Class Balance')).toBeVisible();
  await expect(annotationPanel.locator('.clean429-audit-bars').getByText('smoke')).toBeVisible();
  await expect(annotationPanel.locator('.clean429-audit-issues').getByText('疑似极小框')).toBeVisible();
  await expect(annotationPanel.locator('.clean429-audit-issues').getByText('完全重复框')).toBeVisible();
  await expect(annotationPanel.getByText('不会在此处自动删除、移动或改写 Ground Truth。')).toBeVisible();
  await expect.poll(async () => page.evaluate(() =>
    window.PollRegistryRuntime?.snapshot?.().some(entry => entry.key === 'clean-task-progress:clean-modal-1') || false
  )).toBe(false);
});
