import {test, expect} from '@playwright/test';

async function seedProject(request) {
  const project = await (await request.post('/api/projects', {data: {
    name: `首次训练弹窗-${Date.now()}`,
    labels: [{code: 'smoke', display_name: '烟雾'}],
  }})).json();
  const created = await (await request.post(`/api/v12/projects/${project.id}/algorithms`, {data: {
    name: '首次打开配置回归',
    industry: '测试',
    algorithm_type: 'yolo_ultralytics',
    remark: '',
  }})).json();
  return {project, algorithmId: created.algorithm.id};
}

test('hard refresh first training open hydrates configuration before showing the dialog', async ({page, request}) => {
  const {project} = await seedProject(request);
  let trainingOptionsCalls = 0;
  let recommendationCalls = 0;

  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const response = await route.fetch();
    const snapshot = await response.json();
    snapshot.targets = [{id: 'stale-ready-target', name: '未完成配置', status: 'ready'}];
    snapshot.recommendation = null;
    await route.fulfill({response, json: snapshot});
  });
  await page.route('**/api/training_options**', route => {
    trainingOptionsCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({targets: [{
        id: 'first-open-ultralytics',
        name: '首次打开 Ultralytics',
        type: 'local',
        framework: 'ultralytics',
        status: 'ready',
        algorithms: [{
          key: 'yolo_detect',
          name: 'Ultralytics Detect',
          base_model: 'yolo11n.pt',
          default_epochs: 20,
          default_imgsz: 640,
          default_batch: 4,
        }],
        base_models: [{value: 'yolo11n.pt', label: 'YOLO11n'}],
      }]})
    });
  });
  await page.route('**/api/system/recommendation', route => {
    recommendationCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({device: 'cpu', batch: 4, workers: 0}),
    });
  });
  await page.route('**/api/v62/training-devices', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({recommended: 'cpu', options: [{id: 'cpu', label: 'CPU', available: true}]}),
  }));

  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '算法列表'}));
  }, project.id);

  await page.goto('/');
  await expect.poll(async () => page.evaluate(() => window.TrainingCreateHydrationRuntime?.build || null))
    .toBe('training-create-hydration-422532');

  // Reproduce the user's actual sequence: refresh, then open the training dialog once.
  await page.reload();
  await expect.poll(async () => page.evaluate(() => window.TrainingCreateHydrationRuntime?.build || null))
    .toBe('training-create-hydration-422532');
  await expect.poll(async () => page.evaluate(() => state.uiReady === true)).toBe(true);
  expect(await page.evaluate(() => ({
    targetId: state.targets?.[0]?.id,
    hasAlgorithms: Array.isArray(state.targets?.[0]?.algorithms),
    recommendation: state.rec,
  }))).toEqual({
    targetId: 'stale-ready-target',
    hasAlgorithms: false,
    recommendation: null,
  });

  const beforeOptions = trainingOptionsCalls;
  const beforeRecommendation = recommendationCalls;
  const card = page.locator('.alg428-card', {hasText: '首次打开配置回归'});
  await card.getByRole('button', {name: '训练'}).click();

  const dialog = page.getByRole('dialog', {name: '训练 · 首次打开配置回归'});
  await expect(dialog).toBeVisible({timeout: 10_000});
  await expect(dialog.locator('#tr429Target')).toHaveValue('first-open-ultralytics');
  await expect(dialog.locator('#tr429Target')).toContainText('首次打开 Ultralytics');
  await expect(dialog.locator('#tr429Alg')).toHaveValue('yolo_detect');
  await expect(dialog.locator('#tr429Model')).toHaveText('yolo11n.pt');

  expect(trainingOptionsCalls).toBe(beforeOptions + 1);
  expect(recommendationCalls).toBe(beforeRecommendation + 1);
  expect(await page.evaluate(() => ({
    targetId: state.targets?.[0]?.id,
    algorithmKey: state.targets?.[0]?.algorithms?.[0]?.key,
    model: state.targets?.[0]?.base_models?.[0]?.value,
    recommendationDevice: state.rec?.device,
  }))).toEqual({
    targetId: 'first-open-ultralytics',
    algorithmKey: 'yolo_detect',
    model: 'yolo11n.pt',
    recommendationDevice: 'cpu',
  });
});
