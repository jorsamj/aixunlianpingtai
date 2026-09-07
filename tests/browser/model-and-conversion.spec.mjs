import {test, expect} from '@playwright/test';


function bmp(width = 128, height = 96) {
  const rowBytes = Math.ceil(width * 3 / 4) * 4;
  const buffer = Buffer.alloc(54 + rowBytes * height);
  buffer.write('BM', 0, 'ascii');
  buffer.writeUInt32LE(buffer.length, 2);
  buffer.writeUInt32LE(54, 10);
  buffer.writeUInt32LE(40, 14);
  buffer.writeInt32LE(width, 18);
  buffer.writeInt32LE(height, 22);
  buffer.writeUInt16LE(1, 26);
  buffer.writeUInt16LE(24, 28);
  buffer.writeUInt32LE(rowBytes * height, 34);
  buffer.fill(120, 54);
  return buffer;
}


test('vision providers, candidate review, and vendor target parameters are explicit', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `模型转换浏览器-${Date.now()}`,
    labels: [{code: 'fire', display_name: '明火'}]
  }})).json();
  const upload = await request.post(`/api/projects/${project.id}/images`, {multipart: {
    dataset_id: 'default', files: {name: 'candidate.bmp', mimeType: 'image/bmp', buffer: bmp()}
  }});
  const image = (await upload.json()).uploaded[0];
  await request.post(`/api/projects/${project.id}/annotations/${image.id}`, {data: {boxes: [{
    class_id: 0, label: 'fire', x1: 10, y1: 8, x2: 90, y2: 70
  }]}});
  const configured = await request.post('/api/v35/model-configs', {data: {
    name: '浏览器默认视觉模型', provider_type: 'ollama', provider_adapter: 'ollama',
    model_kind: 'vlm', detect_url: 'http://127.0.0.1:11434', model_name: 'qwen2.5vl:3b',
    default_for_annotation: true
  }});
  expect(configured.ok()).toBeTruthy();
  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '模型配置'}));
  }, project.id);
  await page.goto('/');

  await page.evaluate(() => window.setPage('模型配置'));
  await page.getByRole('button', {name: /新增模型/}).click();
  const modelDialog = page.getByRole('dialog');
  await expect(modelDialog.locator('#mcProviderAdapter')).toBeVisible();
  await expect(modelDialog.locator('#mcProviderAdapter option')).toHaveText([
    /火山方舟/, /阿里云千问/, /本地 OpenAI/, /Ollama/
  ]);
  await expect(modelDialog.locator('#mcApiKey')).toHaveValue('');
  await expect(modelDialog.locator('#mcAnnPrompt')).toBeVisible();
  await modelDialog.getByRole('button', {name: '取消'}).click();

  await page.evaluate(() => window.setPage('自动标注及清洗'));
  await page.getByRole('button', {name: /创建AI标注任务/}).click();
  const createAiDialog = page.getByRole('dialog', {name: '创建AI自动标注任务'});
  await expect(createAiDialog.getByText('浏览器默认视觉模型', {exact: true})).toBeVisible();
  const keptReferenceNode = await page.evaluate(() => {
    const button = document.querySelector('#ai429RefGrid button');
    button.click();
    return document.querySelector('#ai429RefGrid button') === button;
  });
  expect(keptReferenceNode).toBe(true);
  await expect(createAiDialog.locator('#ai429Labels')).toHaveValue('fire');
  await expect(createAiDialog.locator('#ai417ReferenceLabels')).toContainText('fire · 明火');
  await createAiDialog.getByRole('button', {name: '取消'}).click();

  await page.route(`**/api/v60/projects/${project.id}/annotation-tasks/fake-task/candidates?*`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      total: 1,
      items: [{
        image_id: image.id,
        filename: image.filename,
        url: image.url,
        status: 'success',
        boxes: [{label: 'fire', confidence: 0.95, x1: 10, y1: 8, x2: 90, y2: 70}]
      }]
    })
  }));
  await page.evaluate(() => window.reviewAiLabel427('fake-task'));
  const candidateDialog = page.getByRole('dialog', {name: /AI待确认标注/});
  await expect(candidateDialog.getByText(/不会自动写入正式标注/)).toBeVisible();
  await expect(candidateDialog.locator('.data412-box')).toBeVisible();
  await expect(candidateDialog.getByRole('button', {name: '全部接受'})).toBeVisible();
  await candidateDialog.getByRole('button', {name: '暂不处理'}).click();

  await page.evaluate(() => window.setPage('部署转换'));
  await page.locator('.deploy-target-card', {hasText: '华为 Atlas'}).click();
  await expect(page.locator('#dpSoc')).toBeVisible();
  await page.locator('.deploy-target-card', {hasText: '瑞芯微 RKNN'}).click();
  await expect(page.locator('#dpChip option')).toHaveText(['RK3588', 'RK3568']);
  await page.locator('.deploy-target-card', {hasText: 'NVIDIA TensorRT'}).click();
  await expect(page.locator('#dpTargetEnvironment')).toBeVisible();
});

test('version conversion shows configured compiler resources and their readiness', async ({page, request}) => {
  const project = await (await request.post('/api/projects', {data: {
    name: `转换资源浏览器-${Date.now()}`,
    labels: [{code: 'fire', display_name: '明火'}]
  }})).json();
  const algorithmId = 'algorithm-resource-test';
  const versionId = 'version-resource-test';
  await page.route(`**/api/v42/projects/${project.id}/algorithms/${algorithmId}/versions/${versionId}/deployments`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      algorithm: {id: algorithmId, name: '转换资源算法'},
      version: {id: versionId, version_name: '20260829120000', model_name: 'best.pt', stored_path: 'C:\\models\\best.pt'},
      items: []
    })
  }));
  await page.route('**/api/v39/deploy/resources', route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({items: [
      {id: 'rknn-windows', name: 'Windows RKNN-Toolkit2', kind: 'rockchip', mode: 'local', status: 'missing', targets: [], message: '未检测到 RKNN-Toolkit2；建议配置 Linux/WSL2 或远程转换节点'},
      {id: 'atlas-remote', name: 'Atlas 远程转换节点', kind: 'ascend', mode: 'remote', status: 'unchecked', targets: [], message: '尚未检测远程服务'}
    ]})
  }));
  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '工作台'}));
  }, project.id);
  await page.goto('/');
  await page.evaluate(async () => { if (window.__clInit) await window.__clInit(); });
  await expect(page.getByRole('button', {name: /算法列表/})).toBeVisible();
  await page.evaluate(([aid, vid]) => window.openVersionConvert428(aid, vid), [algorithmId, versionId]);
  const historyDialog = page.getByRole('dialog', {name: '版本转换'});
  await expect(historyDialog).toBeVisible();
  await historyDialog.getByRole('button', {name: '选择转换目标'}).click();
  const createDialog = page.getByRole('dialog', {name: '新建版本转换'});
  await expect(createDialog).toBeVisible();
  await createDialog.locator('input[name="conv428Target"][value="rockchip"]').check();
  await expect(createDialog.locator('.convert428-resource-status')).toContainText('Windows RKNN-Toolkit2');
  await expect(createDialog.locator('.convert428-resource-status')).toContainText('未检测到 RKNN-Toolkit2');
  await expect(createDialog.getByRole('button', {name: '配置部署资源'})).toBeVisible();
  await createDialog.getByRole('button', {name: '取消'}).click();
  await historyDialog.locator('button[aria-label="关闭"]').click();
  await page.evaluate(() => window.setPage('部署转换'));
  await expect(page.locator('.deploy-target-card', {hasText: '瑞芯微 RKNN'})).toBeVisible();
  await page.locator('.deploy-target-card', {hasText: '瑞芯微 RKNN'}).click();
  await expect(page.locator('.deploy-resource-readiness')).toContainText('Windows RKNN-Toolkit2');
});

test('module graph is cache-busted and exposes platform helpers', async ({page, request}) => {
  const main = await request.get('/static/main.mjs');
  expect(await main.text()).toMatch(/\.\/modules\/materials\.js\?v=\d+/);

  await page.goto('/');
  await expect.poll(() => page.evaluate(() => typeof window.PlatformCore?.materials?.labelDisplay)).toBe('function');
});
