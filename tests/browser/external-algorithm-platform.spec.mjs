import {test, expect} from '@playwright/test';

async function selectIsolatedTestProject(page, projectId) {
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', projectId);
    await route.continue({url: url.toString()});
  });
}

test('changlian platform page tests draft credentials before manual sync', async ({page}) => {
  let testedPayload = null;
  let savedPayload = null;
  let syncWrites = 0;
  let analysisStatus = 'success';
  let configSaved = false;
  let saveWrites = 0;
  let savedBaseUrl = '';
  let configGets = 0;
  let historyGets = 0;
  let cacheGets = 0;
  let readinessGets = 0;

  await page.route('**/api/v63/external-algorithm-platform/config', async route => {
    if (route.request().method() === 'PUT') {
      savedPayload = route.request().postDataJSON();
      savedBaseUrl = savedPayload.base_url;
      configSaved = true;
      saveWrites += 1;
    } else if (route.request().method() !== 'GET') {
      return route.continue();
    } else {
      configGets += 1;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        config: {
          mode: 'external',
          provider: 'changlian',
          provider_name: '新畅联',
          base_url: configSaved ? savedBaseUrl : '',
          auto_sync_enabled: false,
          auto_sync_interval_seconds: 600,
          auto_publish_enabled: false,
          auth_mode: 'test_sign_bridge',
          business_auth_mode: 'authorization_bearer',
          api_document_summary: {total: 31, wired: 30, documented: 0, reference: 1},
          api_documents: [
            {
              key: 'auth_token',
              group: '应用鉴权',
              title: '内部应用鉴权获取Token',
              doc_url: 'https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515307570e0.md',
              status: 'wired',
              method: 'POST',
              path: '/internal/auth/token',
            },
            {
              key: 'version_update',
              group: '算法版本管理',
              title: '修改算法版本',
              doc_url: 'https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837714e0.md',
              status: 'wired',
              method: 'POST',
              path: '/internal/algorithm/algorithm-version/edit',
            },
          ],
          credentials: {
            configured: configSaved,
            masked: configSaved ? 'AK-****1234' : '',
            available: true,
            backend: 'encrypted_file',
            writable: true,
          },
          updated_at: configSaved ? '2026-09-20T06:55:00Z' : null,
          endpoints: {
            test_sign: '/internal/auth/test-sign',
            token: '/internal/auth/token',
            category_tree: '/internal/base/category/tree',
            product_list: '/internal/algorithm/product-ai/listAll',
            analysis_by_product: '/internal/algorithm/algorithm-analysis/listByProduct/{productId}',
            compute_platform_list: '/internal/base/compute-platform/listAll',
            version_create: '/internal/algorithm/algorithm-version/add',
            weight_create: '/internal/algorithm/algorithm-weight/add',
          },
          cache: {
            category_count: 2,
            product_count: 3,
            analysis_count: 4,
            compute_platform_count: 2,
          },
        },
      }),
    });
  });

  await page.route('**/api/v63/external-algorithm-platform/sync-history?limit=20', async route => {
    historyGets += 1;
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, items: []})});
  });

  await page.route('**/api/v63/external-algorithm-platform/cache', async route => {
    cacheGets += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        cache: {
          provider: 'changlian',
          categories: [{categoryId: 'c1', categoryName: '行为分析'}],
          products: [{productId: 'p1', productName: '抽烟检测', categoryId: 'c1'}],
          analyses_by_product: {p1: [{analysisId: 'a1', analysisName: '视觉智能分析', analysisType: 1, status: 1}]},
          compute_platforms: [{computePlatformId: 'cp1', computePlatformName: 'RK3568'}],
        },
      }),
    });
  });

  await page.route('**/api/v63/external-algorithm-platform/readiness?project_id=*', async route => {
    readinessGets += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        ready: true,
        scope: 'master_data_training',
        provider: 'changlian',
        auth_type: 'application_credentials',
        human_login_required: false,
        blocking_keys: [],
        checks: [
          {key: 'human_login', name: '人员登录账号', status: 'not_required', detail: '系统对接不使用人员用户名/密码；内部 API 使用 AccessKey / AccessSecret 应用鉴权。'},
          {key: 'external_mode', name: '外部平台模式', status: 'ready', detail: '已启用新畅联'},
          {key: 'base_url', name: 'API 服务地址', status: 'ready', detail: 'https://saved.example.test'},
          {key: 'credentials', name: '应用凭据', status: 'ready', detail: '已配置 · encrypted_file'},
          {key: 'last_sync', name: '最近主数据同步', status: 'ready', detail: '2026-09-19T12:00:00Z'},
          {key: 'categories', name: '算法品目', status: 'ready', count: 2},
          {key: 'products', name: '算法产品', status: 'ready', count: 3},
          {key: 'analyses', name: '产品分析方式', status: 'ready', count: 4},
          {key: 'compute_platforms', name: '算力环境', status: 'ready', count: 2},
          {key: 'project_algorithms', name: '当前项目畅联云算法', status: 'ready', count: 1, detail: '同步算法 1 个，当前可训练 1 个'},
        ],
      }),
    });
  });

  await page.route('**/api/v63/external-algorithm-platform/sync?project_id=*', async route => {
    syncWrites += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        sync: {status: 'success', counts: {categories: 2, products: 3, analyses: 4, compute_platforms: 2, added: 1, updated: 2}},
      }),
    });
  });

  await page.route('**/api/v63/external-algorithm-platform/test', async route => {
    testedPayload = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        provider: 'changlian',
        provider_name: '新畅联',
        base_url: testedPayload.base_url,
        auth_mode: 'test_sign_bridge',
        tested_at: '2026-09-19T12:00:00Z',
        steps: [
          {key: 'auth', name: '应用鉴权', status: 'success'},
          {key: 'categories', name: '算法品目', status: 'success', count: 2},
          {key: 'products', name: '算法产品', status: 'success', count: 3},
          {key: 'compute_platforms', name: '算力环境', status: 'success', count: 2},
          analysisStatus === 'success'
            ? {key: 'analysis', name: '产品分析方式', status: 'success', count: 1}
            : {key: 'analysis', name: '产品分析方式', status: 'skipped', detail: '当前没有可用于连接测试的算法产品'},
          analysisStatus === 'success'
            ? {key: 'versions', name: '算法版本', status: 'success', count: 2}
            : {key: 'versions', name: '算法版本', status: 'skipped', detail: '当前没有可用于连接测试的算法产品'},
          analysisStatus === 'success'
            ? {key: 'weights', name: '算法权重', status: 'success', count: 3}
            : {key: 'weights', name: '算法权重', status: 'skipped', detail: '当前没有可用于连接测试的算法产品'},
        ],
      }),
    });
  });

  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => ({
    setPageReady: typeof window.setPage === 'function',
    uiReady: typeof state !== 'undefined' ? !!state.uiReady : false,
  })), {timeout: 20_000}).toEqual({setPageReady: true, uiReady: true});

  await page.evaluate(() => window.setPage('平台对接'));
  await expect(page.getByRole('heading', {name: '平台对接', level: 2})).toBeVisible({timeout: 10_000});
  await expect.poll(() => [
    configGets > 0,
    historyGets > 0,
    cacheGets > 0,
    readinessGets > 0,
  ], {timeout: 10_000}).toEqual([true, true, true, true]);
  const firstVisitGets = {configGets, historyGets, cacheGets, readinessGets};
  await page.evaluate(() => window.setPage('工作台'));
  await expect(page.locator('#title')).toContainText('总览');
  await page.evaluate(() => window.setPage('平台对接'));
  await expect(page.getByRole('heading', {name: '平台对接', level: 2})).toBeVisible();
  await page.waitForTimeout(120);
  expect({configGets, historyGets, cacheGets, readinessGets}).toEqual(firstVisitGets);
  await page.evaluate(() => { window.__externalPlatformStableRoot = document.querySelector('[data-external-platform-page="1"]'); });

  await expect(page.locator('[data-changlian-readiness]')).toHaveCount(0);
  await expect(page.getByRole('button', {name: '概览', exact: true})).toBeVisible();
  await expect(page.getByRole('button', {name: /厂商对应表/})).toBeVisible();

  await page.getByRole('button', {name: '接口契约', exact: true}).click();
  const apiContract = page.locator('[data-changlian-api-contract="1"]');
  await expect(apiContract).toBeVisible();
  await expect(apiContract).toContainText('已核对 31 个官方 OpenAPI 接口');
  await expect(apiContract).toContainText('POST /internal/auth/token');
  await expect(apiContract).toContainText('修改算法版本');
  await expect(apiContract).toContainText('POST /internal/algorithm/algorithm-version/edit');

  await page.getByRole('button', {name: '连接配置', exact: true}).click();
  await page.locator('#externalBaseUrl').fill('https://draft.example.test');
  await page.locator('#externalAccessKey').fill('draft-ak');
  await page.locator('#externalAccessSecret').fill('draft-secret');

  await expect(page.locator('[data-external-sync-settings="1"]')).not.toHaveAttribute('open', '');
  await page.locator('[data-external-sync-settings="1"] summary').click();
  await expect(page.locator('#externalAutoSyncInterval')).toHaveCount(0);
  await expect(page.locator('.external-sync-policy')).toContainText('自动同步已启用');
  await expect(page.locator('.external-sync-policy')).toContainText('每天 08:00、12:00、15:00（北京时间）各主动拉取一次主数据');
  const syncButton = page.getByRole('button', {name: '↻ 立即同步'});
  await expect(syncButton).toBeDisabled();
  await expect(syncButton).toHaveAttribute('title', /未保存修改/);

  await page.getByRole('button', {name: '测试连接'}).click();

  await expect.poll(() => testedPayload).not.toBeNull();
  expect(testedPayload.base_url).toBe('https://draft.example.test');
  expect(testedPayload.access_key).toBe('draft-ak');
  expect(testedPayload.access_secret).toBe('draft-secret');
  expect(testedPayload.mode).toBe('external');
  expect(testedPayload.auto_sync_interval_seconds).toBeUndefined();

  const connectionResult = page.locator('#externalConnectionResult');
  await expect(connectionResult.getByText('连接成功')).toBeVisible();
  await expect(connectionResult.getByRole('cell', {name: '应用鉴权'})).toBeVisible();
  await expect(connectionResult.getByRole('cell', {name: '算法品目'})).toBeVisible();
  await expect(connectionResult.getByRole('cell', {name: '算法产品'})).toBeVisible();
  await expect(connectionResult.getByRole('cell', {name: '算力环境'})).toBeVisible();
  await expect(connectionResult.getByRole('cell', {name: '产品分析方式'})).toBeVisible();

  await page.getByRole('button', {name: '保存配置'}).click();
  await expect.poll(() => savedPayload).not.toBeNull();
  expect(savedPayload.base_url).toBe('https://draft.example.test');
  expect(savedPayload.access_key).toBe('draft-ak');
  expect(savedPayload.access_secret).toBe('draft-secret');
  expect(savedPayload.auto_sync_interval_seconds).toBeUndefined();
  await expect.poll(() => saveWrites).toBe(1);

  // Saved configuration is locked until the user explicitly enters edit mode.
  await expect(page.getByRole('button', {name: '编辑配置'})).toBeVisible();
  await expect(page.getByRole('button', {name: '保存配置'})).toHaveCount(0);
  await expect(page.locator('#externalBaseUrl')).toBeDisabled();
  await expect(page.locator('#externalAccessKey')).toBeDisabled();
  await expect(page.locator('#externalAccessSecret')).toBeDisabled();
  await expect(page.locator('#externalBaseUrl')).toHaveValue('https://draft.example.test');
  await expect(syncButton).toBeEnabled();

  // Locked connection tests submit no new credential values; backend reuses secure saved credentials.
  testedPayload = null;
  await page.getByRole('button', {name: '测试连接'}).click();
  await expect.poll(() => testedPayload).not.toBeNull();
  expect(testedPayload.base_url).toBe('https://draft.example.test');
  expect(testedPayload.access_key).toBeNull();
  expect(testedPayload.access_secret).toBeNull();

  // Edit can be cancelled without mutating the persisted platform.
  await page.getByRole('button', {name: '编辑配置'}).click();
  await expect(page.locator('#externalBaseUrl')).toBeEnabled();
  await expect(page.getByRole('button', {name: '取消编辑'})).toBeVisible();
  await page.locator('#externalBaseUrl').fill('https://cancelled.example.test');
  await expect(syncButton).toBeDisabled();
  await page.getByRole('button', {name: '取消编辑'}).click();
  await expect(page.locator('#externalBaseUrl')).toBeDisabled();
  await expect(page.locator('#externalBaseUrl')).toHaveValue('https://draft.example.test');
  expect(saveWrites).toBe(1);

  // The persisted platform changes only after Edit -> Save, then locks again.
  await page.getByRole('button', {name: '编辑配置'}).click();
  await page.locator('#externalBaseUrl').fill('https://edited.example.test');
  savedPayload = null;
  await page.getByRole('button', {name: '保存配置'}).click();
  await expect.poll(() => saveWrites).toBe(2);
  await expect.poll(() => savedPayload).not.toBeNull();
  expect(savedPayload.base_url).toBe('https://edited.example.test');
  expect(savedPayload.access_key).toBeNull();
  expect(savedPayload.access_secret).toBeNull();
  await expect(page.getByRole('button', {name: '编辑配置'})).toBeVisible();
  await expect(page.locator('#externalBaseUrl')).toBeDisabled();
  await expect(page.locator('#externalBaseUrl')).toHaveValue('https://edited.example.test');

  await syncButton.click();
  await expect.poll(() => syncWrites).toBe(1);

  analysisStatus = 'skipped';
  await page.getByRole('button', {name: '测试连接'}).click();
  await expect(connectionResult.getByText('连接成功')).toBeVisible();
  const analysisRow = connectionResult.getByRole('row', {name: /产品分析方式/});
  await expect(analysisRow.getByText('跳过', {exact: true})).toBeVisible();
  await expect(analysisRow).toContainText('当前没有可用于连接测试的算法产品');
  expect(await page.evaluate(() => window.__externalPlatformStableRoot === document.querySelector('[data-external-platform-page="1"]'))).toBe(true);
});


test('stale changlian algorithm is visibly blocked before training submit', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `畅联云旧主数据-${Date.now()}`,
    labels: [{code: 'smoke', display_name: '烟雾'}],
  }})).json();
  const created = await (await request.post(`/api/v12/projects/${project.id}/algorithms`, {data: {
    name: '待同步抽烟检测',
    industry: '测试',
    algorithm_type: 'yolo_ultralytics',
    remark: '',
  }})).json();
  const algorithmId = created.algorithm.id;

  await page.route('**/api/v63/external-algorithm-platform/config', route => {
    if (route.request().method() !== 'GET') return route.continue();
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        config: {
          mode: 'external',
          provider: 'changlian',
          provider_name: '新畅联',
          base_url: 'https://saved.example.test',
          auto_sync_enabled: false,
          auto_sync_interval_seconds: 600,
          auto_publish_enabled: false,
          auth_mode: 'test_sign_bridge',
          credentials: {configured: true, masked: 'AK-****1234', available: true, backend: 'encrypted_file', writable: true},
          cache: {
            master_data_digest: 'digest-current',
            category_count: 1,
            product_count: 1,
            analysis_count: 1,
            compute_platform_count: 1,
          },
          endpoints: {},
        },
      }),
    });
  });
  await page.route('**/api/v63/external-algorithm-platform/cache', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      ok: true,
      cache: {
        provider: 'changlian',
        master_data_digest: 'digest-current',
        categories: [{categoryId: 'c1', categoryName: '行为分析'}],
        products: [{productId: 'p1', productName: '待同步抽烟检测', categoryId: 'c1'}],
        analyses_by_product: {p1: [{analysisId: 'a1', analysisName: '视觉智能分析', analysisType: 1, status: 1}]},
        compute_platforms: [{computePlatformId: 'cp1', computePlatformName: 'RK3568'}],
      },
    }),
  }));

  await selectIsolatedTestProject(page, project.id);
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page: '算法列表'}));
  });
  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  await expect.poll(async () => page.evaluate(() => window.ExternalAlgorithmPlatformRuntime?.config?.()?.mode || ''))
    .toBe('external');

  await page.getByRole('button', {name: /算法列表/}).click();
  await expect(page.locator('#alg412List')).toBeVisible();
  await page.evaluate(({algorithmId}) => {
    const asset = (state.algorithms || []).find(row => String(row.id) === String(algorithmId));
    if (!asset) throw new Error('algorithm missing from canonical state');
    Object.assign(asset, {
      source_type: 'EXTERNAL',
      provider_type: 'CHANG_LIAN',
      source_name: '新畅联',
      external_product_id: 'p1',
      external_category_id: 'c1',
      external_analysis_id: 'a1',
      external_analysis_ids: ['a1'],
      external_analyses: [{analysis_id: 'a1', analysis_name: '视觉智能分析', analysis_type: '1', status: '1'}],
      external_active: true,
      external_master_data_digest: 'digest-old',
      external_last_synced_at: '2026-09-19T12:00:00Z',
    });
    window.renderAlg412?.();
    window.AlgorithmListRuntime?.runDecorators?.();
  }, {algorithmId});

  const listOwner = page.locator('[data-algorithm-list-owner="AlgorithmListRuntime"]');
  const sourceFilter = listOwner.locator('[data-algorithm-source-filter]');
  const trainingStatusFilter = listOwner.locator('[data-algorithm-training-status-filter]');
  const categoryToggle = listOwner.locator('[data-category-picker-toggle]');
  const categoryPopover = listOwner.locator('[data-category-popover]');
  await expect(sourceFilter).toBeVisible();
  await expect(trainingStatusFilter).toBeVisible();
  await expect(categoryToggle).toBeVisible();
  await categoryToggle.click();
  await expect(categoryPopover.getByPlaceholder('搜索品目名称或路径')).toBeVisible();
  await expect(categoryPopover.getByText('行为分析', {exact: true})).toBeVisible();
  await expect(page.getByRole('button', {name: /新建算法/})).toBeVisible();
  const syncButton = listOwner.locator('[data-algorithm-sync]');
  await expect(syncButton).toBeVisible();
  await expect(syncButton).toHaveText('同步畅联云');

  const card = page.locator('.alg428-card', {hasText: '待同步抽烟检测'});
  await expect(card).toBeVisible();
  await sourceFilter.selectOption('internal');
  await expect(card).toBeHidden();
  await sourceFilter.selectOption('external');
  await expect(card).toBeVisible();
  await categoryPopover.locator('[data-category-check="c1"]').check();
  await categoryPopover.locator('[data-category-confirm]').click();
  await expect(card).toBeVisible();
  await trainingStatusFilter.selectOption('blocked');
  await expect(card).toBeVisible();
  const status = card.locator('.entity-status');
  await expect(status).toHaveText('不可训练');
  await expect(status).toHaveAttribute('title', /立即同步/);
  const trainButton = card.getByRole('button', {name: '训练'});
  await expect(trainButton).toBeDisabled();
  await expect(trainButton).toHaveAttribute('title', /立即同步/);
});

async function prepareCleanupPlatform(page, request, operations) {
  const project = await (await request.post('/api/projects', {data:{name:`清理专项-${Date.now()}`,labels:[{code:'test',display_name:'测试'}]}})).json();
  await selectIsolatedTestProject(page, project.id);
  const json = (route, body, status=200) => route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  await page.route('**/api/v63/external-algorithm-platform/**', async route => {
    const url=new URL(route.request().url());
    if(url.pathname.endsWith('/config')) return json(route,{config:{mode:'external',base_url:'https://example.invalid',credentials:{configured:true},cache:{master_data_digest:'digest'}}});
    if(url.pathname.endsWith('/cache')) return json(route,{cache:{categories:[],products:[],master_data_digest:'digest'}});
    if(url.pathname.endsWith('/sync-history')) return json(route,{items:[{operation_id:'sync-old',status:'failed',current_phase:'fetch_products',error:'产品分页不完整',counts:{products:2},success_count:2,error_count:1}]});
    if(url.pathname.endsWith('/sync-operation')) return json(route,{operation:{operation_id:'sync-old',status:'success',current_phase:'completed'},cleanup_summary:{SUSPECTED_DELETED:1,CLEANUP_FAILED:1,CLEANUP_PENDING:0,CLEANUP_RUNNING:0,CLEANUP_COMPLETED:0}});
    if(url.pathname.endsWith('/cleanup-operations')) {const offset=Number(url.searchParams.get('offset')||0);return json(route,{items:operations.slice(offset,offset+25),total:operations.length,offset,limit:25,has_more:offset+25<operations.length});}
    if(url.pathname.includes('/cleanup-operations/')) {
      const id=decodeURIComponent(url.pathname.split('/').at(-1));
      return json(route,{operation:operations.find(row=>row.operation_id===id)});
    }
    if(url.pathname.endsWith('/readiness')) return json(route,{ok:true});
    return route.continue();
  });
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>state.uiReady===true)).toBe(true);
  await page.evaluate(()=>window.setPage('平台对接'));
  await expect(page.locator('[data-external-platform-page]')).toBeVisible();
  await page.locator('[data-external-platform-tab="sync"]').click();
  return {project,json};
}

test('P0 cleanup UI restores suspected and failed operations, retries same ID and discards closed modal response',async({page,request})=>{
  const operations=[{operation_id:'suspect:a',algorithm_id:'a',algorithm_name:'疑似算法',state:'SUSPECTED_DELETED',phase:'verification_required',evidence:{reason:'分页不完整'},counts:{processed:0,total:1}},
    {operation_id:'failed-op',algorithm_id:'b',algorithm_name:'失败算法',state:'CLEANUP_FAILED',phase:'failed',error:'文件占用，未完成',counts:{processed:2,total:5},task_id:'same-task'}];
  const {json}=await prepareCleanupPlatform(page,request,operations);
  await expect(page.getByText('疑似算法',{exact:true})).toBeVisible();
  await page.locator('[data-cleanup-detail="suspect:a"]').click();
  let detail=page.locator('[data-cleanup-modal-root]').last();
  await expect(detail).toContainText('待核实');await expect(detail).toContainText('已有任务继续');await expect(detail).toContainText('新发布暂缓');
  await expect(detail.locator('[data-cleanup-retry]')).toHaveCount(0);
  await page.evaluate(()=>window.closeModal());
  let retryIds=[];
  await page.route('**/cleanup-operations/failed-op/retry?*',async route=>{
    retryIds.push(new URL(route.request().url()).pathname);
    operations[1]={...operations[1],state:'CLEANUP_COMPLETED',phase:'completed',counts:{processed:5,total:5},error:''};
    await json(route,{ok:true,operation:operations[1]});
  });
  await page.locator('[data-cleanup-detail="failed-op"]').click();
  detail=page.locator('[data-cleanup-modal-root]').last();
  await expect(detail).toContainText('文件占用，未完成');await detail.locator('[data-cleanup-retry]').click();
  await expect(detail).toContainText('清理已完成');expect(retryIds).toEqual(['/api/v63/external-algorithm-platform/cleanup-operations/failed-op/retry']);
  await page.evaluate(()=>window.closeModal());
  let release,readStarted;
  const reading=new Promise(resolve=>{readStarted=resolve});
  await page.route('**/cleanup-operations/suspect%3Aa?*',async route=>{readStarted();await new Promise(resolve=>{release=resolve});await json(route,{operation:operations[0]});});
  await page.locator('[data-cleanup-detail="suspect:a"]').click();await reading;
  await page.evaluate(()=>window.closeModal());release();
  await expect(page.locator('[data-cleanup-modal-root]')).toHaveCount(0);
  await page.unroute('**/cleanup-operations/suspect%3Aa?*');
  await page.reload();await expect.poll(()=>page.evaluate(()=>state.uiReady===true)).toBe(true);
  await page.evaluate(()=>window.setPage('平台对接'));await page.locator('[data-external-platform-tab="sync"]').click();
  await expect(page.getByText('疑似算法',{exact:true})).toBeVisible();await expect(page.getByText('清理已完成',{exact:true}).last()).toBeVisible();
  await page.locator('[data-external-platform-tab="history"]').click();await page.locator('[data-sync-history-detail]').click();
  await expect(page.locator('.external-sync-operation').last()).toContainText('产品分页不完整');
  await page.evaluate(()=>window.closeModal());
  const asset={id:'a',name:'疑似算法',source_type:'EXTERNAL',provider_type:'CHANG_LIAN',external_active:true,external_deletion_status:'SUSPECTED_DELETED',external_deletion_reason:'列表缺少，待重新核实',external_master_data_digest:'digest',external_analyses:[{analysis_id:'analysis',analysis_type:'1',status:'1'}],versions:[]};
  await page.route('**/api/v12/projects/*/algorithms',route=>json(route,{items:[asset]}));
  await page.route('**/api/projects/*/jobs',route=>json(route,[{id:'existing-task',algorithm_id:'a',status:'running'}]));
  await page.evaluate(async()=>{await window.setPage('算法列表');await window.AlgorithmListRuntime.refresh({render:true});});
  const card=page.locator('[data-algorithm-id="a"]');
  await expect(card.locator('[data-external-deletion="SUSPECTED_DELETED"]')).toContainText('待核实');
  await expect(card.locator('[data-algorithm-train="a"]')).toBeEnabled();
  await card.getByRole('button',{name:'详情',exact:true}).click();
  await expect(page.locator('[data-external-algorithm-detail]')).toContainText('已有任务继续；新发布暂缓');
  await page.locator('[data-algorithm-cleanup-detail]').click();
  await expect(page.locator('[data-cleanup-modal-root]').last()).toContainText('待核实');
});

test('P0 manual sync HTTP failure and hanging request restore original button and preserve cache',async({page,request})=>{
  const {json}=await prepareCleanupPlatform(page,request,[]);
  await page.route('**/external-algorithm-platform/sync?*',route=>json(route,{message:'上游分页失败'},502));
  const sync=page.locator('#externalPlatformSync');
  await sync.click();await expect(sync).toBeEnabled();await expect(page.locator('#externalSyncOperation')).toContainText('上游分页失败');
  let requestSeen;const started=new Promise(resolve=>{requestSeen=resolve});
  await page.route('**/external-algorithm-platform/sync?*',async route=>{requestSeen();await new Promise(()=>{});});
  await page.clock.install();
  await sync.click();await started;await expect(sync).toHaveAttribute('aria-busy','true');
  await page.clock.fastForward(31000);
  await expect(sync).toBeEnabled();await expect(sync).toHaveAttribute('aria-busy','false');await expect(page.locator('#externalSyncOperation')).toContainText('超时');
  await expect(page.locator('[data-external-platform-page]')).toBeVisible();
  let statusReads=0;
  await page.route('**/external-algorithm-platform/sync-operation?*',async route=>{
    statusReads+=1;
    if(statusReads===1) return json(route,{operation:{operation_id:'still-running',status:'running',current_phase:'fetch_products',processed_products:1,total_products:5}});
    await new Promise(()=>{});
  });
  await page.locator('[data-sync-refresh]').click();
  await expect(page.locator('#externalSyncOperation')).toContainText('正在同步');
  await page.clock.fastForward(1000);
  await expect.poll(()=>statusReads).toBe(2);
  await page.clock.fastForward(31000);
  await expect(page.locator('#externalSyncOperation')).toContainText('暂无法读取同步状态');
  await expect(page.locator('#externalSyncOperation')).toContainText('正在同步');
  await expect(page.locator('#externalSyncOperation')).not.toContainText('同步失败');
  await expect(page.locator('[data-sync-refresh]')).toBeEnabled();
  await page.unroute('**/external-algorithm-platform/sync-operation?*');
  await page.route('**/external-algorithm-platform/sync-operation?*',route=>route.fulfill({status:200,contentType:'application/json',body:'{broken JSON'}));
  await page.locator('[data-sync-refresh]').click();
  await expect(page.locator('#externalSyncOperation')).toContainText('JSON 解析失败');
  await expect(page.locator('#externalSyncOperation')).toContainText('正在同步');
  await expect(page.locator('[data-sync-refresh]')).toBeEnabled();
  await expect(page.locator('[data-sync-refresh]')).toHaveAttribute('aria-busy','false');
});


test('P0 cleanup pagination stays bounded and old project detail cannot fill the current modal',async({page,request})=>{
  const operations=Array.from({length:26},(_,i)=>({operation_id:`suspect:${i}`,algorithm_id:`${i}`,algorithm_name:`核实算法${i}`,state:'SUSPECTED_DELETED',phase:'verification_required',counts:{processed:0,total:1}}));
  const {json}=await prepareCleanupPlatform(page,request,operations);
  await expect(page.locator('[data-cleanup-detail]')).toHaveCount(25);await expect(page.getByText('核实算法25',{exact:true})).toHaveCount(0);
  await page.locator('[data-cleanup-page="25"]').click();await expect(page.locator('[data-cleanup-detail]')).toHaveCount(1);await expect(page.getByText('核实算法25',{exact:true})).toBeVisible();
  let release,begin;const started=new Promise(resolve=>{begin=resolve});
  await page.route('**/cleanup-operations/suspect%3A25?*',async route=>{begin();await new Promise(resolve=>{release=resolve});await json(route,{operation:{...operations[25],algorithm_name:'旧项目迟到内容'}});});
  await page.locator('[data-cleanup-detail="suspect:25"]').click();await started;
  await page.evaluate(()=>{state.project={...state.project,id:'different-project'};});release();
  await expect(page.locator('[data-cleanup-modal-root]')).not.toContainText('旧项目迟到内容');
  await page.evaluate(()=>window.closeModal());
});

test('P0 sync rendering faults release original busy state before another real click',async({page,request})=>{
  const {json}=await prepareCleanupPlatform(page,request,[]);
  let posts=0;
  await page.route('**/external-algorithm-platform/sync?*',route=>{posts+=1;return json(route,{operation:{operation_id:`sync-${posts}`,status:'success',current_phase:'completed',counts:{added:0,updated:0}}});});
  await page.evaluate(()=>{
    window.__cleanupOriginalGet=document.getElementById;
    let once=true;
    document.getElementById=function(id){if(id==='externalSyncOperation'&&once){once=false;throw new Error('injected initial sync paint failure');}return window.__cleanupOriginalGet.call(this,id);};
  });
  const sync=page.locator('#externalPlatformSync');
  await sync.click();
  await page.evaluate(()=>{document.getElementById=window.__cleanupOriginalGet;});
  await expect(sync).toBeEnabled();await expect(sync).toHaveAttribute('aria-busy','false');
  await sync.click();await expect.poll(()=>posts).toBe(1);
  await expect(sync).toBeEnabled();
  await page.evaluate(()=>{
    let reads=0;window.__syncFinalPaintFailed=false;
    document.getElementById=function(id){if(id==='externalSyncOperation'&&++reads===4){window.__syncFinalPaintFailed=true;throw new Error('injected final sync paint failure');}return window.__cleanupOriginalGet.call(this,id);};
  });
  await sync.click();await expect.poll(()=>posts).toBe(2);
  await expect.poll(()=>page.evaluate(()=>window.__syncFinalPaintFailed)).toBe(true);
  await page.evaluate(()=>{document.getElementById=window.__cleanupOriginalGet;});
  await expect(sync).toBeEnabled();await expect(sync).toHaveAttribute('aria-busy','false');
  await sync.click();await expect.poll(()=>posts).toBe(3);await expect(sync).toBeEnabled();
});
