import {actionRegistry, invokeAction, registerAction} from './modules/actions.js';
import {messageFromApiError} from './modules/api.js';
import {createModalStack} from './modules/modal.js';


const modalStack = createModalStack();

registerAction('algorithm.create', () => {
  if (typeof window.openNewAlgorithm423 !== 'function') {
    throw new Error('创建算法功能尚未加载，请刷新页面后重试。');
  }
  return window.openNewAlgorithm423();
});

document.addEventListener('click', async event => {
  const target = event.target.closest('[data-action]');
  if (!target) return;
  event.preventDefault();
  try {
    await invokeAction(target.dataset.action, {event, target});
  } catch (error) {
    const message = messageFromApiError(error);
    if (typeof window.toast === 'function') window.toast(message);
    else console.error(message);
  }
});

window.PlatformCore = {
  actions: actionRegistry,
  modalStack,
  messageFromApiError
};

