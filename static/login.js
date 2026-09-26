(() => {
  'use strict';

  const form = document.getElementById('changlianLoginForm');
  const username = document.getElementById('loginUsername');
  const password = document.getElementById('loginPassword');
  const code = document.getElementById('loginCode');
  const uuid = document.getElementById('loginUuid');
  const submit = document.getElementById('loginSubmit');
  const errorBox = document.getElementById('loginError');
  const togglePassword = document.getElementById('togglePassword');

  function safeNext() {
    const value = new URLSearchParams(window.location.search).get('next') || '/';
    if (!value.startsWith('/') || value.startsWith('//')) return '/';
    return value;
  }

  function showError(message) {
    errorBox.textContent = String(message || '登录失败，请重试。');
    errorBox.classList.remove('hidden');
  }

  function clearError() {
    errorBox.textContent = '';
    errorBox.classList.add('hidden');
  }

  function setBusy(busy) {
    submit.disabled = !!busy;
    submit.classList.toggle('loading', !!busy);
    submit.querySelector('span').textContent = busy ? '正在验证…' : '登录';
  }

  async function responseBody(response) {
    const text = await response.text();
    if (!text) return {};
    try {
      return JSON.parse(text);
    } catch (_) {
      return {detail: text};
    }
  }

  togglePassword.addEventListener('click', () => {
    const revealing = password.type === 'password';
    password.type = revealing ? 'text' : 'password';
    togglePassword.textContent = revealing ? '隐藏' : '显示';
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    clearError();
    const user = username.value.trim();
    const secret = password.value;
    if (!user || !secret) {
      showError('请输入畅联云用户名和密码。');
      (user ? password : username).focus();
      return;
    }

    const payload = {username: user, password: secret};
    if (code.value.trim()) payload.code = code.value.trim();
    if (uuid.value.trim()) payload.uuid = uuid.value.trim();

    setBusy(true);
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        credentials: 'same-origin',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const body = await responseBody(response);
      if (!response.ok || !body.authenticated) {
        throw new Error(body.message || body.detail || '畅联云账号登录失败');
      }
      password.value = '';
      window.location.replace(safeNext());
    } catch (error) {
      showError(error && error.message ? error.message : error);
      password.select();
    } finally {
      setBusy(false);
    }
  });

  void fetch('/api/auth/session', {credentials: 'same-origin', cache: 'no-store'})
    .then(response => response.ok ? response.json() : null)
    .then(body => {
      if (body && body.authenticated) window.location.replace(safeNext());
    })
    .catch(() => {});
})();
