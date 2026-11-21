import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync('app.py', 'utf8');
const algorithms = readFileSync('platform_core/algorithms.py', 'utf8');
const login = readFileSync('static/login.js', 'utf8');
const integration = readFileSync('static/modules/external-algorithm-platform.js', 'utf8');
const platform = readFileSync('platform_core/external_algorithm_platform.py', 'utf8');

test('internal create endpoint never asks external platform permission', () => {
  const start = app.indexOf('def v12_create_algorithm(');
  const end = app.indexOf('@app.get("/api/v12/projects/{project_id}/algorithms/{algorithm_id}")', start);
  const endpoint = app.slice(start, end);
  assert.ok(start >= 0 && end > start);
  assert.doesNotMatch(endpoint, /assert_local_algorithm_create_allowed|_CHANGLIAN_LOGIN_CLIENT|\.sync\(/);
  assert.match(endpoint, /create_algorithm_asset\(algorithms_file\(project_id\)/);
  assert.match(algorithms, /"source_type": "LOCAL"/);
});

test('local login is default and only remote selection supplies captcha', () => {
  assert.match(app, /provider: Literal\["local", "changlian"\] = "local"/);
  assert.match(app, /if payload\.provider == "local":/);
  assert.match(login, /let activeProvider = 'local'/);
  assert.match(login, /activeProvider === 'changlian' && code\.value/);
  assert.match(login, /activeProvider === 'changlian' && uuid\.value/);
});

test('one integration master switch controls backend mode and front-end operations', () => {
  assert.match(integration, /id="externalPlatformMasterSwitch" role="switch"/);
  assert.match(integration, /aria-checked="\$\{external\}"/);
  assert.match(integration, /requestJson\(`\$\{API_ROOT\}\/mode`/);
  assert.doesNotMatch(integration, /input\[name="externalMode"\]/);
  assert.match(platform, /@router\.put\("\/mode"\)/);
  assert.match(platform, /service\.save\(payload, preserve_mode=True\)/);
  assert.match(platform, /def set_mode\(self, mode: Literal\["local", "external"\]\)/);
  assert.match(platform, /self\._external_enabled_check\(\)/);
});

test('same-origin login is default and rotating local password fences existing cookies', () => {
  assert.doesNotMatch(app, /allow_origins=\["\*"\]/);
  assert.match(app, /MC_CORS_ALLOWED_ORIGINS/);
  assert.match(app, /def _verify_browser_session\(/);
  assert.match(app, /local_credential_revision\(/);
  assert.match(app, /credential_revision=revision/);
});
