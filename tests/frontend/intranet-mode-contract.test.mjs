import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app = readFileSync('app.py', 'utf8');
const algorithms = readFileSync('platform_core/algorithms.py', 'utf8');
const login = readFileSync('static/login.js', 'utf8');

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
