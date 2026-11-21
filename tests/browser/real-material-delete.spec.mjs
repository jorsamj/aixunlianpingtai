import {test, expect} from '@playwright/test';
import {spawn, execFileSync} from 'node:child_process';
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

const seedGt = (env, projectId, imageId) => execFileSync('python', ['-c', `
import app
annotations = app._v50_annotation_repository(${JSON.stringify(projectId)})
annotations.upsert(${JSON.stringify(imageId)}, boxes=[{"id":"box-1","label":"fire","x1":10,"y1":10,"x2":50,"y2":50}],
                   annotation_state="annotated", annotation_scope=["fire"])
print(annotations.get(${JSON.stringify(imageId)})["version"])
`], {env}).toString();

const inspect = (env, projectId, imageId) => JSON.parse(execFileSync('python', ['-c', `
import json, os, sqlite3
from pathlib import Path
import app
project = Path(os.environ["MC_TRAIN_DATA_DIR"]) / "projects" / ${JSON.stringify(projectId)}
annotations = app._v50_annotation_repository(${JSON.stringify(projectId)})
with sqlite3.connect(annotations.path) as db:
    gt_rows = db.execute("SELECT COUNT(*) FROM annotations WHERE image_id=?", (${JSON.stringify(imageId)},)).fetchone()[0]
images = [path for path in project.rglob("*") if path.is_file() and path.suffix.lower() in {".jpg", ".jpeg", ".png"}]
print(json.dumps({"material": app.material_store(${JSON.stringify(projectId)}).get(${JSON.stringify(imageId)}),
                  "gt_rows": gt_rows, "image_bytes": sum(path.stat().st_size for path in images)}))
`], {env}).toString());

async function uploadOne(request, origin, projectId, name) {
  const jpeg = execFileSync('python', ['-c',
    "from PIL import Image;import io,sys;b=io.BytesIO();Image.new('RGB',(320,240),'#dde5ed').save(b,format='JPEG');sys.stdout.buffer.write(b.getvalue())"]);
  const uploaded = await request.post(`${origin}/api/projects/${encodeURIComponent(projectId)}/images`, {
    multipart: {files: {name, mimeType: 'image/jpeg', buffer: jpeg}, dataset_id: 'default'},
  });
  expect(uploaded.ok()).toBeTruthy();
  return (await uploaded.json()).uploaded[0];
}

test('Vue standalone material library deletes one material through the v62 plan and keeps bytes', async ({page, request}) => {
  test.setTimeout(180_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-material-delete-'));
  const env = {
    ...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics'),
  };
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  const child = spawn('python', ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1',
    '--port', String(port), '--log-level', 'info'], {env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
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
      data: {name: '隔离单张删除', labels: [{code: 'fire', display_name: '明火'}]},
    });
    const project = await created.json();
    const row = await uploadOne(request, origin, project.id, 'delete-me.jpg');
    expect(Number(seedGt(env, project.id, row.id))).toBeGreaterThan(0);
    const before = inspect(env, project.id, row.id);
    expect(before.material).not.toBeNull();
    expect(before.gt_rows).toBe(1);
    expect(before.image_bytes).toBeGreaterThan(0);

    worker = spawn('python', ['tests/browser/helpers/material_delete_worker.py'], {
      env: {...env, MC_WORKER_SECONDS: '150'}, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
    });

    const legacyDeletes = [];
    page.on('request', req => {
      const url = new URL(req.url());
      if (req.method() === 'DELETE' && url.pathname === `/api/projects/${project.id}/images/${row.id}`)
        legacyDeletes.push(url.pathname);
    });
    let estimates = 0, creates = 0;
    page.on('request', req => {
      const url = new URL(req.url());
      if (req.method() !== 'POST' || !url.pathname.includes(`${project.id}/material-batches`)) return;
      if (url.pathname.endsWith('/estimate')) estimates += 1;
      else creates += 1;
    });

    await page.goto(`${origin}/app/#/projects/${project.id}/materials`);
    const card = page.locator('.material-card').filter({hasText: row.filename});
    await expect(card).toBeVisible({timeout: 45000});
    await card.getByRole('button', {name: '删除', exact: true}).click();
    const dialog = page.getByRole('dialog');
    await expect(dialog).toContainText('本次删除 1 张素材', {timeout: 30000});
    expect(estimates).toBe(1);
    expect(creates).toBe(0);

    const createResponse = page.waitForResponse(res => {
      const url = new URL(res.url());
      return res.request().method() === 'POST' && url.pathname.endsWith('/material-batches')
        && url.pathname.includes(project.id);
    });
    await dialog.getByRole('button', {name: '确认删除'}).click();
    const task = await (await createResponse).json();
    expect(task.project_id).toBe(project.id);
    expect(task.operation).toBe('DELETE_INDEX');
    expect(task.task_id).toBeTruthy();

    await expect(card).toHaveCount(0, {timeout: 120000});
    const finished = await (await request.get(
      `${origin}/api/v62/projects/${project.id}/material-batches/${task.task_id}`,
    )).json();
    expect(finished.status).toBe('SUCCEEDED');
    const results = await (await request.get(
      `${origin}/api/v62/projects/${project.id}/material-batches/${task.task_id}/results`,
    )).json();
    const item = (results.items || []).find(entry => entry.image_id === row.id);
    expect(item?.item_state).toBe('succeeded');

    await expect(card).toHaveCount(0, {timeout: 30000});
    const after = inspect(env, project.id, row.id);
    expect(after.material).toBeNull();
    expect(after.gt_rows).toBe(0);
    expect(after.image_bytes).toBe(before.image_bytes);
    expect(legacyDeletes).toEqual([]);
    expect(creates).toBe(1);
  } finally {
    worker?.kill();
    child.kill();
  }
});

test('unknown create response keeps the original plan and never creates a second task', async ({page, request}) => {
  test.setTimeout(180_000);
  const data = mkdtempSync(join(tmpdir(), 'xjalgo-material-delete-unknown-'));
  const env = {
    ...process.env, MC_TRAIN_DATA_DIR: data, MC_PLATFORM_VERSION: 'browser-test',
    MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS: '1', YOLO_CONFIG_DIR: join(data, 'ultralytics'),
  };
  const port = await freePort();
  const origin = `http://127.0.0.1:${port}`;
  const child = spawn('python', ['-m', 'uvicorn', 'app:app', '--host', '127.0.0.1',
    '--port', String(port), '--log-level', 'info'], {env, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true});
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
    const created = await request.post(origin + '/api/projects', {
      data: {name: '隔离未知删除', labels: [{code: 'fire', display_name: '明火'}]},
    });
    const project = await created.json();
    const row = await uploadOne(request, origin, project.id, 'unknown-delete.jpg');
    seedGt(env, project.id, row.id);
    worker = spawn('python', ['tests/browser/helpers/material_delete_worker.py'], {
      env: {...env, MC_WORKER_SECONDS: '150'}, stdio: ['ignore', 'pipe', 'pipe'], windowsHide: true,
    });

    let creates = 0;
    await page.route('**/api/v62/projects/*/material-batches', async route => {
      const url = new URL(route.request().url());
      if (route.request().method() === 'POST' && !url.pathname.endsWith('/estimate')) {
        creates += 1;
        if (creates === 1) {
          await route.fetch();
          return route.abort();
        }
      }
      return route.continue();
    });

    await page.goto(`${origin}/app/#/projects/${project.id}/materials`);
    const card = page.locator('.material-card').filter({hasText: row.filename});
    await expect(card).toBeVisible({timeout: 45000});
    await card.getByRole('button', {name: '删除', exact: true}).click();
    await expect(page.getByRole('dialog')).toContainText('本次删除 1 张素材', {timeout: 30000});
    await page.getByRole('dialog').getByRole('button', {name: '确认删除'}).click();
    await expect(page.locator('.el-dialog__body')).toContainText(/未确认|核验/, {timeout: 30000});
    await expect.poll(async () => creates, {timeout: 30000}).toBe(1);
    await expect(card).toHaveCount(0, {timeout: 90000});
    expect(creates).toBe(1);
  } finally {
    worker?.kill();
    child.kill();
  }
});
