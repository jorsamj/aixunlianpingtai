function scopeText(annotation) {
  const scope = Array.isArray(annotation?.annotation_scope) ? annotation.annotation_scope : [];
  if (!scope.length) return '当前启用标签';
  if (scope.includes('*')) return '本次算法全部标签';
  return scope.join('、');
}

export function installNegativeSampleRuntime({getState} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__negativeSampleRuntimeInstalled) return window.NegativeSampleRuntime;

  let destroyed = false;
  const state = () => getState?.() || {};

  function decorate() {
    if (destroyed || typeof document === 'undefined') return false;
    const current = state();
    const toolbar = document.querySelector?.('.ann420-stable #ann420ReviewPanel');
    const button = document.getElementById?.('ann420SaveReview');
    if (!toolbar || !button || !current?.activeImage || !current?.ann) return false;

    const boxes = Array.isArray(current.ann.boxes) ? current.ann.boxes : [];
    const confirmed = !current.annDirty && boxes.length === 0 && current.ann.annotation_state === 'confirmed_empty';

    button.dataset.negativeSample = '1';
    button.title = '先查看图片并显式选择已审核类别，再保存正式标注与审核范围';
    button.hidden = false;
    const label = boxes.length ? '保存并确认审核' : confirmed ? '✓ 已确认负样本' : '确认本图无目标';
    if (button.textContent !== label) button.textContent = label;
    button.classList?.toggle?.('primary', confirmed);

    let status = toolbar.querySelector?.('[data-negative-sample-status]');
    if (!confirmed) {
      status?.remove?.();
      return true;
    }
    if (!status) {
      status = document.createElement('span');
      status.dataset.negativeSampleStatus = '1';
      status.className = 'muted';
      toolbar.appendChild(status);
    }
    const text = `负样本范围：${scopeText(current.ann)}`;
    if (status.textContent !== text) status.textContent = text;
    return true;
  }

  const runtime = Object.freeze({
    decorate,
    destroy() {
      destroyed = true;
      document.querySelector?.('[data-negative-sample-status]')?.remove?.();
      if (window.NegativeSampleRuntime === runtime) window.NegativeSampleRuntime = null;
      window.__negativeSampleRuntimeInstalled = false;
    },
  });

  window.NegativeSampleRuntime = runtime;
  window.__negativeSampleRuntimeInstalled = true;
  queueMicrotask(decorate);
  return runtime;
}
