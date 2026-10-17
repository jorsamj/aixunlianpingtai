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
    const toolbar = document.querySelector?.('#modalBody .ann420-stable .ann-toolbar')
      || document.querySelector?.('.ann420-stable .ann-toolbar');
    const button = document.getElementById?.('ann420ConfirmEmpty');
    if (!toolbar || !button || !current?.activeImage || !current?.ann) return false;

    const boxes = Array.isArray(current.ann.boxes) ? current.ann.boxes : [];
    const confirmed = current.ann.annotation_state === 'confirmed_empty';
    const locked = Boolean(current.annotationHydrating420 || current.annotationLoadError420);

    button.dataset.negativeSample = '1';
    button.title = '明确确认当前图片中不存在本次算法关注的目标；确认后以 confirmed_empty 负样本写入正式标注';
    button.hidden = locked || boxes.length > 0;
    const label = confirmed ? '✓ 已确认负样本' : '确认无目标';
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
