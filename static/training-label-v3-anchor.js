(() => {
  'use strict';
  if (window.__trainingLabelV3AnchorInstalled) return;
  window.__trainingLabelV3AnchorInstalled = true;

  function sync() {
    const summary = document.querySelector('.train-v3-summary');
    if (!summary) return false;
    let anchor = summary.parentElement?.querySelector(':scope > .training-label-v3-anchor');
    if (!anchor) {
      anchor = document.createElement('div');
      anchor.className = 'train429-data-summary training-label-v3-anchor';
      anchor.setAttribute('aria-hidden', 'true');
      anchor.style.display = 'none';
      summary.insertAdjacentElement('afterend', anchor);
    }
    window.TrainingLabelRuntime?.refresh?.();
    return true;
  }

  const observer = typeof MutationObserver !== 'undefined'
    ? new MutationObserver(() => {
        if (document.querySelector('.train-v3-summary')) queueMicrotask(sync);
      })
    : null;
  observer?.observe(document.getElementById('modalBody') || document.body, {childList: true, subtree: true});

  sync();
  for (const delay of [20, 80, 180, 400, 800, 1600]) setTimeout(sync, delay);

  window.TrainingLabelV3Anchor = {sync, build: '422505'};
})();
