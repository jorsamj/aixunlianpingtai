import {installTrainingCheckpointResumeUI} from './modules/training-checkpoint-resume-ui.js?v=422531';

let installed = false;

function install() {
  if (installed || typeof state === 'undefined') return null;
  if (!window.TrainingTaskRuntime || !window.TrainingRecoveryRuntime) return null;
  installed = true;
  return installTrainingCheckpointResumeUI({
    getState: () => state,
    notify: message => window.toast?.(message),
  });
}

if (!install()) {
  window.addEventListener('DOMContentLoaded', () => {
    if (!install()) window.setTimeout(install, 0);
  }, {once: true});
}
