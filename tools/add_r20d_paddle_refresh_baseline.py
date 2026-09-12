from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'tests/browser/navigation-stability.spec.mjs'
s=p.read_text(encoding='utf-8')
marker="test('paddle environment activation keeps manual and quick-detect behavior', async ({page}) => {"
if marker in s:
    raise SystemExit('R20d baseline already present')
block=r'''

test('paddle environment activation keeps manual and quick-detect behavior', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));
  const selectBodies = [];
  const testBodies = [];
  let detectCalls = 0;

  await page.route('**/api/paddle_env/select', async route => {
    const body = route.request().postDataJSON();
    selectBodies.push(body);
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({ok: true, active: body})});
  });
  await page.route('**/api/paddle_env/test', async route => {
    const body = route.request().postDataJSON();
    testBodies.push(body);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, modules: {paddle: '3.0.0'}, paddledet_exists: true, algorithm_scan: {total: 12, families: {ppyoloe: 12}}}),
    });
  });
  await page.route('**/api/paddle_env/detect', async route => {
    detectCalls += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, candidates: [{
        name: '自动飞桨',
        python_path: '/opt/paddle/bin/python',
        paddledet_dir: '/opt/PaddleDetection',
        paddlex_dir: '/opt/PaddleX',
        algorithm_scan: {total: 12, families: {ppyoloe: 12}},
      }]}),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await page.evaluate(() => window.setPage('训练资源'));
  await expect(page.locator('#title')).toContainText('训练资源');

  const paddleCard = page.locator('.quick-card').filter({hasText: '本机飞桨'}).last();
  await expect(paddleCard).toBeVisible();
  await paddleCard.locator('#ppy').fill('/manual/paddle/python');
  await paddleCard.locator('#pdet').fill('/manual/PaddleDetection');
  await paddleCard.locator('#pxdir').fill('/manual/PaddleX');
  await paddleCard.getByRole('button', {name: '检测并启用'}).click();
  await expect(page.locator('#toast')).toContainText('飞桨环境已启用');
  expect(selectBodies[0]).toMatchObject({
    name: '本机飞桨',
    python_path: '/manual/paddle/python',
    paddledet_dir: '/manual/PaddleDetection',
    paddlex_dir: '/manual/PaddleX',
  });
  expect(testBodies[0]).toMatchObject(selectBodies[0]);

  const currentPaddleCard = page.locator('.quick-card').filter({hasText: '本机飞桨'}).last();
  await currentPaddleCard.getByRole('button', {name: '一键检测'}).click();
  await expect(page.locator('#toast')).toContainText('已启用飞桨环境');
  expect(detectCalls).toBe(1);
  expect(selectBodies.at(-1)).toMatchObject({
    name: '自动飞桨',
    python_path: '/opt/paddle/bin/python',
    paddledet_dir: '/opt/PaddleDetection',
    paddlex_dir: '/opt/PaddleX',
  });
  expect(pageErrors).toEqual([]);
});
'''
p.write_text(s+block,encoding='utf-8')
if (ROOT/'VERSION.txt').read_text(encoding='utf-8').strip()!='42.24.0':
    raise SystemExit('formal VERSION changed')
print('R20d paddle behavior baseline added')
