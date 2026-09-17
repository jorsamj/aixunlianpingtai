import {test, expect} from '@playwright/test';

function bmp(width = 40, height = 30, rgb = [42, 120, 210]) {
  const rowBytes = Math.ceil(width * 3 / 4) * 4;
  const pixelBytes = rowBytes * height;
  const buffer = Buffer.alloc(54 + pixelBytes);
  buffer.write('BM', 0, 'ascii');
  buffer.writeUInt32LE(buffer.length, 2);
  buffer.writeUInt32LE(54, 10);
  buffer.writeUInt32LE(40, 14);
  buffer.writeInt32LE(width, 18);
  buffer.writeInt32LE(height, 22);
  buffer.writeUInt16LE(1, 26);
  buffer.writeUInt16LE(24, 28);
  buffer.writeUInt32LE(pixelBytes, 34);
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      const offset = 54 + y * rowBytes + x * 3;
      buffer[offset] = rgb[2];
      buffer[offset + 1] = rgb[1];
      buffer[offset + 2] = rgb[0];
    }
  }
  return buffer;
}

async function createProject(request) {
  const response = await request.post('/api/projects', {data: {name: `分批上传-${Date.now()}`, labels: []}});
  expect(response.ok()).toBeTruthy();
  return response.json();
}

test('65 browser-selected images upload as two sequential server-confirmed chunks', async ({page, request}) => {
  const project = await createProject(request);
  await page.addInitScript(id => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId: id, page: '数据集'}));
  }, project.id);

  const uploadRequests = [];
  let active = 0;
  let maxActive = 0;
  page.on('request', req => {
    const url = new URL(req.url());
    if (req.method() === 'POST' && url.pathname === `/api/projects/${project.id}/images`) {
      uploadRequests.push(req);
      active += 1;
      maxActive = Math.max(maxActive, active);
    }
  });
  page.on('response', response => {
    const req = response.request();
    const url = new URL(req.url());
    if (req.method() === 'POST' && url.pathname === `/api/projects/${project.id}/images`) active -= 1;
  });

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  await page.getByRole('button', {name: '上传'}).click();
  const payloads = Array.from({length: 65}, (_, index) => ({
    name: `chunk-${String(index + 1).padStart(2, '0')}.bmp`,
    mimeType: 'image/bmp',
    buffer: bmp(40, 30, [40 + index % 100, 90, 160]),
  }));
  await page.locator('#up426Images').setInputFiles(payloads);

  const dialog = page.getByRole('dialog', {name: '图片上传'});
  await expect(dialog.getByText('成功上传 65 张')).toBeVisible({timeout: 60_000});
  await expect(dialog.getByText(/服务器已处理 65\/65/)).toBeVisible();
  await expect(dialog.getByText('本次上传 65 张素材')).toBeVisible();
  expect(uploadRequests).toHaveLength(2);
  expect(maxActive).toBe(1);
});
