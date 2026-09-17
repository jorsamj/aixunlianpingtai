export const TRAINING_DRAFT_CONTROL_IDS = Object.freeze([
  'trV3Experiment',
  'trV3Validation',
  'tr429Priority',
  'trV3ResourceStrategy',
  'trV3Device',
  'trV3GpuPolicy',
]);

const CONTROL_ID_SET = new Set(TRAINING_DRAFT_CONTROL_IDS);

function numberValue(target) {
  const value = Number(target?.value);
  return Number.isFinite(value) ? value : null;
}

export function isTrainingDraftDirectControl(target) {
  return CONTROL_ID_SET.has(String(target?.id || ''));
}

export function trainingDraftControlPatch(target) {
  const id = String(target?.id || '');
  if (id === 'trV3Experiment') {
    const value = numberValue(target);
    return value == null ? null : {experimentPercent: value};
  }
  if (id === 'trV3Validation') {
    const value = numberValue(target);
    return value == null ? null : {validationPercent: value};
  }
  if (id === 'tr429Priority') {
    const value = numberValue(target);
    return value == null ? null : {priority: value};
  }
  if (id === 'trV3ResourceStrategy') {
    return {resource: {strategy: String(target?.value || 'auto')}};
  }
  if (id === 'trV3Device') {
    return {resource: {device: String(target?.value || 'auto')}};
  }
  if (id === 'trV3GpuPolicy') {
    return {resource: {gpuPolicy: String(target?.value || 'auto')}};
  }
  return null;
}

export function installTrainingDraftControls({trainingDraftRuntime} = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;
  if (window.__trainingDraftControlsInstalled) return window.TrainingDraftControlsRuntime || null;
  if (typeof trainingDraftRuntime?.update !== 'function') {
    throw new Error('TrainingDraftControlsRuntime missing canonical draft runtime');
  }

  let destroyed = false;
  let directWrites = 0;

  const apply = event => {
    if (destroyed) return;
    const target = event?.target;
    if (!isTrainingDraftDirectControl(target)) return;
    const patch = trainingDraftControlPatch(target);
    if (!patch) return;
    trainingDraftRuntime.update(patch);
    directWrites += 1;
  };

  document.addEventListener('input', apply);
  document.addEventListener('change', apply);

  const runtime = {
    build: 'training-draft-controls-422501',
    state: () => ({directWrites}),
    destroy() {
      destroyed = true;
      document.removeEventListener('input', apply);
      document.removeEventListener('change', apply);
      if (window.TrainingDraftControlsRuntime === runtime) window.TrainingDraftControlsRuntime = null;
      window.__trainingDraftControlsInstalled = false;
    },
  };

  window.TrainingDraftControlsRuntime = runtime;
  window.__trainingDraftControlsInstalled = true;
  return runtime;
}
