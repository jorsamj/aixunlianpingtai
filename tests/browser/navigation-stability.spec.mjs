import {test, expect} from '@playwright/test';

async function mockDurableZipUpload(page, {
  jobId,
  fileName = 'browser.zip',
  report = {imported_images: 1, annotated_images: 0, boxes: 0, warnings: []},
}) {
  const uploadId = `upload-${jobId}`;
  let uploaded = false;
  let started = false;
  const selecting = {
    id: jobId,
    file_name: fileName,
    status: 'selecting',
    stage: '上传与校验完成',
    message: '等待启动后台导入',
    progress: 0,
    image_count: Number(report.imported_images || 0),
    file_count: Number(report.imported_images || 0),
    uncompressed_size_mb: 1,
    format_hints: ['YOLO'],
  };
  const running = {...selecting, status: 'running', stage: '后台导入中', progress: 65};
  const done = {...running, status: 'done', stage: '导入完成', message: '完成', progress: 100, report};

  await page.route(/\/api\/v19\/projects\/[^/]+\/datasets\/default\/import\/uploads$/, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        upload_id: uploadId,
        part_size: 8 * 1024 * 1024,
        completed_parts: [],
        total_parts: 1,
        upload_progress: 0,
      }),
    });
  });
  await page.route(new RegExp(`/api/v19/projects/[^/]+/import/uploads/${uploadId}/parts/\\d+$`), async route => {
    if (route.request().method() !== 'PUT') return route.continue();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });
  await page.route(new RegExp(`/api/v19/projects/[^/]+/import/uploads/${uploadId}/complete$`), async route => {
    if (route.request().method() !== 'POST') return route.continue();
    uploaded = true;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(selecting)});
  });
  await page.route(new RegExp(`/api/v19/projects/[^/]+/import/jobs/${jobId}/start$`), async route => {
    if (route.request().method() !== 'POST') return route.continue();
    started = true;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(running)});
  });
  await page.route(new RegExp(`/api/v19/projects/[^/]+/import/jobs/${jobId}$`), async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(started ? done : selecting)});
  });
  await page.route(/\/api\/v19\/projects\/[^/]+\/import\/jobs$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    const items = !uploaded ? [] : [started ? done : selecting];
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, items})});
  });
}


test('delayed request from previous page cannot jump back over the current page', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.getByRole('button', {name: /训练任务/})).toBeVisible({timeout: 15_000});
  await expect(page.getByRole('button', {name: /数据集/})).toBeVisible();

  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let interceptedResolve;
  const intercepted = new Promise(resolve => { interceptedResolve = resolve; });
  let shouldDelay = true;

  await page.route('**/api/**', async route => {
    const request = route.request();
    if (shouldDelay && request.method() === 'GET') {
      shouldDelay = false;
      interceptedResolve(request.url());
      await gate;
      try {
        await route.continue();
      } catch (_) {
        // Expected when PageRequestScope aborts the old page request.
      }
      return;
    }
    await route.continue();
  });

  await page.getByRole('button', {name: /训练任务/}).click();
  const delayedUrl = await Promise.race([
    intercepted,
    new Promise((_, reject) => setTimeout(() => reject(new Error('训练任务页面没有发出可延迟的 GET 请求')), 8_000)),
  ]);
  expect(delayedUrl).toContain('/api/');

  await expect.poll(async () => page.evaluate(() => (
    window.PollRegistryRuntime?.snapshot?.().some(item => item.key === 'training-jobs') || false
  ))).toBe(false);

  await page.getByRole('button', {name: /数据集/}).click();
  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.getByRole('button', {name: /数据集/})).toHaveClass(/active/);
  await expect.poll(async () => page.evaluate(() => (
    window.PollRegistryRuntime?.snapshot?.().some(item => item.key === 'training-jobs') || false
  ))).toBe(false);

  release();
  await page.waitForTimeout(1_500);

  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.getByRole('button', {name: /数据集/})).toHaveClass(/active/);
  expect(pageErrors).toEqual([]);
});

test('final v42.4 video polling patches rows with a PollRegistry-managed one-shot and stops on leave', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  let requests = 0;

  await page.route(/\/api\/v33\/projects\/[^/]+\/video-tasks(?:\?.*)?$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    requests += 1;
    const progress = Math.min(90, requests * 20);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 'video-browser-1',
        video_name: 'browser-video.mp4',
        status: 'RUNNING',
        mode: 'interval_seconds',
        interval_seconds: 1,
        progress,
        current_item: `frame-${requests}`,
        result: {extracted_frames: requests * 3},
        split: 'train',
        created_at: '2026-09-11T00:00:00Z',
        updated_at: `2026-09-11T00:00:0${Math.min(requests, 9)}Z`,
      }]})
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.setPage('视频切帧'));
  await expect(page.locator('#title')).toContainText('视频切帧');
  await expect(page.locator('#video424Rows')).toBeVisible({timeout: 10_000});

  await page.evaluate(() => {
    window.__videoStableRoot = document.getElementById('view');
  });

  await expect.poll(async () => page.evaluate(() => {
    const row = window.PollRegistryRuntime?.snapshot?.().find(item => item.key === 'video-frames');
    return row ? {managed: row.managed, owners: row.owners, delay: row.delay} : null;
  })).toEqual({managed: true, owners: ['视频切帧'], delay: 2000});

  await expect.poll(() => requests, {timeout: 8_000}).toBeGreaterThanOrEqual(2);
  await expect(page.locator('#video424Rows')).toContainText('frame-2');
  expect(await page.evaluate(() => window.__videoStableRoot === document.getElementById('view'))).toBe(true);
  expect(await page.evaluate(() => window.__videoFramePollTimer ?? null)).toBeNull();

  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await expect.poll(async () => page.evaluate(() => (
    window.PollRegistryRuntime?.snapshot?.().some(item => item.key === 'video-frames') || false
  ))).toBe(false);

  expect(pageErrors).toEqual([]);
});

test('source polling is PollRegistry-managed after initial page render and stops on leave', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.setPage('素材接入'));
  await expect(page.locator('#title')).toContainText('素材接入');
  await expect(page.locator('#source422Rows')).toBeVisible({timeout: 10_000});

  await expect.poll(async () => page.evaluate(() => {
    const row = window.PollRegistryRuntime?.snapshot?.().find(item => item.key === 'sources');
    return row ? {managed: row.managed, owners: row.owners, delay: row.delay} : null;
  })).toEqual({managed: true, owners: ['素材接入'], delay: 2500});

  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await expect.poll(async () => page.evaluate(() => (
    window.PollRegistryRuntime?.snapshot?.().some(item => item.key === 'sources') || false
  ))).toBe(false);

  expect(pageErrors).toEqual([]);
});

test('final navigation owner closes the mobile sidebar and backdrop', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.toggleMobileSidebarV37?.(true));
  await expect(page.locator('#sidebar')).toHaveClass(/mobile-open/);
  await expect(page.locator('#sideBackdrop')).toHaveClass(/show/);

  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.locator('#sidebar')).not.toHaveClass(/mobile-open/);
  await expect(page.locator('#sideBackdrop')).not.toHaveClass(/show/);

  expect(pageErrors).toEqual([]);
});

test('final navigation persists the selected page and restores it after reload', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await expect.poll(async () => page.evaluate(() => {
    try {
      return JSON.parse(localStorage.getItem('mc_train_ui_state_v34') || '{}').page || '';
    } catch (_) {
      return '';
    }
  })).toBe('数据集');

  await page.reload();
  await expect(page.locator('#title')).toContainText('数据集', {timeout: 15_000});
  expect(pageErrors).toEqual([]);
});

test('service node owner commits its own shell without flashing another business page', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  await page.route('**/api/v63/service-nodes', async route => {
    await new Promise(resolve => setTimeout(resolve, 350));
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: [], supported_capabilities: []})});
  });

  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => window.ServiceNodeRuntime?.build || null)).toBe('service-node-runtime-422539');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);

  const openService = async () => page.evaluate(async () => {
    window.setPage('服务节点');
    await Promise.resolve();
    await Promise.resolve();
    const view = document.getElementById('view');
    return {
      page: state.page,
      title: document.getElementById('title')?.textContent,
      serviceShell: Boolean(view?.querySelector('[data-service-node-page]')),
      wrongBusinessPage: Boolean(view?.querySelector('.alg428-card,.train428-page,.data426-page,.storage61-shell')),
    };
  });

  await expect(openService()).resolves.toEqual({
    page: '服务节点', title: '服务节点', serviceShell: true, wrongBusinessPage: false,
  });
  await expect(page.locator('[data-service-node-page]')).toBeVisible();

  await page.evaluate(() => window.setPage('训练任务'));
  await expect(page.locator('#title')).toHaveText('训练任务');
  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toHaveText('数据集');

  await expect(openService()).resolves.toEqual({
    page: '服务节点', title: '服务节点', serviceShell: true, wrongBusinessPage: false,
  });
  expect(pageErrors).toEqual([]);
});

test('legacy auto-label route alias resolves to 自动标注及清洗 through final navigation', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.setPage('自动标注'));
  await expect(page.locator('#title')).toContainText('自动标注及清洗');
  await expect.poll(async () => page.evaluate(() => {
    try {
      return JSON.parse(localStorage.getItem('mc_train_ui_state_v34') || '{}').page || '';
    } catch (_) {
      return '';
    }
  })).toBe('自动标注及清洗');

  expect(pageErrors).toEqual([]);
});

test('historical persisted 自动标注 page is restored as canonical 自动标注及清洗', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '自动标注'}));
  });

  await page.goto('/');
  await expect(page.locator('#title')).toContainText('自动标注及清洗', {timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => {
    try {
      return JSON.parse(localStorage.getItem('mc_train_ui_state_v34') || '{}').page || '';
    } catch (_) {
      return '';
    }
  })).toBe('自动标注及清洗');

  expect(pageErrors).toEqual([]);
});

test('storage configuration route is rendered by the final storage owner', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.setPage('存储配置'));
  await expect(page.locator('#title')).toContainText('存储配置');
  await expect(page.locator('.storage61-shell')).toBeVisible({timeout: 10_000});
  await expect(page.locator('#storage61Rows')).toBeVisible();

  expect(pageErrors).toEqual([]);
});

test('formal version marker stays stable across final render owners and delayed legacy timers', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  const expectFormalVersion = async () => {
    await expect(page.locator('#versionBadge')).toHaveText('v42.24.0');
    await expect(page.locator('.nav-footer b')).toHaveText('v42.24.0');
  };

  await expectFormalVersion();
  await page.waitForTimeout(1_800);
  await expectFormalVersion();

  for (const route of ['算法列表', '数据集', '训练任务', '自动标注及清洗', '质量中心', '视频切帧', '标签管理', '模型配置', '存储配置']) {
    await page.evaluate(next => window.setPage(next), route);
    await expect(page.locator('#title')).toContainText(route);
    await expectFormalVersion();
  }

  await page.waitForTimeout(1_800);
  await expectFormalVersion();
  expect(pageErrors).toEqual([]);
});

test('quality-center detection keeps multi-image and folder pickers after page render ownership', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(async () => {
    window.setPage('质量中心');
    await window.setQualityCenterTab411?.('detect');
  });
  await expect(page.locator('#title')).toContainText('质量中心');
  await expect(page.locator('#benchFiles64')).toHaveAttribute('multiple', '');
  await expect(page.locator('#benchFolder64')).toHaveAttribute('webkitdirectory', '');
  await expect(page.getByRole('button', {name: '选择图片'})).toBeVisible();
  await expect(page.getByRole('button', {name: '选择文件夹'})).toBeVisible();

  expect(pageErrors).toEqual([]);
});

test('retired testing routes resolve to quality center and normal navigation exposes only three product groups', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => {
    state.v427Advanced = false;
    window.renderNav?.();
    window.setPage('检测台');
  });
  await expect(page.locator('#title')).toHaveText('质量中心');
  await expect(page.locator('.nav-group-title')).toHaveText(['总览','算法生成','数据中心']);
  await expect(page.locator('#nav')).not.toContainText('测试评测');
  await expect(page.locator('#nav')).not.toContainText('部署中心');
  await expect(page.locator('#nav')).not.toContainText('测试发布');

  await page.evaluate(() => window.setPage('测试发布'));
  await expect(page.locator('#title')).toHaveText('质量中心');
  expect(pageErrors).toEqual([]);
});

test('modal file input beautification survives modal lifecycle ownership', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.modal(
    '文件选择器生命周期测试',
    '<div class="form"><div class="field"><label>选择文件</label><input id="modalProbeFile" type="file" class="file" accept=".zip"></div></div>',
    true,
  ));

  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalProbeFile')).toHaveClass(/native-file426/);
  await expect(page.locator('#modalProbeFile + .filepicker426')).toBeVisible();
  await expect(page.locator('#modalProbeFile + .filepicker426 .filepicker426-btn')).toContainText('选择本地文件');
  await expect(page.locator('#modalProbeFile + .filepicker426 .filepicker426-name')).toContainText('未选择');

  expect(pageErrors).toEqual([]);
});

test('modal table wrapping and first-field focus survive normalization ownership', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.modal(
    '后处理生命周期测试',
    '<div class="form"><table id="normalizationProbeTable" class="table"><tbody><tr><td>probe</td></tr></tbody></table><input id="normalizationProbeInput" class="input"><input id="normalizationProbeSecond" class="input"></div>',
    true,
  ));

  await expect(page.locator('#normalizationProbeTable')).toBeVisible();
  await expect(page.locator('#normalizationProbeTable').locator('xpath=..')).toHaveClass(/table-wrap/);
  await expect(page.locator('#normalizationProbeInput')).toBeFocused();

  expect(pageErrors).toEqual([]);
});

test('ZIP import completion surfaces review action and auto-opens review', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await mockDurableZipUpload(page, {
    jobId: 'zip-browser-1',
    fileName: 'browser.zip',
    report: {imported_images: 3, annotated_images: 2, boxes: 5, warnings: []},
  });
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => {
    window.__zipReviewOpened = null;
    window.showImportReview412 = jobId => { window.__zipReviewOpened = jobId; };
  });

  await page.evaluate(async () => { await window.openDataUpload426(); });
  await expect(page.locator('#up426Zip')).toBeAttached();
  await page.locator('#up426Zip').setInputFiles({
    name: 'browser.zip',
    mimeType: 'application/zip',
    buffer: Buffer.from('browser-zip-probe'),
  });

  await expect.poll(async () => page.evaluate(() => state.import411?.stage || ''), {timeout: 10_000}).toBe('导入完成');
  await expect.poll(async () => page.evaluate(() => ({
    bound: Boolean(state.import411?.__reviewBound),
    opened: window.__zipReviewOpened,
    hasButton: Boolean(document.querySelector('.review412-btn')),
    persistedButton: String(state.import411?.resultHtml || '').includes('review412-btn'),
  })), {timeout: 10_000}).toEqual({
    bound: true,
    opened: 'zip-browser-1',
    hasButton: true,
    persistedButton: true,
  });

  expect(pageErrors).toEqual([]);
});


test('ZIP import completion uses scoped label and material refresh', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await mockDurableZipUpload(page, {
    jobId: 'zip-r20g-scoped',
    fileName: 'r20g.zip',
    report: {imported_images: 2, annotated_images: 1, boxes: 2, warnings: []},
  });
  await page.route(/\/api\/v12\/projects\/[^/]+\/labels$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: [
      {class_id: 0, code: 'smoke', display_name: '烟雾', color: '#64748b'},
    ]})});
  });
  await page.route(/\/api\/v61\/projects\/[^/]+\/materials(?:\?.*)?$/, async route => {
    const url = new URL(route.request().url());
    const limit = Number(url.searchParams.get('limit') || 48);
    const status = url.searchParams.get('processing_status');
    const total = status === 'unprocessed' ? 0 : 2;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      items: limit === 1 ? [] : [{
        id: 'zip-r20g-material', filename: 'zip-r20g.jpg',
        url: 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==',
        width: 640, height: 480, processing_status: 'processed', annotated: true,
        box_count: 1, labels: ['smoke'], annotation_preview: [], storage_type: 'local', storage_source_id: 'default_local',
      }],
      total, next_cursor: null,
    })});
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady))).toBe(true);
  await page.evaluate(() => {
    state.data412Tab = 'processed';
    state.materialQuery61 = '';
    state.materialAnnotated61 = 'all';
    state.materialSourceFilter61 = 'all';
    window.setPage('数据集');
  });
  await expect(page.locator('#title')).toContainText('数据集');
  await expect(page.locator('.data426-shell')).toBeVisible({timeout: 10_000});
  await page.waitForTimeout(1_500);

  const requests = [];
  const onRequest = request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  };
  page.on('request', onRequest);
  await page.evaluate(() => {
    window.__zipReviewOpenedR20g = null;
    window.showImportReview412 = jobId => { window.__zipReviewOpenedR20g = jobId; };
  });
  await page.evaluate(async () => { await window.openDataUpload426(); });
  await page.locator('#up426Zip').setInputFiles({
    name: 'r20g.zip', mimeType: 'application/zip', buffer: Buffer.from('r20g-zip-probe'),
  });
  await expect.poll(async () => page.evaluate(() => state.import411?.stage || ''), {timeout: 10_000}).toBe('导入完成');
  await expect.poll(async () => page.evaluate(() => window.__zipReviewOpenedR20g)).toBe('zip-r20g-scoped');
  await expect(page.locator('#data412Grid')).toContainText('zip-r20g.jpg', {timeout: 10_000});
  page.off('request', onRequest);

  const owned = requests.filter(row => !row.includes('/api/v19/projects/') || !row.endsWith('/import/jobs'));
  expect(owned.some(row => row === 'GET ' + row.slice(4) && row.includes('/api/v12/projects/') && row.endsWith('/labels'))).toBe(true);
  expect(owned.some(row => row.startsWith('GET /api/v61/projects/') && row.includes('/materials'))).toBe(true);

  const forbidden = owned.filter(row => (
    row === 'GET /api/projects'
    || /^GET \/api\/projects\/[^/?]+$/.test(row)
    || /\/datasets(?:\?|$)/.test(row)
    || /\/algorithms(?:\?|$)/.test(row)
    || /\/publish\/pending(?:\?|$)/.test(row)
    || /\/test_models(?:\?|$)/.test(row)
    || row.startsWith('GET /api/training_options')
    || row.startsWith('GET /api/v16/inference_envs')
    || row.startsWith('GET /api/system/recommendation')
    || row.startsWith('GET /api/local_models')
    || row.startsWith('GET /api/v35/model-configs')
    || row.startsWith('GET /api/v35/prompt-templates')
    || row.includes('/bootstrap/snapshot')
  ));
  expect(forbidden).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('server storage import confirmation avoids broad related refresh', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  const requests = [];

  await page.route(/\/api\/v61\/projects\/[^/]+\/storage-imports\/storage-r20g\/confirm$/, async route => {
    requests.push(`POST ${new URL(route.request().url()).pathname}`);
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      task_id: 'storage-r20g', status: 'RUNNING', stage: 'IMPORTING', result: {},
    })});
  });
  await page.route(/\/api\/v62\/projects\/[^/]+\/tasks\/storage-r20g$/, async route => {
    requests.push(`GET ${new URL(route.request().url()).pathname}`);
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      task_id: 'storage-r20g', status: 'SUCCEEDED', persisted_status: 'SUCCEEDED',
      phase: 'DONE', progress_percent: 100, result: {imported: 3, indexed: 3},
    })});
  });
  await page.route(/\/api\/v12\/projects\/[^/]+\/labels$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    requests.push(`GET ${new URL(route.request().url()).pathname}`);
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: [
      {class_id: 0, code: 'smoke', display_name: '烟雾', color: '#64748b'},
    ]})});
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady))).toBe(true);
  await page.evaluate(() => window.setPage('存储配置'));
  await expect(page.locator('#title')).toContainText('存储配置');
  await page.evaluate(async () => { await window.openStorageImport61(); });
  await expect(page.locator('#si61ImportShell')).toBeVisible();
  await page.evaluate(() => {
    const status = document.getElementById('si61Status');
    status.innerHTML = '<div data-import-class="smoke"><input data-label-code value="smoke"></div><button id="si61Confirm">确认建立索引</button>';
  });

  const broad = [];
  const onRequest = request => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith('/api/')) return;
    const row = `${request.method()} ${url.pathname}${url.search}`;
    if (
      row === 'GET /api/projects'
      || /^GET \/api\/projects\/[^/?]+$/.test(row)
      || /\/datasets(?:\?|$)/.test(row)
      || /\/algorithms(?:\?|$)/.test(row)
      || /\/publish\/pending(?:\?|$)/.test(row)
      || /\/test_models(?:\?|$)/.test(row)
      || row.startsWith('GET /api/training_options')
      || row.startsWith('GET /api/v16/inference_envs')
      || row.startsWith('GET /api/system/recommendation')
      || row.startsWith('GET /api/local_models')
      || row.startsWith('GET /api/v35/model-configs')
      || row.startsWith('GET /api/v35/prompt-templates')
      || row.includes('/bootstrap/snapshot')
      || row.startsWith('GET /api/v61/projects/') && row.includes('/materials')
    ) broad.push(row);
  };
  page.on('request', onRequest);
  await page.evaluate(async () => { await window.confirmStorageImport61('storage-r20g'); });
  await expect(page.locator('#toast')).toContainText('素材索引已建立：3 条');
  page.off('request', onRequest);

  expect(requests.filter(row => row.includes('storage-r20g'))).toEqual([
    expect.stringMatching(/^POST \/api\/v61\/projects\/[^/]+\/storage-imports\/storage-r20g\/confirm$/),
    expect.stringMatching(/^GET \/api\/v62\/projects\/[^/]+\/tasks\/storage-r20g$/),
  ]);
  expect(requests.some(row => row.startsWith('GET /api/v12/projects/') && row.endsWith('/labels'))).toBe(false);
  expect(broad).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('base modal open and manual refresh both fetch fresh import jobs', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  let listCalls = 0;
  let phase = 'startup';

  const job = (id, fileName) => ({
    id,
    file_name: fileName,
    status: 'done',
    stage: '导入完成',
    message: '完成',
    image_count: 2,
    report: {imported_images: 2, annotated_images: 1, boxes: 3, warnings: []},
  });

  await page.route(/\/api\/v19\/projects\/[^/]+\/import\/jobs$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    listCalls += 1;
    const items = phase === 'open'
      ? [job('modal-open-job', 'modal-open.zip')]
      : phase === 'refresh'
        ? [job('modal-refresh-job', 'modal-refresh.zip')]
        : [];
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items}),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady))).toBe(true);

  const callsBeforeOpen = listCalls;
  phase = 'open';
  await page.evaluate(async () => { await window.openImportDock(); });
  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalTitle')).toHaveText('后台导入任务');
  await expect(page.locator('#modalBody')).toContainText('modal-open.zip');
  await expect(page.locator('#modalBody')).toContainText('导入完成');
  expect(listCalls).toBeGreaterThan(callsBeforeOpen);

  const callsBeforeRefresh = listCalls;
  phase = 'refresh';
  await page.locator('#modalBody').getByRole('button', {name: '刷新'}).click();
  await expect(page.locator('#modalBody')).toContainText('modal-refresh.zip');
  await expect(page.locator('#modalBody')).not.toContainText('modal-open.zip');
  expect(listCalls).toBeGreaterThan(callsBeforeRefresh);
  expect(pageErrors).toEqual([]);
});

test('training server connection keeps existing form and payload behavior', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('训练资源'));
  await expect(page.locator('#title')).toContainText('训练资源');
  await expect(page.locator('#quickServerUrl')).toBeVisible({timeout: 10_000});

  let submittedBody = null;
  await page.route('**/api/train_servers', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    submittedBody = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'server-r20c',
        name: submittedBody?.name || 'R20c训练服务器',
        base_url: submittedBody?.base_url || 'http://127.0.0.1:18020',
        status: 'configured',
      }),
    });
  });

  await page.locator('#quickServerUrl').fill('http://127.0.0.1:18020');
  await page.getByRole('button', {name: '接入服务器'}).click();
  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#surl')).toHaveValue('http://127.0.0.1:18020');
  await page.locator('#sname').fill('R20c训练服务器');
  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  await page.route(`**/api/training_options?project_id=${encoded}`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({targets: [{
        id: 'server-r20c',
        name: 'R20c训练服务器',
        type: 'server',
        framework: 'ultralytics',
        status: 'ready',
        version: 'remote',
        algorithms: [],
        base_models: [],
      }]}),
    });
  });
  await expect.poll(async () => page.evaluate(() => !state.__extras412)).toBe(true);
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await page.locator('#modalBody').getByRole('button', {name: '保存'}).click();

  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#toast')).toContainText('已保存服务器');
  expect(submittedBody).toEqual({
    name: 'R20c训练服务器',
    base_url: 'http://127.0.0.1:18020',
  });
  await expect.poll(async () => page.evaluate(() => state.targets.find(x => x.id === 'server-r20c')?.name || null)).toBe('R20c训练服务器');
  await expect(page.locator('.resource-grid')).toContainText('R20c训练服务器');
  const ownedRequests = requests.filter(row => row.includes('/api/train_servers') || row.includes('/api/training_options') || row.includes('/bootstrap/snapshot'));
  expect(ownedRequests).toEqual([
    'POST /api/train_servers',
    `GET /api/training_options?project_id=${projectId}`,
  ]);
  expect(pageErrors).toEqual([]);
});



test('paddle environment activation keeps manual and quick-detect behavior', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  const selectBodies = [];
  const testBodies = [];
  let detectCalls = 0;

  await page.route('**/api/paddle_env/select', async route => {
    const body = route.request().postDataJSON();
    selectBodies.push(body);
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, active: body})});
  });
  await page.route('**/api/paddle_env/test', async route => {
    const body = route.request().postDataJSON();
    testBodies.push(body);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, modules: {paddle: '3.0.0'}, paddledet_exists: true, algorithm_scan: {total: 12, families: {ppyoloe: 12}}}),
    });
  });
  await page.route('**/api/paddle_env/detect', async route => {
    detectCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, candidates: [{
        name: '自动飞桨',
        python_path: '/opt/paddle/bin/python',
        paddledet_dir: '/opt/PaddleDetection',
        paddlex_dir: '/opt/PaddleX',
        algorithm_scan: {total: 12, families: {ppyoloe: 12}},
      }]}),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('训练资源'));
  await expect(page.locator('#title')).toContainText('训练资源');

  const projectId = await page.evaluate(() => state.project?.id || '');
  const actionRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) actionRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await page.route(/\/api\/training_options(?:\?.*)?$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({targets: [{
        id: 'local_paddle',
        name: 'R20d 飞桨环境',
        framework: 'paddle',
        type: 'local',
        version: '3.0.0',
        status: 'ready',
        python_path: '/opt/paddle/bin/python',
        paddledet_dir: '/opt/PaddleDetection',
        paddlex_dir: '/opt/PaddleX',
        algorithms: [],
        base_models: [],
      }]}),
    });
  });

  const paddleCard = page.locator('.quick-card').filter({hasText: '本机飞桨'}).last();
  await expect(paddleCard).toBeVisible();
  await paddleCard.locator('#ppy').fill('/manual/paddle/python');
  await paddleCard.locator('#pdet').fill('/manual/PaddleDetection');
  await paddleCard.locator('#pxdir').fill('/manual/PaddleX');
  await paddleCard.getByRole('button', {name: '检测并启用'}).click();
  await expect(page.locator('#toast')).toContainText('飞桨环境已启用');
  expect(selectBodies[0]).toMatchObject({
    name: '本机飞桨',
    python_path: '/manual/paddle/python',
    paddledet_dir: '/manual/PaddleDetection',
    paddlex_dir: '/manual/PaddleX',
  });
  expect(testBodies[0]).toMatchObject(selectBodies[0]);

  const currentPaddleCard = page.locator('.quick-card').filter({hasText: '本机飞桨'}).last();
  await currentPaddleCard.getByRole('button', {name: '一键检测'}).click();
  await expect(page.locator('#toast')).toContainText('已启用飞桨环境');
  expect(detectCalls).toBe(1);
  expect(selectBodies.at(-1)).toMatchObject({
    name: '自动飞桨',
    python_path: '/opt/paddle/bin/python',
    paddledet_dir: '/opt/PaddleDetection',
    paddlex_dir: '/opt/PaddleX',
  });
  await expect.poll(async () => page.evaluate(() => state.targets.find(x => x.id === 'local_paddle')?.name || '')).toBe('R20d 飞桨环境');
  const relevant = actionRequests.filter(row => row.includes('/api/paddle_env/') || row.includes('/api/training_options') || row.includes('/bootstrap/snapshot'));
  expect(relevant.filter(row => row.startsWith('POST /api/paddle_env/select'))).toHaveLength(2);
  expect(relevant.filter(row => row.startsWith('POST /api/paddle_env/test'))).toHaveLength(1);
  expect(relevant.filter(row => row.startsWith('POST /api/paddle_env/detect'))).toHaveLength(1);
  expect(relevant.filter(row => row === `GET /api/training_options?project_id=${projectId}`)).toHaveLength(2);
  expect(relevant.filter(row => row.includes('/bootstrap/snapshot'))).toEqual([]);
  expect(pageErrors).toEqual([]);
});


test('model config delete keeps model configuration page consistent', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.route(/\/api\/v35\/model-configs\/cfg-r20e$/, async route => {
    if (route.request().method() !== 'DELETE') return route.continue();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });
  await page.route(/\/api\/v35\/model-configs(?:\?.*)?$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: []})});
  });

  page.on('dialog', dialog => dialog.accept());
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => state.uiReady === true), {timeout: 15_000}).toBe(true);
  await page.evaluate(() => {
    state.page = '模型配置';
    state.modelConfigs = [{
      id: 'cfg-r20e',
      name: 'R20e 模型配置',
      provider_type: 'local',
      model_name: 'r20e-model',
      detect_url: 'http://127.0.0.1:9000/detect',
    }];
    state.promptTemplates = [];
    render();
  });
  await expect(page.locator('#title')).toContainText('模型配置');
  await expect(page.locator('#view')).toContainText('R20e 模型配置');

  const actionRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) actionRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await page.getByRole('button', {name: '删除'}).first().click();
  await expect(page.locator('#toast')).toContainText('已删除');
  await expect(page.locator('#view')).not.toContainText('R20e 模型配置');
  expect(actionRequests.filter(row => row === 'DELETE /api/v35/model-configs/cfg-r20e')).toHaveLength(1);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v35/model-configs'))).toEqual([]);
  expect(actionRequests.filter(row => row.includes('/bootstrap/snapshot'))).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('prompt template save appears immediately in model configuration', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.route(/\/api\/v35\/prompt-templates$/, async route => {
    const request = route.request();
    if (request.method() !== 'POST') return route.continue();
    const body = request.postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({...body, id: 'tpl-r20e-new', created_at: '2026-09-12T00:00:00Z'}),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => {
    state.page = '模型配置';
    state.modelConfigs = [];
    state.promptTemplates = [];
    render();
    window.openPromptTemplateModalV35();
  });
  await page.locator('#ptName').fill('R20e 新提示词');
  await page.locator('#ptLabels').fill('fire');
  await page.locator('#ptPrompt').fill('detect fire and return bbox json');
  const actionRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) actionRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await page.getByRole('button', {name: '保存模板'}).click();
  await expect(page.locator('#toast')).toContainText('已保存模型标注模板');
  await expect(page.locator('#view')).toContainText('R20e 新提示词');
  await expect.poll(async () => page.evaluate(() => state.promptTemplates.find(x => x.id === 'tpl-r20e-new')?.name || '')).toBe('R20e 新提示词');
  expect(actionRequests.filter(row => row === 'POST /api/v35/prompt-templates')).toHaveLength(1);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v35/prompt-templates'))).toEqual([]);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v35/model-configs'))).toEqual([]);
  expect(actionRequests.filter(row => row.includes('/bootstrap/snapshot'))).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('prompt template delete disappears immediately in model configuration', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.route(/\/api\/v35\/prompt-templates\/tpl-r20e-old$/, async route => {
    if (route.request().method() !== 'DELETE') return route.continue();
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });

  page.on('dialog', dialog => dialog.accept());
  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => {
    state.page = '模型配置';
    state.modelConfigs = [];
    state.promptTemplates = [{
      id: 'tpl-r20e-old',
      name: 'R20e 旧提示词',
      framework: 'common',
      save_format: 'internal',
      labels: ['fire'],
      prompt: 'old prompt',
    }];
    render();
  });
  await expect(page.locator('#view')).toContainText('R20e 旧提示词');
  const row = page.locator('tr').filter({hasText: 'R20e 旧提示词'});
  const actionRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) actionRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await row.getByRole('button', {name: '删除'}).click();
  await expect(page.locator('#toast')).toContainText('已删除');
  await expect(page.locator('#view')).not.toContainText('R20e 旧提示词');
  await expect.poll(async () => page.evaluate(() => state.promptTemplates.some(x => x.id === 'tpl-r20e-old'))).toBe(false);
  expect(actionRequests.filter(row => row === 'DELETE /api/v35/prompt-templates/tpl-r20e-old')).toHaveLength(1);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v35/prompt-templates'))).toEqual([]);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v35/model-configs'))).toEqual([]);
  expect(actionRequests.filter(row => row.includes('/bootstrap/snapshot'))).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('model config save appears immediately without broad related refresh', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.route(/\/api\/v35\/model-configs(?:\?.*)?$/, async route => {
    const request = route.request();
    if (request.method() === 'GET') {
      await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: []})});
      return;
    }
    if (request.method() !== 'POST') return route.continue();
    const body = request.postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ...body,
        id: 'cfg-r20f-new',
        has_api_key: false,
        api_key_masked: '',
        created_at: '2026-09-12T10:30:00Z',
        updated_at: '2026-09-12T10:30:00Z',
      }),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => {
    state.page = '模型配置';
    state.modelConfigs = [];
    state.promptTemplates = [];
    render();
    window.openModelConfigModalV35();
  });

  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await page.locator('#mcName').fill('R20f 新模型配置');
  await page.locator('#mcModel').fill('r20f-vision-model');
  await page.locator('#mcUrl').fill('http://127.0.0.1:19020/detect');

  const actionRequests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) actionRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  await page.locator('#modalBody').getByRole('button', {name: '保存'}).click();
  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#toast')).toContainText('模型配置已保存');
  await expect(page.locator('#view')).toContainText('R20f 新模型配置');
  await expect.poll(async () => page.evaluate(() => state.modelConfigs.find(x => x.id === 'cfg-r20f-new')?.name || '')).toBe('R20f 新模型配置');

  expect(actionRequests.filter(row => row === 'POST /api/v35/model-configs')).toHaveLength(1);
  expect(actionRequests.filter(row => row.startsWith('GET /api/projects/'))).toEqual([]);
  expect(actionRequests.filter(row => row.startsWith('GET /api/v12/projects/'))).toEqual([]);
  expect(actionRequests.filter(row => row.includes('/bootstrap/snapshot'))).toEqual([]);
  expect(pageErrors).toEqual([]);
});


test('platform integration is installed as a canonical navigation owner', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.route('**/api/v63/external-algorithm-platform/**', async route => {
    const path = new URL(route.request().url()).pathname;
    const body = path.endsWith('/config')
      ? {mode:'local', provider:'changlian', base_url:'', credentials:{configured:false, available:true}}
      : path.endsWith('/history')
        ? {items:[]}
        : path.endsWith('/cache')
          ? {categories:[], products:[], analyses:[], compute_platforms:[]}
          : {ready:true, status:'local'};
    await route.fulfill({status:200, contentType:'application/json', body:JSON.stringify(body)});
  });

  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state.uiReady)), {timeout:15_000}).toBe(true);
  await expect.poll(() => page.evaluate(() => Boolean(window.NavigationStability?.hasPageOwner?.('平台对接'))))
    .toBe(true);

  await page.evaluate(async () => {
    const result = window.setPage('平台对接');
    if (result && typeof result.then === 'function') await result;
  });
  await expect(page.locator('#title')).toHaveText('平台对接');
  await expect(page.locator('[data-external-platform-page="1"]')).toBeVisible({timeout:10_000});
  await expect(page.locator('#view [data-unknown-page]')).toHaveCount(0);
  expect(pageErrors).toEqual([]);
});


test('formal utility pages avoid unknown-module fallback and retired deployment routes normalize safely', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state.uiReady)), {timeout: 15_000}).toBe(true);

  const pages = [
    '工作台',
    '质量中心',
    '标签管理',
    '模型配置',
    '组件检测',
    '平台对接',
    '服务节点',
  ];

  for (const target of pages) {
    await page.evaluate(async name => {
      const result = window.setPage(name);
      if (result && typeof result.then === 'function') await result;
    }, target);

    await expect.poll(() => page.evaluate(() => state.page), {timeout: 10_000}).toBe(target);
    await expect(page.locator('#title')).toHaveText(target);
    const fallback = page.locator('#view [data-unknown-page]');
    await expect(fallback, `formal page ${target} must have a concrete renderer owner`).toHaveCount(0);
    await expect(page.locator('#view')).not.toContainText('当前页面模块尚未就绪');
    await expect(page.locator('#view')).not.toContainText('当前页面不存在或已下线');
  }

  const aliases = [
    ['部署转换', '算法列表'],
    ['部署产物', '算法列表'],
    ['部署资源', '模型配置'],
    ['部署插件', '模型配置'],
  ];
  for (const [legacy, canonical] of aliases) {
    await page.evaluate(async name => {
      const result = window.setPage(name);
      if (result && typeof result.then === 'function') await result;
    }, legacy);
    await expect.poll(() => page.evaluate(() => state.page), {timeout: 10_000}).toBe(canonical);
    await expect(page.locator('#title')).toHaveText(canonical);
  }

  expect(pageErrors).toEqual([]);
});
