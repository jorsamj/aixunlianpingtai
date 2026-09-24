(() => {
  'use strict';

  const SESSION_REFRESH_INTERVAL_MS = 30 * 60 * 1000;
  let refreshTimer = null;

  async function readJson(response) {
    const text = await response.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch (_) {
      return {};
    }
  }

  function formatRemaining(seconds) {
    const value = Math.max(0, Number(seconds) || 0);
    if (value >= 48 * 60 * 60) return `${Math.max(1, Math.ceil(value / 86400))}天保持登录`;
    if (value >= 60 * 60) return `${Math.max(1, Math.ceil(value / 3600))}小时有效`;
    return `${Math.max(1, Math.ceil(value / 60))}分钟有效`;
  }

  function formatExpiry(timestamp) {
    const value = Number(timestamp) || 0;
    if (!value) return '';
    try {
      return new Date(value * 1000).toLocaleString();
    } catch (_) {
      return '';
    }
  }

  function applyIdentity(body) {
    const name = String(body.user?.username || '畅联云用户');
    const target = document.getElementById('authUsername');
    const life = document.getElementById('authSessionLife');
    const identity = document.getElementById('authIdentity');
    if (target) target.textContent = name;
    if (life) life.textContent = formatRemaining(body.remaining_seconds);

    if (identity) {
      const localExpiry = formatExpiry(body.expires_at);
      const upstreamExpiry = formatExpiry(body.upstream_token_expires_at);
      const upstreamSource = String(body.upstream_token_expiry_source || 'undocumented');
      const upstreamLine = upstreamExpiry
        ? `畅联云 Token：${upstreamExpiry}（${upstreamSource}）`
        : '畅联云 Token：登录接口未公开有效期';
      identity.title = [
        `畅联云账号：${name}`,
        localExpiry ? `本平台会话：${localExpiry}` : '',
        upstreamLine,
      ].filter(Boolean).join('\n');
    }

    window.__changLianAuthSession = Object.freeze({...body});
    return body;
  }

  async function hydrateAuthIdentity({redirectOnFailure = true} = {}) {
    try {
      const response = await fetch('/api/auth/session', {
        credentials: 'same-origin',
        cache: 'no-store',
      });
      const body = await readJson(response);
      if (!response.ok || !body.authenticated) {
        if (redirectOnFailure) window.location.replace('/login?next=%2F');
        return null;
      }
      return applyIdentity(body);
    } catch (_) {
      return null;
    }
  }

  function startSessionKeepalive() {
    if (refreshTimer) window.clearInterval(refreshTimer);
    refreshTimer = window.setInterval(
      () => void hydrateAuthIdentity({redirectOnFailure: true}),
      SESSION_REFRESH_INTERVAL_MS,
    );
  }

  window.logoutChangLianAuth = async function logoutChangLianAuth() {
    const button = document.getElementById('logoutBtn');
    if (button) button.disabled = true;
    if (refreshTimer) {
      window.clearInterval(refreshTimer);
      refreshTimer = null;
    }
    try {
      await fetch('/api/auth/logout', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: '{}',
      });
    } finally {
      window.location.replace('/login');
    }
  };

  async function bootAuthSession() {
    const body = await hydrateAuthIdentity({redirectOnFailure: true});
    if (body?.authenticated) startSessionKeepalive();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => void bootAuthSession(), {once: true});
  } else {
    void bootAuthSession();
  }
})();
