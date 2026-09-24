import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const loginHtml = readFileSync('static/login.html', 'utf8');
const loginJs = readFileSync('static/login.js', 'utf8');
const sessionJs = readFileSync('static/auth-session.js', 'utf8');
const indexHtml = readFileSync('static/index.html', 'utf8');
const backend = readFileSync('platform_core/changlian_login_auth.py', 'utf8');
const app = readFileSync('app.py', 'utf8');

test('login page uses the canonical local auth owner and never calls ChangLian from browser', () => {
  assert.match(loginHtml, /id="changlianLoginForm"/);
  assert.match(loginHtml, /name="username"/);
  assert.match(loginHtml, /name="password"/);
  assert.match(loginHtml, /name="code"/);
  assert.match(loginHtml, /name="uuid"/);
  assert.match(loginJs, /fetch\('\/api\/auth\/login'/);
  assert.doesNotMatch(loginJs, /vip\.24hlink\.cn/);
  assert.doesNotMatch(loginJs, /localStorage|sessionStorage/);
});

test('backend owns ChangLian POST login and does not use internal application token as user login', () => {
  assert.match(backend, /DEFAULT_CHANGLIAN_LOGIN_BASE_URL = "http:\/\/vip\.24hlink\.cn\/prod-api"/);
  assert.match(backend, /return f"\{self\.base_url\}\/login"/);
  assert.doesNotMatch(backend, /internal\/auth\/token/);
  assert.match(app, /_CHANGLIAN_LOGIN_CLIENT\.login/);
  assert.match(app, /httponly=True/);
});

test('authenticated shell exposes current cloud identity and logout without storing credentials', () => {
  assert.match(indexHtml, /id="authUsername"/);
  assert.match(indexHtml, /id="logoutBtn"/);
  assert.match(indexHtml, /auth-session\.js/);
  assert.match(sessionJs, /fetch\('\/api\/auth\/session'/);
  assert.match(sessionJs, /fetch\('\/api\/auth\/logout'/);
  assert.doesNotMatch(sessionJs, /password|localStorage|sessionStorage/);
});


test('session runtime keeps an authenticated browser alive without browser credential storage', () => {
  assert.match(sessionJs, /SESSION_REFRESH_INTERVAL_MS = 30 \* 60 \* 1000/);
  assert.match(sessionJs, /setInterval/);
  assert.match(sessionJs, /cache: 'no-store'/);
  assert.doesNotMatch(sessionJs, /localStorage|sessionStorage/);
});

test('backend exposes rolling and absolute session lifetime without exposing upstream token', () => {
  assert.match(backend, /DEFAULT_SESSION_IDLE_TTL_SECONDS = 7 \* 24 \* 60 \* 60/);
  assert.match(backend, /DEFAULT_SESSION_ABSOLUTE_TTL_SECONDS = 30 \* 24 \* 60 \* 60/);
  assert.match(backend, /upstream_expiry_source/);
  assert.match(app, /MC_AUTH_SESSION_IDLE_SECONDS/);
  assert.match(app, /MC_AUTH_SESSION_ABSOLUTE_SECONDS/);
  assert.match(app, /_set_auth_cookie/);
  assert.doesNotMatch(app, /"token": result/);
});
