import {test, expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';

const JPEG = Buffer.from('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAoHBwgHBgoICAgLCgoLDhgQDg0NDh0VFhEYIx8lJCIfIiEmKzcvJik0KSEiMEExNDk7Pj4+JS5ESUM8SDc9Pjv/2wBDAQoLCw4NDhwQEBw7KCIoOzs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozs7Ozv/wAARCADwAUADASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD1CiiitDMKKKKACiiigAooooAKKKKACiiigAooooA//2Q==', 'base64');

function freePort() {
  return new Promise(resolve => {
    const socket = createServer();
    socket.listen(0, '127.0.0.1', () => {
      const {port} = socket.address();
      socket.close(() => resolve(port));
    });
  });
}
function crc32(buffer) {
  let table = crc32.table;
  if (!table) {
    table = crc32.table = [];
    for (let n = 0; n < 256; n += 1) {
      let c = n;
      for (let k = 0; k < 8; k += 1) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      table[n] = c >>> 0;
    }
  }
  let crc = 0xffffffff;
  for (const byte of buffer) crc = table[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}
function storedZip(entries) {
  const locals = [], centrals = [];
  let offset = 0;
  for (const entry of entries) {
    const name = Buffer.from(entry.name, 'utf8');
    const crc = crc32(entry.buffer);
    const local = Buffer.alloc(30);
    local.writeUInt32LE(0x04034b50, 0); local.writeUInt16LE(20, 4); local.writeUInt16LE(0, 6);
    local.writeUInt16LE(0, 8); local.writeUInt16LE(0, 10); local.writeUInt16LE(0, 12);
    local.writeUInt32LE(crc, 14); local.writeUInt32LE(entry.buffer.length, 18);
    local.writeUInt32LE(entry.buffer.length, 22); local.writeUInt16LE(name.length, 26);
    local.writeUInt16LE(0, 28);
    locals.push(local, name, entry.buffer);
    const central = Buffer.alloc(46);
    central.writeUInt32LE(0x02014b50, 0); central.writeUInt16LE(20, 4); central.writeUInt16LE(20, 6);
    central.writeUInt16LE(0, 8); central.writeUInt16LE(0, 10); central.writeUInt16LE(0, 12);
    central.writeUInt16LE(0, 14); central.writeUInt32LE(crc, 16);
    central.writeUInt32LE(entry.buffer.length, 20); central.writeUInt32LE(entry.buffer.length, 24);
    central.writeUInt16LE(name.length, 28); central.writeUInt16LE(0, 30); central.writeUInt16LE(0, 32);
    central.writeUInt16LE(0, 34); central.writeUInt16LE(0, 36); central.writeUInt32LE(0, 38);
    central.writeUInt32LE(offset, 42);
    centrals.push(central, name);
    offset += local.length + name.length + entry.buffer.length;
  }
  const centralBuffer = Buffer.concat(centrals);
  const end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(0, 4); end.writeUInt16LE(0, 6);
  end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10);
  end.writeUInt32LE(centralBuffer.length, 12); end.writeUInt32LE(offset, 16); end.writeUInt16LE(0, 20);
  return Buffer.concat([...locals, centralBuffer, end]);
}
async function startIsolated(env) {
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  const child = spawn('python', ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1',
    '--port', String(port), '--log-level', 'info'], {env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('isolated server startup timeout')), 40000);
    child.once('exit', code => { clearTimeout(timer); reject(new Error(`isolated server exited ${code}`)); });
    const onData = chunk => { if (String(chunk).includes('Uvicorn running on')) { clearTimeout(timer); resolve(); } };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
  });
  return {origin, child};
}

test('native Vue opens the real Uppy ZIP dashboard, confirms raw labels and imports through the existing owner', async ({page, request}) => {
  test.setTimeout(240_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-native-zip-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await (await request.post(origin + '/api/projects', {
      data: {name: '原生 ZIP 导入', labels: [{code: 'fire', display_name: '明火'}]},
    })).json();
    await page.goto(`${origin}/app/#/projects/${project.id}/materials`);
    await page.getByRole('button', {name: 'ZIP 数据集（原生）', exact: true}).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${project.id}/materials/zip`));
    await expect(page.locator('.uppy-Dashboard')).toBeVisible({timeout: 45000});

    const archive = storedZip([
      {name: 'one.jpg', buffer: JPEG},
      {name: 'two.jpg', buffer: JPEG},
    ]);
    await page.locator('.uppy-Dashboard input[type=file]').first().setInputFiles({
      name: 'raw-dataset.zip', mimeType: 'application/zip', buffer: archive,
    });
    const upload = page.locator('.uppy-StatusBar-actionBtn--upload');
    await expect(upload).toBeVisible({timeout: 15000});
    await upload.click();

    await expect(page.locator('#native-zip-modal-root .modal')).toBeVisible({timeout: 90000});
    await expect(page.locator('#native-zip-modal-root')).toContainText('确认 ZIP 导入');
    await expect(page.locator('.zip-transfer')).toContainText(/upload_id：[0-9a-f-]+/);
    const modal = page.locator('#native-zip-modal-root');
    if (await modal.getByText('导入未标注原图').count()) {
      await modal.locator('[data-zip-confirm-button]').click();
    } else {
      const folder = modal.locator('[data-zip-folder-row]').first();
      await folder.locator('select[aria-label="数据用途"]').selectOption({index: 1});
      await folder.locator('select[aria-label="素材类型"]').selectOption({label: '未分类'});
      const confirm = modal.locator('[data-zip-confirm-button]');
      await expect(confirm).toBeEnabled({timeout: 15000});
      await expect(confirm).toContainText('确认文件夹并导入');
      await confirm.click();
    }

    await expect.poll(async () => {
      const result = await (await request.get(
        `${origin}/api/v19/projects/${project.id}/import/jobs`)).json();
      return result.items?.[0]?.status;
    }, {timeout: 120000}).toBe('done');
    const jobs = await (await request.get(
      `${origin}/api/v19/projects/${project.id}/import/jobs`)).json();
    const job = jobs.items[0];
    expect(job.report.imported_images).toBe(2);
    expect(job.report.boxes).toBe(0);
    await expect(page.getByText(/导入完成/).first()).toBeVisible({timeout: 30000});
    await expect(page.getByText(/已入库 2 张/)).toBeVisible();
    const list = await (await request.get(
      `${origin}/api/v61/projects/${project.id}/materials?reader_view=true&page=1&page_size=48`)).json();
    expect(list.total).toBe(2);
  } finally { child.kill(); }
});
