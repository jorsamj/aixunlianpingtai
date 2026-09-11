function scopeText(annotation) {
  const scope = Array.isArray(annotation?.annotation_scope) ? annotation.annotation_scope : [];
  if (!scope.length) return '当前启用标签';
  if (scope.includes('*')) return '本次算法全部标签';
  return scope.join('、');
}

export function installNegativeSampleRuntime({getState, notify}) {
  if (window.__negativeSampleRuntimeInstalled) return;
  window.__negativeSampleRuntimeInstalled = true;

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
      const saved = await window.saveAnn?.(true);
      if (saved === false) return;
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

  const wrap = () => {
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

  if (!wrap()) {
    for (const delay of [50, 200, 500, 1200]) setTimeout(wrap, delay);
  }
  document.addEventListener('click', event => {
    if (event.target.closest?.('[onclick*="openAnnotation"], [onclick*="openAnnot"]')) {
      setTimeout(inject, 0);
    }
  });
}
