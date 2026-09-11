function scopeText(annotation) {
  const scope = Array.isArray(annotation?.annotation_scope) ? annotation.annotation_scope : [];
  if (!scope.length) return '当前启用标签';
  if (scope.includes('*')) return '本次算法全部标签';
  return scope.join('、');
}

function unconfirmedEmpty(state) {
  const boxes = Array.isArray(state?.ann?.boxes) ? state.ann.boxes : [];
  return Boolean(
    state?.activeImage &&
    state?.ann &&
    state.annDirty &&
    boxes.length === 0 &&
    state.ann.annotation_state !== 'confirmed_empty'
  );
}

export function installNegativeSampleRuntime({getState, notify}) {
  if (window.__negativeSampleRuntimeInstalled) return;
  window.__negativeSampleRuntimeInstalled = true;
  let confirmingNegative = false;

  const warnEmpty = () => {
    notify?.('当前为 0 个标注框。若确认画面中没有目标，请点击“确认无目标”；系统不会把普通空保存自动当成负样本。');
  };

  const inject = () => {
    const state = getState?.();
    if (!state?.activeImage || !state?.ann) return;
    const toolbar = document.querySelector('#modalBody .ann-toolbar');
    if (!toolbar || toolbar.querySelector('[data-negative-sample]')) return;

    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'btn small soft';
    button.dataset.negativeSample = '1';
    button.textContent = state.ann.annotation_state === 'confirmed_empty' ? '✓ 已确认负样本' : '确认无目标';
    button.title = '明确确认当前图片中不存在本次训练关注的目标；将作为 YOLO 空标签负样本参与训练';
    button.onclick = async () => {
      const current = getState?.();
      if (!current?.activeImage || !current?.ann) return;
      const boxes = Array.isArray(current.ann.boxes) ? current.ann.boxes : [];
      if (boxes.length) {
        const accepted = window.confirm('当前图片已有标注框。确认负样本会清空这些框，并把图片作为“确认无目标”样本。是否继续？');
        if (!accepted) return;
      }
      current.ann.boxes = [];
      current.activeBox = null;
      current.annDirty = true;
      if (typeof window.drawBoxes === 'function') window.drawBoxes();
      if (typeof window.renderAnnSide === 'function') window.renderAnnSide();
      confirmingNegative = true;
      try {
        const saved = await window.saveAnn?.(true);
        if (saved === false) return;
      } finally {
        confirmingNegative = false;
      }
      button.textContent = '✓ 已确认负样本';
      button.classList.add('primary');
      notify?.(`已确认负样本 · 范围：${scopeText(current.ann)}`);
    };
    toolbar.insertBefore(button, toolbar.firstChild?.nextSibling || null);

    const status = document.createElement('span');
    status.dataset.negativeSampleStatus = '1';
    status.className = 'muted';
    if (state.ann.annotation_state === 'confirmed_empty') {
      status.textContent = `负样本范围：${scopeText(state.ann)}`;
      toolbar.appendChild(status);
    }
  };

  const wrapRender = () => {
    if (typeof window.renderAnnotator !== 'function' || window.renderAnnotator.__negativeWrapped) return false;
    const original = window.renderAnnotator;
    const wrapped = function (...args) {
      const result = original.apply(this, args);
      queueMicrotask(inject);
      return result;
    };
    wrapped.__negativeWrapped = true;
    window.renderAnnotator = wrapped;
    return true;
  };

  const wrapSave = () => {
    if (typeof window.saveAnn !== 'function' || window.saveAnn.__negativeWrapped) return false;
    const original = window.saveAnn;
    const wrapped = async function (...args) {
      const state = getState?.();
      const boxes = Array.isArray(state?.ann?.boxes) ? state.ann.boxes : [];
      if (
        state?.activeImage &&
        state?.ann &&
        boxes.length === 0 &&
        state.ann.annotation_state !== 'confirmed_empty' &&
        !confirmingNegative
      ) {
        warnEmpty();
        return false;
      }
      return original.apply(this, args);
    };
    wrapped.__negativeWrapped = true;
    window.saveAnn = wrapped;
    return true;
  };

  const wrapNavigation = name => {
    const fn = window[name];
    if (typeof fn !== 'function' || fn.__negativeWrapped) return false;
    const wrapped = async function (...args) {
      if (unconfirmedEmpty(getState?.())) {
        warnEmpty();
        return false;
      }
      return fn.apply(this, args);
    };
    wrapped.__negativeWrapped = true;
    window[name] = wrapped;
    return true;
  };

  const install = () => {
    const rendered = wrapRender();
    const saved = wrapSave();
    wrapNavigation('prevImage');
    wrapNavigation('nextImage');
    return rendered || saved;
  };

  if (!install()) {
    for (const delay of [50, 200, 500, 1200]) setTimeout(install, delay);
  } else {
    for (const delay of [200, 500, 1200]) setTimeout(install, delay);
  }
  document.addEventListener('click', event => {
    if (event.target.closest?.('[onclick*="openAnnotation"], [onclick*="openAnnot"]')) {
      setTimeout(inject, 0);
    }
  });
}
