import {test, expect} from '@playwright/test';

test('algorithm cards expand locally and focused refresh avoids full bootstrap reload', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('算法列表'));
  await expect(page.locator('#title')).toContainText('算法列表');
  await expect(page.locator('#alg412List')).toBeVisible({timeout: 10_000});

  await expect.poll(async () => page.evaluate(() => window.AlgorithmListRuntime?.build || null))
    .toBe('algorithm-list-runtime-422504');
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady) && !state.__extras412))
    .toBe(true);

  await page.evaluate(() => {
    state.algorithms = [{
      id: 'algo-perf-1',
      name: '性能验收算法',
      remark: '用于算法列表浏览器性能验收',
      industry: '测试',
      algorithm_type: 'yolo_ultralytics',
      versions: [{
        id: 'version-perf-1',
        version_name: '20260911140000',
        training_status: 'done',
        status: 'done',
        model_name: 'best.pt',
        stored_path: '/tmp/best.pt',
        created_at: '2026-09-11T14:00:00Z',
        report: {metrics: {map50: 0.88}},
      }],
    }];
    state.jobs = [];
    state.alg428Expanded = {};
    window.renderAlgorithms423();
  });

  const apiRequests = [];
  const onRequest = request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) apiRequests.push(`${request.method()} ${url.pathname}${url.search}`);
  };
  page.on('request', onRequest);

  const card = page.locator('.alg428-card').filter({hasText: '性能验收算法'});
  await expect(card).toBeVisible();
  await card.locator('.alg428-main').click();
  await expect(card).toHaveClass(/open/);
  await expect(card.locator('.alg428-version-row')).toHaveCount(1);
  await page.waitForTimeout(250);

  let owned = apiRequests.filter(row => row.includes('/algorithms') || row.includes('/bootstrap/snapshot'));
  expect(owned).toEqual([]);

  await card.locator('.alg428-main').click();
  await expect(card).not.toHaveClass(/open/);
  await page.waitForTimeout(150);
  owned = apiRequests.filter(row => row.includes('/algorithms') || row.includes('/bootstrap/snapshot'));
  expect(owned).toEqual([]);

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);

  await page.route(`**/api/v12/projects/${encoded}/algorithms`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 'algo-perf-1',
        name: '性能验收算法-已刷新',
        remark: 'focused refresh',
        industry: '测试',
        algorithm_type: 'yolo_ultralytics',
        versions: [],
      }]}),
    });
  });
  await page.route(`**/api/projects/${encoded}/jobs`, async route => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([{id: 'job-perf-1', status: 'running', algorithm_asset_id: 'algo-perf-1'}]),
    });
  });

  apiRequests.length = 0;
  await page.locator('#refreshBtn').click();
  await expect.poll(async () => page.evaluate(() => window.AlgorithmListRuntime?.state?.().inflight ?? null))
    .toBe(false);
  await expect(page.locator('#alg412List')).toContainText('性能验收算法-已刷新');

  const algorithmRequests = apiRequests.filter(row => row.includes(`/api/v12/projects/${projectId}/algorithms`));
  const jobRequests = apiRequests.filter(row => row.includes(`/api/projects/${projectId}/jobs`));
  expect(algorithmRequests).toEqual([`GET /api/v12/projects/${projectId}/algorithms`]);
  expect(jobRequests).toEqual([`GET /api/projects/${projectId}/jobs`]);
  expect(apiRequests.some(row => row.includes('/bootstrap/snapshot'))).toBe(false);
  expect(pageErrors).toEqual([]);
});

test('algorithm version deletion uses focused refresh without full reload', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('算法列表'));
  await expect(page.locator('#alg412List')).toBeVisible({timeout: 10_000});

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  await page.route(`**/api/v12/projects/${encoded}/algorithms/algo-version-delete/versions/version-delete-1`, async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
  });
  await page.route(`**/api/v12/projects/${encoded}/algorithms`, async route => {
    if (route.request().method() !== 'GET') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 'algo-version-delete',
        name: '版本删除验收算法',
        remark: 'R20 behavior baseline',
        industry: '测试',
        algorithm_type: 'yolo_ultralytics',
        versions: [],
      }]}),
    });
  });
  await page.route(`**/api/projects/${encoded}/jobs`, async route => {
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify([])});
  });

  await page.evaluate(() => {
    state.algorithms = [{
      id: 'algo-version-delete',
      name: '版本删除验收算法',
      remark: 'R20 behavior baseline',
      industry: '测试',
      algorithm_type: 'yolo_ultralytics',
      versions: [{
        id: 'version-delete-1',
        version_name: '20260912100000',
        model_name: 'best.pt',
        size_mb: 5.2,
        created_at: '2026-09-12T10:00:00Z',
      }],
    }];
    state.jobs = [];
    window.renderAlgorithms423();
    window.viewAlgorithm423('algo-version-delete');
  });

  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalBody')).toContainText('20260912100000');
  page.once('dialog', dialog => dialog.accept());
  await page.locator('#modalBody').getByRole('button', {name: '删除版本'}).click();

  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#alg412List')).toContainText('版本删除验收算法');
  await expect(page.locator('#alg412List')).not.toContainText('20260912100000');

  const deleteRequest = `DELETE /api/v12/projects/${projectId}/algorithms/algo-version-delete/versions/version-delete-1`;
  const algorithmRequest = `GET /api/v12/projects/${projectId}/algorithms`;
  const jobRequest = `GET /api/projects/${projectId}/jobs`;
  expect(requests.filter(row => row === deleteRequest)).toEqual([deleteRequest]);
  expect(requests.filter(row => row === algorithmRequest)).toEqual([algorithmRequest]);
  expect(requests.filter(row => row === jobRequest)).toEqual([jobRequest]);

  const forbiddenFullReloadRequests = requests.filter(row => {
    const path = row.slice(row.indexOf(' ') + 1).split('?')[0];
    return path === '/api/projects'
      || path === `/api/projects/${projectId}`
      || path.startsWith(`/api/projects/${projectId}/datasets`)
      || path.startsWith(`/api/projects/${projectId}/images`)
      || path.startsWith(`/api/v12/projects/${projectId}/labels`)
      || path.startsWith(`/api/v12/projects/${projectId}/publish/pending`)
      || path.startsWith(`/api/v12/projects/${projectId}/test_models`)
      || path === '/api/training_options'
      || path === '/api/v16/inference_envs'
      || path === '/api/system/recommendation'
      || path === '/api/local_models'
      || path.includes('/bootstrap/snapshot');
  });
  expect(forbiddenFullReloadRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('publishing a pending model as an algorithm version keeps the live publish flow functional', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('测试发布'));
  await expect(page.locator('#title')).toContainText('测试发布');

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  let submittedBody = null;
  await page.route(`**/api/v12/projects/${encoded}/algorithms/algo-publish-r20b/versions`, async route => {
    submittedBody = route.request().postDataJSON();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        version: {
          id: 'version-publish-r20b',
          version_name: '20260912143000',
          model_name: 'publish-r20b.pt',
          model_key: 'project::publish-r20b.pt',
          size_mb: 8.5,
          created_at: '2026-09-12T14:30:00Z',
        },
      }),
    });
  });

  await page.evaluate(() => {
    state.algorithms = [{
      id: 'algo-publish-r20b',
      name: '发布验收算法',
      remark: 'R20b publish baseline',
      industry: '测试',
      algorithm_type: 'yolo_ultralytics',
      versions: [],
    }];
    state.pending = [{
      name: 'publish-r20b.pt',
      model_key: 'project::publish-r20b.pt',
      type: 'pt',
      framework: 'ultralytics',
      size_mb: 8.5,
      job_id: 'job-publish-r20b',
      job_name: 'R20b publish baseline',
    }];
    window.assignVersion('publish-r20b.pt');
  });

  await expect(page.locator('#modal')).not.toHaveClass(/hidden/);
  await expect(page.locator('#modalBody input[disabled]').first()).toHaveValue('publish-r20b.pt');
  await expect(page.locator('#algoSel')).toHaveValue('algo-publish-r20b');
  await page.locator('#verName').fill('R20B-PUBLISH');
  await page.locator('#verRemark').fill('发布行为基线');
  await expect.poll(async () => page.evaluate(() => !state.__extras412)).toBe(true);
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });
  await page.locator('#modalBody').getByRole('button', {name: '发布为算法版本'}).click();

  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#toast')).toContainText('已发布为算法版本');
  expect(submittedBody).toMatchObject({
    model_name: 'publish-r20b.pt',
    model_source: 'project',
    version_name: 'R20B-PUBLISH',
    remark: '发布行为基线',
    job_id: 'job-publish-r20b',
  });
  await expect.poll(async () => page.evaluate(() => state.algorithms.find(x => x.id === 'algo-publish-r20b')?.versions?.[0]?.id || null)).toBe('version-publish-r20b');
  await expect.poll(async () => page.evaluate(() => state.pending.some(x => x.name === 'publish-r20b.pt'))).toBe(false);
  const publishRequest = `POST /api/v12/projects/${projectId}/algorithms/algo-publish-r20b/versions`;
  expect(requests.filter(row => row === publishRequest)).toEqual([publishRequest]);
  const forbiddenReloadRequests = requests.filter(row => {
    const path = row.slice(row.indexOf(' ') + 1).split('?')[0];
    return path === '/api/projects'
      || path === `/api/projects/${projectId}`
      || path.startsWith(`/api/projects/${projectId}/datasets`)
      || path.startsWith(`/api/projects/${projectId}/images`)
      || path.startsWith(`/api/projects/${projectId}/jobs`)
      || path.startsWith(`/api/projects/${projectId}/models`)
      || path.startsWith(`/api/v12/projects/${projectId}/labels`)
      || path.startsWith(`/api/v12/projects/${projectId}/algorithms`) && path !== `/api/v12/projects/${projectId}/algorithms/algo-publish-r20b/versions`
      || path.startsWith(`/api/v12/projects/${projectId}/publish/pending`)
      || path.startsWith(`/api/v12/projects/${projectId}/test_models`)
      || path === '/api/training_options'
      || path === '/api/v16/inference_envs'
      || path === '/api/system/recommendation'
      || path === '/api/local_models'
      || path.includes('/bootstrap/snapshot');
  });
  expect(forbiddenReloadRequests).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('algorithm create edit delete uses authoritative local state without broad refresh', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('算法列表'));
  await expect(page.locator('#alg412List')).toBeVisible({timeout: 10_000});
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady) && !state.__extras412)).toBe(true);

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  const requests = [];
  page.on('request', request => {
    const url = new URL(request.url());
    if (url.pathname.startsWith('/api/')) requests.push(`${request.method()} ${url.pathname}${url.search}`);
  });

  await page.route(`**/api/v12/projects/${encoded}/algorithms`, async route => {
    if (route.request().method() !== 'POST') return route.continue();
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({algorithm: {
        id: 'algo-r20h-crud',
        name: 'R20h 创建算法',
        remark: 'create local state',
        industry: '测试',
        algorithm_type: 'yolo_ultralytics',
        versions: [],
      }}),
    });
  });
  await page.route(`**/api/v12/projects/${encoded}/algorithms/algo-r20h-crud`, async route => {
    if (route.request().method() === 'PUT') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({algorithm: {
          id: 'algo-r20h-crud',
          name: 'R20h 已编辑算法',
          remark: 'edit local state',
          industry: '测试',
          algorithm_type: 'yolo_ultralytics',
          versions: [],
        }}),
      });
    }
    if (route.request().method() === 'DELETE') {
      return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true})});
    }
    return route.continue();
  });

  await page.locator('[data-action="algorithm.create"]').click();
  await expect(page.locator('#alg414Name')).toBeVisible();
  await page.locator('#alg414Name').fill('R20h 创建算法');
  await page.locator('#alg414Industry').fill('测试');
  await page.locator('#alg414Remark').fill('create local state');
  await page.locator('#alg414Save').click();
  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#alg412List')).toContainText('R20h 创建算法');
  await expect.poll(async () => page.evaluate(() => state.algorithms.some(x => x.id === 'algo-r20h-crud'))).toBe(true);

  const card = page.locator('.alg428-card').filter({hasText: 'R20h 创建算法'});
  await card.getByRole('button', {name: '编辑'}).click();
  await expect(page.locator('#alg414EditName')).toHaveValue('R20h 创建算法');
  await page.locator('#alg414EditName').fill('R20h 已编辑算法');
  await page.locator('#modalBody').getByRole('button', {name: '保存'}).click();
  await expect(page.locator('#modal')).toHaveClass(/hidden/);
  await expect(page.locator('#alg412List')).toContainText('R20h 已编辑算法');

  page.once('dialog', dialog => dialog.accept());
  const editedCard = page.locator('.alg428-card').filter({hasText: 'R20h 已编辑算法'});
  await editedCard.getByRole('button', {name: '删除'}).click();
  await expect(page.locator('#alg412List')).not.toContainText('R20h 已编辑算法');
  await expect.poll(async () => page.evaluate(() => state.algorithms.some(x => x.id === 'algo-r20h-crud'))).toBe(false);

  const expected = [
    `POST /api/v12/projects/${projectId}/algorithms`,
    `PUT /api/v12/projects/${projectId}/algorithms/algo-r20h-crud`,
    `DELETE /api/v12/projects/${projectId}/algorithms/algo-r20h-crud`,
  ];
  for (const row of expected) expect(requests.filter(x => x === row)).toEqual([row]);

  const forbiddenBroadRefresh = requests.filter(row => {
    if (expected.includes(row)) return false;
    const [method, rawPath] = row.split(' ', 2);
    const pathOnly = rawPath.split('?')[0];
    if (method !== 'GET') return false;
    return pathOnly === '/api/projects'
      || pathOnly === `/api/projects/${projectId}`
      || pathOnly.startsWith(`/api/projects/${projectId}/datasets`)
      || pathOnly.startsWith(`/api/projects/${projectId}/images`)
      || pathOnly.startsWith(`/api/projects/${projectId}/jobs`)
      || pathOnly.startsWith(`/api/v12/projects/${projectId}/labels`)
      || pathOnly.startsWith(`/api/v12/projects/${projectId}/algorithms`)
      || pathOnly.includes('/bootstrap/snapshot');
  });
  expect(forbiddenBroadRefresh).toEqual([]);
  expect(pageErrors).toEqual([]);
});


test('algorithm version exposes persisted training lineage without job refetch', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(async () => page.evaluate(() => window.AlgorithmListRuntime?.build || null))
    .toBe('algorithm-list-runtime-422504');
  await expect.poll(async () => page.evaluate(() => Boolean(state.uiReady) && !state.__extras412))
    .toBe(true);

  const projectId = await page.evaluate(() => state.project?.id);
  expect(projectId).toBeTruthy();
  const encoded = encodeURIComponent(projectId);
  const lineageAlgorithm = {
    id:'algo-lineage-1',name:'溯源验收算法',industry:'测试',
    algorithm_type:'yolo_ultralytics',current_version_id:'version-lineage-1',
    versions:[{
      id:'version-lineage-1',version_name:'20260919103000',training_status:'SUCCEEDED',
      model_name:'best.pt',stored_path:'/models/best.pt',created_at:'2026-09-19T10:30:00Z',
      training_lineage:{
        schema_version:1,task_id:'train-lineage-1',dataset_revision_id:'a'.repeat(64),
        snapshot_id:'b'.repeat(64),framework:'ultralytics',
        base:{model:'yolo11n.pt',selection_reason:'mother_model'},
        execution:{mode:'agent',worker_id:'agent:node-7',node_id:'node-7',execution_generation:4,actual_device:'cuda:0'},
        parameters:{actual:{epochs:30,batch:4,imgsz:640}},
        artifacts:[{role:'best',file_name:'best.pt',sha256:'c'.repeat(64),size_bytes:1234}],
      },
      evaluation:{
        schema_version:1,evaluation_id:'d'.repeat(64),status:'succeeded',
        task_id:'train-lineage-1',dataset_revision_id:'a'.repeat(64),snapshot_id:'b'.repeat(64),
        model_sha256:'c'.repeat(64),image_count:12,
        metrics:{'metrics/precision(B)':0.82,'metrics/recall(B)':0.70,'metrics/mAP50(B)':0.76,'metrics/mAP50-95(B)':0.55},
        per_class:[{class_id:0,label:'smoke',precision:0.82,recall:0.70,map50:0.76,map50_95:0.55,true_positive:7,false_positive:2,false_negative:3}],
        weak_labels:['smoke'],
        error_samples:[{image:'test-smoke.jpg',fp_count:2,fn_count:3,fp_labels:['smoke'],fn_labels:['smoke']}],
        protocol:{mode:'blind_image_only_inference_then_hidden_ground_truth_scoring',operating_conf:0.25,matching_iou:0.5},
      },
      iteration_decision:{
        schema_version:1,decision_id:'e'.repeat(64),evaluation_id:'d'.repeat(64),
        decision:'needs_data',
        quality_gate:{metric:'map50',metric_key:'metrics/mAP50(B)',metric_value:0.76,continue_threshold:0.65,stop_threshold:0.90},
        weak_labels:['smoke'],
        signals:{false_positive:2,false_negative:3,error_sample_count:1},
        reason_codes:['weak_labels_present'],
        recommended_actions:['supplement_weak_label_data','review_fp_fn_samples'],
        automatic_execution:false,requires_confirmation:true,
      },
    }],
  };

  await page.route(`**/api/v12/projects/${encoded}/algorithms`, async route => {
    await route.fulfill({
      status:200,contentType:'application/json',
      body:JSON.stringify({items:[lineageAlgorithm]}),
    });
  });
  await page.route(`**/api/projects/${encoded}/jobs`, async route => {
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify([])});
  });
  await page.route(`**/api/v63/projects/${encoded}/algorithms/algo-lineage-1/versions/version-lineage-1/supplement-data-candidates`, async route => {
    if(route.request().method()!=='GET')return route.continue();
    await route.fulfill({
      status:200,contentType:'application/json',
      body:JSON.stringify({
        ok:true,action_id:'f'.repeat(64),total:0,returned:0,truncated:false,
        eligible:0,annotation_required:0,candidate_set:null,items:[],
      }),
    });
  });

  await page.evaluate(() => window.setPage('算法列表'));
  await expect(page.locator('#alg412List')).toBeVisible({timeout: 10_000});
  await page.evaluate(async () => {
    await window.AlgorithmListRuntime.refresh({render:false});
    state.alg428Expanded = {};
    window.renderAlgorithms423();
  });

  const card=page.locator('.alg428-card').filter({hasText:'溯源验收算法'});
  await expect(card).toBeVisible();
  await card.locator('.alg428-main').click();
  await expect(card).toHaveClass(/open/);
  await expect(card.getByRole('button',{name:'训练溯源'})).toBeVisible();

  let confirmedActionBody=null;
  const persistedAction={
    schema_version:1,action_id:'f'.repeat(64),action:'supplement_data',status:'confirmed',
    source:{decision_id:'e'.repeat(64),evaluation_id:'d'.repeat(64),algorithm_id:'algo-lineage-1',
      version_id:'version-lineage-1',dataset_revision_id:'a'.repeat(64),snapshot_id:'b'.repeat(64)},
    weak_labels:['smoke'],automatic_execution:false,requires_user_submit:false,confirmed_at:'2026-09-19T05:10:00Z',
    data_draft:{weak_labels:['smoke'],problem_samples:[{image:'test-smoke.jpg',fp_count:2,fn_count:3}],
      dataset_revision_id:'a'.repeat(64),snapshot_id:'b'.repeat(64)},
  };
  await page.route(`**/api/v12/projects/${encoded}/algorithms/algo-lineage-1/versions/version-lineage-1/iteration-actions/confirm`, async route=>{
    confirmedActionBody=route.request().postDataJSON();
    lineageAlgorithm.versions[0].confirmed_iteration_action=persistedAction;
    await route.fulfill({
      status:200,contentType:'application/json',
      body:JSON.stringify({ok:true,action:persistedAction}),
    });
  });
  const requests=[];
  page.on('request',request=>{
    const url=new URL(request.url());
    if(url.pathname.startsWith('/api/'))requests.push(url.pathname);
  });
  await card.getByRole('button',{name:'训练溯源'}).click();
  await expect(page.locator('#modalBody')).toContainText('数据版本');
  await expect(page.locator('#modalBody')).toContainText('train-lineage-1');
  await expect(page.locator('#modalBody')).toContainText('node-7');
  await expect(page.locator('#modalBody')).toContainText('yolo11n.pt');
  await expect(page.locator('#modalBody')).toContainText('实际训练参数');
  await page.evaluate(() => closeModal());
  await card.getByRole('button',{name:'独立评测'}).click();
  await expect(page.locator('#modalBody')).toContainText('冻结 Test Split');
  await expect(page.locator('#modalBody')).toContainText('mAP50');
  await expect(page.locator('#modalBody')).toContainText('smoke');
  await expect(page.locator('#modalBody')).toContainText('test-smoke.jpg');
  await expect(page.locator('#modalBody')).toContainText('FP / FN');
  await expect(page.locator('#modalBody')).toContainText('迭代决策');
  await expect(page.locator('#modalBody')).toContainText('需补充数据');
  await expect(page.locator('#modalBody')).toContainText('补充弱标签数据');
  await expect(page.locator('#modalBody')).toContainText('系统仅给出建议，不会自动发起下一次训练');
  await expect(page.locator('#modalBody').getByRole('button',{name:'确认准备补数据'})).toBeVisible();
  await page.locator('#modalBody').getByRole('button',{name:'确认准备补数据'}).click();
  await expect.poll(()=>confirmedActionBody).toEqual({
    decision_id:'e'.repeat(64),action:'supplement_data',
  });
  await expect.poll(async()=>page.evaluate(()=>state.iterationDataDraft?.weak_labels||[])).toEqual(['smoke']);
  expect(requests.filter(path=>path.includes('/train/start'))).toEqual([]);

  // Simulate a fresh UI state: the draft must be recoverable from persisted
  // version truth without confirming the action a second time.
  await page.evaluate(async()=>{
    state.iterationDataDraft=null;
    window.setPage('算法列表');
    await window.AlgorithmListRuntime.refresh({render:false});
    state.alg428Expanded={};
    window.renderAlgorithms423();
  });
  const refreshed=page.locator('.alg428-card').filter({hasText:'溯源验收算法'});
  await refreshed.locator('.alg428-main').click();
  await refreshed.getByRole('button',{name:'独立评测'}).click();
  await expect(page.locator('#modalBody')).toContainText('已确认：补数据');
  await expect(page.locator('#modalBody').getByRole('button',{name:'继续补数据'})).toBeVisible();
  const confirmCallsBefore=requests.filter(path=>path.includes('/iteration-actions/confirm')).length;
  await page.locator('#modalBody').getByRole('button',{name:'继续补数据'}).click();
  await expect.poll(async()=>page.evaluate(()=>state.iterationDataDraft?.weak_labels||[])).toEqual(['smoke']);
  expect(requests.filter(path=>path.includes('/iteration-actions/confirm')).length).toBe(confirmCallsBefore);
  expect(requests.filter(path=>path.includes('/train/start'))).toEqual([]);
  expect(requests.filter(path=>path.includes('/jobs/'))).toEqual([]);
  expect(pageErrors).toEqual([]);
});
