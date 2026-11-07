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
  const providers = [...document.querySelectorAll('[data-login-provider]')];
  const advanced = document.getElementById('loginRemoteAdvanced');
  const description = document.getElementById('loginModeDescription');
  const securityNote = document.getElementById('loginSecurityNote');
  let activeProvider = 'local';

  function selectProvider(provider) {
    if (!['local', 'changlian'].includes(provider)) return;
    const wasLocal = activeProvider === 'local';
    activeProvider = provider;
    const local = provider === 'local';
    providers.forEach(button => {
      const selected = button.dataset.loginProvider === provider;
      button.classList.toggle('active', selected);
      button.setAttribute('aria-pressed', String(selected));
    });
    advanced.classList.toggle('hidden', local);
    if (local) advanced.open = false;
    description.textContent = local ? '使用本地账号登录，无需连接畅联云' : '通过畅联云验证身份（需要可访问外部平台）';
    securityNote.textContent = local ? '本地认证，无需外部网络连接' : '畅联云账号由远端校验，本平台不保存密码';
    username.placeholder = local ? '请输入本地用户名' : '请输入畅联云用户名';
    if (wasLocal && !local && username.value.trim() === 'jiangjs') username.value = '';
    if (local && !username.value.trim()) username.value = 'jiangjs';
    password.value = '';
    clearError();
  }

  providers.forEach(button => button.addEventListener('click', () => selectProvider(button.dataset.loginProvider)));

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
      showError('请输入用户名和密码。');
      (user ? password : username).focus();
      return;
    }

    const payload = {provider: activeProvider, username: user, password: secret};
    if (activeProvider === 'changlian' && code.value.trim()) payload.code = code.value.trim();
    if (activeProvider === 'changlian' && uuid.value.trim()) payload.uuid = uuid.value.trim();

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
        throw new Error(body.message || body.detail || '账号登录失败');
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
