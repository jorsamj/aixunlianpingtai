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

  await page.route(`**/api/v47/projects/${project.id}/ai-label-tasks/fake-task/result`, route => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({
      status: 'awaiting_confirmation',
      task: {id: 'fake-task', status: 'awaiting_confirmation'},
      result: {labels: ['fire'], items: [{
        image_id: image.id,
        filename: image.filename,
        url: image.url,
        status: 'success',
        boxes: [{label: 'fire', confidence: 0.95, x1: 10, y1: 8, x2: 90, y2: 70}]
      }]}
    })
  }));
  await page.evaluate(() => window.reviewAiLabel427('fake-task'));
  const candidateDialog = page.getByRole('dialog', {name: /AI标注结果确认/});
  await expect(candidateDialog.getByText(/确认后才写入正式标注/)).toBeVisible();
  await expect(candidateDialog.locator('.ai-candidate-box')).toBeVisible();
  await expect(candidateDialog.getByRole('button', {name: /确认写入标注/})).toBeVisible();
  await candidateDialog.getByRole('button', {name: /暂不应用/}).click();

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
  await createDialog.getByRole('button', {name: '取消'}).click();
  await historyDialog.locator('button[aria-label="关闭"]').click();
  await page.evaluate(() => window.setPage('部署转换'));
  await expect(page.locator('.deploy-target-card', {hasText: '瑞芯微 RKNN'})).toBeVisible();
  await page.locator('.deploy-target-card', {hasText: '瑞芯微 RKNN'}).click();
  await expect(page.locator('.deploy-resource-readiness')).toContainText('Windows RKNN-Toolkit2');
});
