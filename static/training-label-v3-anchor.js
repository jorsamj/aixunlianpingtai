(() => {
  'use strict';
  if (window.__trainingLabelV3AnchorInstalled) return;
  window.__trainingLabelV3AnchorInstalled = true;

  function activeTrainingPanel() {
    const direct = document.querySelector('.train-v3-summary')?.closest('.train428-panel');
    if (direct) return direct;

    const legacySummary = document.querySelector('.train429-create .train429-data-summary');
    if (legacySummary) return legacySummary.closest('.train428-panel') || legacySummary.parentElement;

    const roots = [...document.querySelectorAll('.train429-create .train428-panel')];
    return roots.find(panel => {
      const header = panel.querySelector('header');
      return /本次训练素材|训练数据/.test(String(header?.textContent || ''));
    }) || null;
  }

  function anchorPoint(panel) {
    return panel?.querySelector('.train-v3-summary')
      || panel?.querySelector('.train429-data-summary')
      || panel?.querySelector('.train428-data')
      || panel?.querySelector('header')
      || null;
  }

  function sync() {
    const panel = activeTrainingPanel();
    if (!panel) return false;

    // If the historical summary already exists, the classic runtime can use it directly.
    // Still request a refresh because the panel may just have been rewritten.
    const existingSummary = panel.querySelector('.train429-data-summary:not(.training-label-v3-anchor)');
    if (existingSummary) {
      window.TrainingLabelRuntime?.refresh?.();
      return true;
    }

    let anchor = panel.querySelector(':scope > .training-label-v3-anchor');
    if (!anchor) {
      anchor = document.createElement('div');
      anchor.className = 'train429-data-summary training-label-v3-anchor';
      anchor.setAttribute('aria-hidden', 'true');
      anchor.style.display = 'none';
      const point = anchorPoint(panel);
      if (point && point !== panel.querySelector('header')) point.insertAdjacentElement('afterend', anchor);
      else if (point) point.insertAdjacentElement('afterend', anchor);
      else panel.prepend(anchor);
    }
    window.TrainingLabelRuntime?.refresh?.();
    return true;
  }

  const observer = typeof MutationObserver !== 'undefined'
    ? new MutationObserver(() => {
        if (activeTrainingPanel()) queueMicrotask(sync);
      })
    : null;
  observer?.observe(document.getElementById('modalBody') || document.body, {childList: true, subtree: true});

  sync();
  for (const delay of [0, 20, 80, 180, 400, 800, 1600, 3200]) setTimeout(sync, delay);

  window.TrainingLabelV3Anchor = {sync, build: '422506'};
})();
