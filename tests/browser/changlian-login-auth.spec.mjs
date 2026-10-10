import {test, expect} from '@playwright/test';

test('refresh keeps the ChangLian login session and logout closes it', async ({page, context}) => {
  await page.goto('/');
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  await expect(page.getByRole('heading', {name: '欢迎回来'})).toBeVisible();
  const loginLogo = page.locator('.company-brand-login .company-brand-image');
  await expect(loginLogo).toBeVisible();
  await expect.poll(() => loginLogo.evaluate(img => img.complete && img.naturalWidth === 825)).toBe(true);

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
  const shellLogo = page.locator('.brand-company-image');
  await expect(shellLogo).toBeVisible();
  await expect.poll(() => shellLogo.evaluate(img => img.complete && img.naturalWidth === 825)).toBe(true);

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


test('mobile login renders the same company logo', async ({page}) => {
  await page.setViewportSize({width:390, height:844});
  await page.goto('/');
  await expect(page).toHaveURL(/\/login(?:\?|$)/);
  const logo = page.locator('.login-mobile-company-brand .company-brand-image');
  await expect(logo).toBeVisible();
  await expect.poll(() => logo.evaluate(img => img.complete && img.naturalWidth === 825)).toBe(true);
});
