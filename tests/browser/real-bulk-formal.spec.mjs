import {test, expect} from '@playwright/test';
import {spawn, execFileSync} from 'node:child_process';
import {mkdtempSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createServer} from 'node:net';

const taskId = 'browser-bulk-real';
const total = 205;
const expectedCommitted = 201;
const excludedIndexes = [0, 1, 24, 25];

function freePort() {
  return new Promise(resolve => {
    const socket = createServer();
    socket.listen(0, '127.0.0.1', () => {
      const {port} = socket.address();
      socket.close(() => resolve(port));
    });
  });
}

test('Vue real FastAPI bulk formal GT: 205 candidates, shuffle exclusion, 201 across three batches', async ({page, request}) => {
  test.setTimeout(240000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-bulk-review-'));
  const env = {
    ...process.env,
    MC_TRAIN_DATA_DIR: data,
    MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1',
    YOLO_CONFIG_DIR: join(data, 'ultralytics'),
  };
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  const child = spawn('python', ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1',
    '--port', String(port), '--log-level', 'info'],
    {env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
  const ready = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('isolated server startup timeout')), 40000);
    child.once('exit', code => { clearTimeout(timer); reject(new Error(`isolated server exited ${code}`)); });
    const onData = chunk => { if (String(chunk).includes('Uvicorn running on')) { clearTimeout(timer); resolve(); } };
    child.stdout.on('data', onData);
    child.stderr.on('data', onData);
  });
  let worker;
  try {
    await ready;
    await expect.poll(async () => {
      try { return (await request.get(origin + '/api/health')).status(); } catch { return 0; }
    }, {timeout: 30000}).toBe(200);

    const created = await request.post(origin + '/api/projects', {
      data: {name: '隔离真实批量', labels: [{code: 'fire', display_name: '明火'}]},
    });
    expect(created.ok()).toBeTruthy();
    const project = await created.json();

    execFileSync('python', ['tests/browser/helpers/bulk_review_seed.py'], {
      env: {...env, MC_PROJECT_ID: project.id, MC_TASK_ID: taskId, MC_BULK_COUNT: String(total)},
      stdio: 'inherit',
    });
    worker = spawn('python', ['tests/browser/helpers/bulk_review_worker.py'], {
      env: {...env, MC_WORKER_SECONDS: '180'},
      stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
    });

    await page.goto(`${origin}/app/#/projects/${project.id}/ai/tasks/${taskId}/review`);
    const freeze = page.getByRole('button', {name: '选择全部筛选结果'});
    await expect(freeze).toBeVisible({timeout: 45000});
    await freeze.click();
    await expect(page.getByText(new RegExp(`可操作 ${total} 张`))).toBeVisible({timeout: 30000});

    // Cross-page exclusion: two on page 1, two on page 2 (same count, exact set).
    const boxes = page.locator('.review-candidate input[type="checkbox"]');
    await boxes.nth(0).uncheck();
    await boxes.nth(1).uncheck();
    await page.getByRole('button', {name: '下一页'}).click();
    await boxes.nth(0).uncheck();
    await boxes.nth(1).uncheck();
    await expect(page.locator('.review-selection').getByText(new RegExp(`已选 ${expectedCommitted} 张`)).first())
      .toBeVisible({timeout: 10000});

    await page.getByRole('button', {name: `后台正式入库 ${expectedCommitted} 张`}).click();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', {name: '预检并封存'}).click();
    await expect(dialog).toContainText(`可入库 ${expectedCommitted} 张`, {timeout: 30000});
    await dialog.getByRole('button', {name: '确认创建后台任务'}).click();
    await dialog.getByRole('button', {name: '关闭'}).last().click();
    await expect(page.locator('.review-bulk')).toContainText(/排队中|后台执行中/, {timeout: 30000});

    const record = await page.evaluate(() => {
      for (let index = 0; index < sessionStorage.length; index += 1) {
        const key = sessionStorage.key(index);
        if (key && key.startsWith('ai-review-bulk:v1:')) return JSON.parse(sessionStorage.getItem(key));
      }
      return null;
    });
    expect(record?.request_id).toBeTruthy();

    // Progress must survive a reload of the real Vue page.
    await page.reload();
    await expect(page.locator('.review-bulk')).toContainText(/排队中|后台执行中|已完成/, {timeout: 45000});
    await expect(page.locator('.review-bulk')).toContainText('已完成', {timeout: 90000});
    await expect(page.locator('.review-bulk')).toContainText(`已证明提交 GT ${expectedCommitted}`, {timeout: 30000});

    const execution = await (await request.get(
      `${origin}/api/v60/projects/${project.id}/annotation-tasks/${taskId}/bulk-formal/intents/${record.request_id}/execution`,
    )).json();
    expect(execution.status).toBe('SUCCEEDED');
    expect(execution.committed_images_proven).toBe(true);
    expect(execution.committed_images).toBe(expectedCommitted);
    expect(execution.completed_batches).toBe(3);

    const dbCheck = `
import json, sys
import app
from platform_core.annotation_candidates import CandidateStore
pid = ${JSON.stringify(project.id)}
tid = ${JSON.stringify(taskId)}
ids = [f'bulk-{index:04d}' for index in range(${total})]
annotations = app._v50_annotation_repository(pid)
store = CandidateStore(app.shared_task_artifacts(), task_id=tid)
gt = annotations.get_many(ids)
committed = [image_id for image_id in ids if int(gt[image_id].get('version') or 0) >= 1]
journal = 0
for offset in range(0, len(ids), 100):
    journal += len(store.get_commit_summaries(ids[offset:offset + 100]))
print(json.dumps({'committed': len(committed), 'total': len(ids),
                  'excluded_versions': {image_id: int(gt[image_id].get('version') or 0)
                                        for image_id in ids if image_id not in committed},
                  'journal': journal}))
`;
    const firstCheck = JSON.parse(execFileSync('python', ['-c', dbCheck], {env}).toString());
    expect(firstCheck.committed).toBe(expectedCommitted);
    expect(firstCheck.total).toBe(total);
    expect(Object.keys(firstCheck.excluded_versions).sort()).toEqual(
      excludedIndexes.map(index => `bulk-${String(index).padStart(4, '0')}`).sort());
    expect(Object.values(firstCheck.excluded_versions).every(version => version === 0)).toBe(true);
    expect(firstCheck.journal).toBe(expectedCommitted);

    // A second, independent operation handles the four excluded candidates.
    await freeze.click();
    await expect(page.getByText(/可操作 4 张/)).toBeVisible({timeout: 30000});
    await page.getByRole('button', {name: '后台正式入库 4 张'}).click();
    await page.getByRole('dialog').getByRole('button', {name: '预检并封存'}).click();
    await expect(page.getByRole('dialog')).toContainText('可入库 4 张', {timeout: 30000});
    await page.getByRole('dialog').getByRole('button', {name: '确认创建后台任务'}).click();
    await page.getByRole('dialog').getByRole('button', {name: '关闭'}).last().click();
    await expect(page.locator('.review-bulk')).toContainText('已完成', {timeout: 90000});

    const secondCheck = JSON.parse(execFileSync('python', ['-c', dbCheck], {env}).toString());
    expect(secondCheck.committed).toBe(total);
    expect(secondCheck.journal).toBe(total);
  } finally {
    worker?.kill();
    child.kill();
  }
});
