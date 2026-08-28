import {defineConfig} from '@playwright/test';


export default defineConfig({
  testDir: './tests/browser',
  timeout: 60_000,
  use: {
    baseURL: 'http://127.0.0.1:8011',
    channel: 'chrome',
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure'
  },
  webServer: {
    command: 'python tools/test_server.py',
    url: 'http://127.0.0.1:8011/api/health',
    reuseExistingServer: false,
    timeout: 120_000
  }
});
