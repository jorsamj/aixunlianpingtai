import {test, expect} from '@playwright/test';

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

  await expect.poll(async () => page.evaluate(() => {
    const row = window.PollRegistryRuntime?.snapshot?.().find(item => item.key === 'training-jobs');
    return row ? {managed: row.managed, owners: row.owners, delay: row.delay} : null;
  })).toMatchObject({managed: true, owners: ['训练任务', '检测台']});

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

  await page.evaluate(() => window.setPage('素材存储配置'));
  await expect(page.locator('#title')).toContainText('素材存储配置');
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

  for (const route of ['算法列表', '数据集', '训练任务', '自动标注及清洗', '质量中心', '视频切帧', '标签管理', '部署资源', '素材存储配置']) {
    await page.evaluate(next => window.setPage(next), route);
    await expect(page.locator('#title')).toContainText(route);
    await expectFormalVersion();
  }

  await page.waitForTimeout(1_800);
  await expectFormalVersion();
  expect(pageErrors).toEqual([]);
});

test('file input beautification survives page render lifecycle ownership', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});

  await page.evaluate(() => window.setPage('测试发布'));
  await expect(page.locator('#title')).toContainText('测试发布');
  await expect(page.locator('#predFile')).toHaveClass(/native-file426/);
  await expect(page.locator('#predFile + .filepicker426')).toBeVisible();
  await expect(page.locator('#predFile + .filepicker426 .filepicker426-btn')).toContainText('选择图片');

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

  await page.route(/\/api\/v19\/projects\/[^/]+\/datasets\/default\/import\/jobs$/, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'zip-browser-1',
        image_count: 3,
        format_hints: ['YOLO'],
        upload_seconds: 0.1,
        scan_seconds: 0.1,
      }),
    });
  });
  await page.route(/\/api\/v19\/projects\/[^/]+\/import\/jobs\/zip-browser-1\/start$/, async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });
  await page.route(/\/api\/v19\/projects\/[^/]+\/import\/jobs\/zip-browser-1$/, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        id: 'zip-browser-1',
        status: 'done',
        stage: '导入完成',
        message: '完成',
        progress: 100,
        processing_seconds: 0.2,
        report: {imported_images: 3, annotated_images: 2, boxes: 5, warnings: []},
      }),
    });
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

test('base modal post-open content refresh stays functional', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  let listCalls = 0;

  await page.route(/\/api\/v19\/projects\/[^/]+\/import\/jobs$/, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    listCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: listCalls === 1 ? [] : [{
        id: 'modal-refresh-job',
        file_name: 'modal-refresh.zip',
        status: 'done',
        stage: '导入完成',
        message: '完成',
        image_count: 2,
        report: {imported_images: 2, annotated_images: 1, boxes: 3, warnings: []},
      }]}),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(async () => { await window.openImportDock(); });

  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalTitle')).toHaveText('后台导入任务');
  await expect(page.locator('#modalBody')).toContainText('暂无导入任务');

  await page.locator('#modalBody').getByRole('button', {name: '刷新'}).click();
  await expect(page.locator('#modalBody')).toContainText('modal-refresh.zip');
  await expect(page.locator('#modalBody')).toContainText('导入完成');
  expect(listCalls).toBeGreaterThanOrEqual(2);
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

