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

  function applyIdentity(body) {
    const name = String(body.user?.username || '畅联云用户');
    const target = document.getElementById('authUsername');
    if (target) target.textContent = name;
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
