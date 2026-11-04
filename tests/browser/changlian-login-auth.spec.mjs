import {test, expect} from '@playwright/test';

test('default local login works offline, persists across refresh and logs out', async ({page, context}) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await expect(page.locator('[data-login-provider="local"]')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.locator('#loginRemoteAdvanced')).toBeHidden();
  await expect(page.locator('#loginUsername')).toHaveValue('jiangjs');
  await page.locator('#loginPassword').fill('invalid');
  await page.locator('#loginSubmit').click();
  await expect(page.locator('#loginError')).toContainText('本地用户名或密码错误');
  await page.locator('#loginPassword').fill('123456');
  await Promise.all([
    page.waitForURL(url => url.pathname === '/'),
    page.locator('#loginSubmit').click(),
  ]);
  await expect(page.locator('#authUsername')).toHaveText('jiangjs');
  await expect(page.locator('.brand-company-title')).toHaveText('算法训练');
  const session = await page.evaluate(async () => (await fetch('/api/auth/session')).json());
  expect(session.provider).toBe('local');
  expect(session.upstream_token_expires_at).toBe(null);
  expect(session.upstream_token_expiry_source).toBe('local');
  const bootstrap = await page.request.get('/api/v53/bootstrap/status');
  expect(bootstrap.ok()).toBe(true);
  const {active_project_id: projectId} = await bootstrap.json();
  expect(projectId).toBeTruthy();
  const created = await page.request.post(`/api/v12/projects/${projectId}/algorithms`, {
    data: {name: '内网独立算法', industry: '现场安全', algorithm_type: 'yolo_ultralytics'},
  });
  expect(created.status()).toBe(200);
  const createdAlgorithm = (await created.json()).algorithm;
  expect(createdAlgorithm.source_type).toBe('LOCAL');
  expect(createdAlgorithm.master_data_readonly).toBe(false);
  const listed = await page.request.get(`/api/v12/projects/${projectId}/algorithms`);
  expect((await listed.json()).items.some(row => row.id === createdAlgorithm.id)).toBe(true);
  const cookie = (await context.cookies()).find(c => c.name === 'mc_changlian_session');
  expect(cookie?.httpOnly).toBe(true);
  await page.reload();
  await expect(page.locator('#authUsername')).toHaveText('jiangjs');
  await page.locator('#logoutBtn').click();
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  expect((await page.request.get('/api/system/version')).status()).toBe(401);
});

test('refresh keeps optional ChangLian login session and logout closes it', async ({page, context}) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await expect(page.getByRole('heading', {name: '欢迎回来'})).toBeVisible();
  await expect(page.locator('.company-brand-login .login-local-brand')).toHaveText('算法训练');
  await page.locator('[data-login-provider="changlian"]').click();
  await expect(page.locator('#loginRemoteAdvanced')).toBeHidden();

  await page.locator('#loginUsername').fill('demo');
  await page.locator('#loginPassword').fill('wrong');
  await page.locator('#loginSubmit').click();
  await expect(page.locator('#loginError')).toContainText('畅联云账号登录失败');

  await page.locator('#loginPassword').fill('secret');
  await Promise.all([
    page.waitForURL(url => url.pathname === '/'),
    page.locator('#loginSubmit').click(),
  ]);

  await expect(page.locator('#authUsername')).toHaveText('demo');
  await expect(page.locator('.brand-company-title')).toHaveText('算法训练');

  const cookies = await context.cookies();
  const sessionCookie = cookies.find(cookie => cookie.name === 'mc_changlian_session');
  expect(sessionCookie).toBeTruthy();
  expect(sessionCookie.httpOnly).toBe(true);
  expect(sessionCookie.sameSite).toBe('Lax');
  expect(sessionCookie.expires).toBeGreaterThan(Date.now() / 1000 + 6 * 24 * 60 * 60);

  const sessionBeforeRefresh = await page.evaluate(async () => {
    const response = await fetch('/api/auth/session', {credentials: 'same-origin', cache: 'no-store'});
    return response.json();
  });
  expect(sessionBeforeRefresh.authenticated).toBe(true);
  expect(sessionBeforeRefresh.user.username).toBe('demo');
  expect(sessionBeforeRefresh.provider).toBe('changlian');
  expect(sessionBeforeRefresh.idle_ttl_seconds).toBe(7 * 24 * 60 * 60);
  expect(sessionBeforeRefresh.upstream_token_expiry_source).toBe('expires_in');
  expect(sessionBeforeRefresh.upstream_token_expires_at).toBeTruthy();

  await page.reload();
  await expect(page).toHaveURL('http://127.0.0.1:8012/');
  await expect(page.locator('#authUsername')).toHaveText('demo');
  await expect(page.locator('#changlianLoginForm')).toHaveCount(0);

  await page.locator('#logoutBtn').click();
  await expect(page).toHaveURL(/\/login(?:\?|$)/);

  const protectedApi = await page.request.get('/api/system/version');
  expect(protectedApi.status()).toBe(401);

  await page.goto('/data/private-artifact.bin');
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
});


test('mobile login renders neutral algorithm-training branding', async ({page}) => {
  await page.setViewportSize({width:390, height:844});
  await page.goto('/');
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await expect(page.locator('.login-mobile-company-brand .login-local-brand')).toHaveText('算法训练');
});
