import {test, expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';

function freePort() {
  return new Promise(resolve => {
    const socket = createServer();
    socket.listen(0, '127.0.0.1', () => {
      const {port} = socket.address();
      socket.close(() => resolve(port));
    });
  });
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

test('task center bounds receipt reads for 50 sessions and never marks a 150-part session done', async ({page, request}) => {
  test.setTimeout(180_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-upload-tasks-bounded-'));
  const env = {...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics')};
  const {origin, child} = await startIsolated(env);
  try {
    const project = await (await request.post(origin + '/api/projects', {
      data: {name: '任务中心有界', labels: [{code: 'fire', display_name: '明火'}]},
    })).json();
    const auth = await (await request.get(origin + '/api/auth/session')).json();
    const actorKey = JSON.stringify([auth.provider || '', auth.user?.username || '']);
    const indexKey = `material-upload-index:v1:${encodeURIComponent(actorKey)}:${encodeURIComponent(project.id)}`;
    const now = Date.now();
    const rows = Array.from({length: 48}, (_, index) => ({
      id: `hist-${index}-0001`, totalFiles: 1, requestIds: [`hist-${index}-0001`],
      batchIds: [`hist-${index}-0001`], status: 'SUCCEEDED', failed: 0, pendingDecision: 0,
      confirmationState: 'DONE', createdAt: new Date(now - index * 1000).toISOString(),
      updatedAt: new Date(now - index * 1000).toISOString(),
    }));
    rows.push({id: 'active-0001', totalFiles: 1, requestIds: ['active-0001'], batchIds: [],
      status: 'UPLOADING', failed: 0, pendingDecision: 0, confirmationState: '',
      createdAt: new Date(now).toISOString(), updatedAt: new Date(now).toISOString()});
    rows.push({id: 'big-0001', totalFiles: 150,
      requestIds: Array.from({length: 150}, (_, index) => `big-${String(index + 1).padStart(4, '0')}`),
      batchIds: [], status: 'SUCCEEDED', failed: 0, pendingDecision: 0, confirmationState: 'DONE',
      createdAt: new Date(now).toISOString(), updatedAt: new Date(now).toISOString()});

    let receiptReads = 0;
    await page.route('**/api/v55/projects/*/upload-batches/*', route => {
      receiptReads += 1;
      const requestId = decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1));
      const status = requestId === 'active-0001' ? 'PROCESSING' : 'SUCCEEDED';
      return route.fulfill({json: {id: requestId, upload_request_status: status,
        items: status === 'SUCCEEDED' ? [{image_id: `image-${requestId}`,
          decision: 'pending', image: {id: `image-${requestId}`, filename: `${requestId}.jpg`}}] : [],
        upload_failed: []}});
    });
    await page.route('**/api/v19/projects/*/import/jobs', route =>
      route.fulfill({json: {ok: true, items: []}}));
    await page.addInitScript(([key, value]) => localStorage.setItem(key, value),
      [indexKey, JSON.stringify(rows)]);
    await page.goto(`${origin}/app/#/projects/${project.id}/materials/tasks`);
    await expect(page.getByRole('heading', {name: '上传任务', level: 2})).toBeVisible({timeout: 45000});
    await expect.poll(() => page.getByRole('row').filter({hasText: '图片上传批次'}).count())
      .toBe(50);
    expect(receiptReads).toBeLessThanOrEqual(120);
    const initialReads = receiptReads;
    console.log(`R6_RECEIPT_READS initial=${initialReads}`);

    const bigRow = page.getByRole('row').filter({hasText: 'big-0001'});
    await expect(bigRow).toContainText('待核验');
    await expect(bigRow).toContainText('超过 100 个分片');
    await expect(bigRow).not.toContainText('服务器已入库');

    await page.waitForTimeout(4000);
    console.log(`R6_RECEIPT_READS second=${receiptReads}`);
    expect(receiptReads).toBeLessThanOrEqual(initialReads + 2);
    await expect(bigRow).toContainText('待核验');
  } finally { child.kill(); }
});
