import {test, expect} from '@playwright/test';

function crc32(buffer) {
  let crc = 0xffffffff;
  for (const byte of buffer) {
    crc ^= byte;
    for (let bit = 0; bit < 8; bit += 1) crc = (crc >>> 1) ^ (0xedb88320 & -(crc & 1));
  }
  return (crc ^ 0xffffffff) >>> 0;
}

function storedZip(entries) {
  const locals = [];
  const centrals = [];
  let offset = 0;
  for (const [name, raw] of entries) {
    const data = Buffer.isBuffer(raw) ? raw : Buffer.from(raw);
    const filename = Buffer.from(name);
    const crc = crc32(data);
    const local = Buffer.alloc(30 + filename.length);
    local.writeUInt32LE(0x04034b50, 0);
    local.writeUInt16LE(20, 4);
    local.writeUInt16LE(0, 6);
    local.writeUInt16LE(0, 8);
    local.writeUInt32LE(crc, 14);
    local.writeUInt32LE(data.length, 18);
    local.writeUInt32LE(data.length, 22);
    local.writeUInt16LE(filename.length, 26);
    filename.copy(local, 30);
    locals.push(local, data);

    const central = Buffer.alloc(46 + filename.length);
    central.writeUInt32LE(0x02014b50, 0);
    central.writeUInt16LE(20, 4);
    central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8);
    central.writeUInt16LE(0, 10);
    central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(data.length, 20);
    central.writeUInt32LE(data.length, 24);
    central.writeUInt16LE(filename.length, 28);
    central.writeUInt32LE(offset, 42);
    filename.copy(central, 46);
    centrals.push(central);
    offset += local.length + data.length;
  }
  const centralOffset = offset;
  const centralData = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0);
  end.writeUInt16LE(entries.length, 8);
  end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(centralData.length, 12);
  end.writeUInt32LE(centralOffset, 16);
  return Buffer.concat([...locals, centralData, end]);
}

async function createProject(request) {
  const response = await request.post('/api/projects', {data: {name: `ZIP恢复-${Date.now()}`, labels: []}});
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function createSelectingZipJob(request, projectId) {
  const zip = storedZip([
    ['images/train/sample.jpg', Buffer.from('not-decoded-during-scan')],
    ['data.yaml', Buffer.from('train: images/train\nnames: [object]\n')],
  ]);
  const response = await request.post(`/api/v19/projects/${projectId}/datasets/default/import/jobs`, {
    multipart: {file: {name: 'refresh-recovery.zip', mimeType: 'application/zip', buffer: zip}},
  });
  expect(response.ok()).toBeTruthy();
  const body = await response.json();
  expect(body.status).toBe('selecting');
  return body;
}

test('server-persisted ZIP job is restored in upload task center after browser refresh', async ({page, request}) => {
  const project = await createProject(request);
  const job = await createSelectingZipJob(request, project.id);
  expect(job.id).toBeTruthy();

  await page.addInitScript(id => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId: id, page: '数据集'}));
  }, project.id);

  await page.goto('/');
  await page.getByRole('button', {name: /数据集/}).click();
  const taskCenter = page.locator('#uploadTaskCenter');
  await expect(taskCenter).toBeVisible({timeout: 10_000});
  await expect(taskCenter).toContainText('数据导入 / 上传');

  await taskCenter.locator('[data-utc-toggle]').click();
  await expect(taskCenter).toContainText('refresh-recovery.zip');
  await expect(taskCenter).toContainText(/等待启动后台导入|等待中|后台/);

  await page.reload();
  await expect(taskCenter).toBeVisible({timeout: 10_000});
  await taskCenter.locator('[data-utc-toggle]').click();
  await expect(taskCenter).toContainText('refresh-recovery.zip');
  await expect(taskCenter).toContainText(/等待启动后台导入|等待中|后台/);

  // The retired single-task ZIP dock must stay hidden when the unified task center owns visibility.
  await expect(page.locator('#zipImportDurableDock')).toBeHidden();
});
