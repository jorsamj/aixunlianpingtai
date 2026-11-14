import {defineConfig} from '@playwright/test';

export default defineConfig({
  testDir: './tests/browser',
  testMatch: 'changlian-login-auth.spec.mjs',
  workers: 1,
  timeout: 60_000,
  use: {
    baseURL: 'http://127.0.0.1:8012',
    channel: 'chrome',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  webServer: {
    command: 'python tools/test_auth_server.py',
    url: 'http://127.0.0.1:8012/api/health',
    reuseExistingServer: false,
    timeout: 120_000
  }
});
