(() => {
  'use strict';

  async function readJson(response) {
    const text = await response.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch (_) {
      return {};
    }
  }

  async function hydrateAuthIdentity() {
    try {
      const response = await fetch('/api/auth/session', {credentials: 'same-origin'});
      const body = await readJson(response);
      if (!response.ok || !body.authenticated) {
        window.location.replace('/login?next=%2F');
        return null;
      }
      const name = String(body.user?.username || '畅联云用户');
      const target = document.getElementById('authUsername');
      if (target) target.textContent = name;
      window.__changLianAuthSession = Object.freeze(body);
      return body;
    } catch (_) {
      return null;
    }
  }

  window.logoutChangLianAuth = async function logoutChangLianAuth() {
    const button = document.getElementById('logoutBtn');
    if (button) button.disabled = true;
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

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => void hydrateAuthIdentity(), {once: true});
  } else {
    void hydrateAuthIdentity();
  }
})();
