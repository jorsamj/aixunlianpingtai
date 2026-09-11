from pathlib import Path

RUNTIME = Path('static/modules/training-draft-runtime.js')
MAIN = Path('static/main.mjs')
INDEX = Path('static/index.html')
DIRECT_TEST = Path('tests/frontend/training-draft-direct-write.test.mjs')
BROWSER_TEST = Path('tests/browser/training-label-selector.spec.mjs')
FRONTEND_CI = Path('.github/workflows/frontend-runtime-stabilization.yml')


def replace_one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and new and new in text:
        print(f'{label}: already migrated')
        return text
    if count != 1:
        raise SystemExit(f'expected one {label}, found {count}')
    print(f'{label}: migrated')
    return text.replace(old, new, 1)


def migrate_runtime() -> None:
    text = RUNTIME.read_text(encoding='utf-8')
    if "build: 'training-draft-runtime-422513'" in text:
        print('TrainingDraftRuntime already wrapper-free')
        return
    text = replace_one(text, '  let directWrites = 0;\n', '', 'directWrites counter')
    text = replace_one(text, '  const mutationWrappers = [];\n', '', 'mutation wrapper registry')
    start = text.find('  function directMutationFor(name, args) {')
    end = text.find('  sync();', start + 1)
    if start < 0 or end < 0:
        raise SystemExit('legacy mutation wrapper block markers missing')
    text = text[:start] + text[end:]
    text = replace_one(
        text,
        "    build: 'training-draft-runtime-422512',",
        "    build: 'training-draft-runtime-422513',",
        'TrainingDraftRuntime build',
    )
    text = replace_one(
        text,
        '    state() { return {directWrites, directControlSkips, initializationCount, networkOwner: false}; },',
        '    state() { return {directControlSkips, initializationCount, networkOwner: false, classicWrapperOwner: false}; },',
        'runtime diagnostic state',
    )
    wrapper_cleanup = """      for (const {name, original, wrapped} of mutationWrappers) {\n        if (window[name] === wrapped) window[name] = original;\n      }\n      mutationWrappers.length = 0;\n"""
    text = replace_one(text, wrapper_cleanup, '', 'destroy wrapper restoration')
    forbidden = ('startAlgorithmTraining429', 'wrapLegacyMutation', 'directMutationFor', 'mutationWrappers', 'directWrites', '__trainingDraftMutationWrapped')
    found = [token for token in forbidden if token in text]
    if found:
        raise SystemExit(f'wrapper ownership remains in TrainingDraftRuntime: {found}')
    RUNTIME.write_text(text, encoding='utf-8')


def migrate_caches() -> None:
    text = MAIN.read_text(encoding='utf-8')
    text = replace_one(text, "./modules/training-draft-runtime.js?v=422512", "./modules/training-draft-runtime.js?v=422513", 'TrainingDraft import cache')
    MAIN.write_text(text, encoding='utf-8')
    text = INDEX.read_text(encoding='utf-8')
    text = replace_one(text, '/static/main.mjs?v=42.25.43', '/static/main.mjs?v=42.25.44', 'main outer cache')
    INDEX.write_text(text, encoding='utf-8')
    text = BROWSER_TEST.read_text(encoding='utf-8')
    text = replace_one(text, 'training-draft-runtime-422512', 'training-draft-runtime-422513', 'browser Draft build')
    BROWSER_TEST.write_text(text, encoding='utf-8')


def migrate_direct_test() -> None:
    DIRECT_TEST.write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  createTrainingDraft,
  trainingInheritanceFromAlgorithm,
} from '../../static/modules/training-draft.js';
import {installTrainingDraftRuntime} from '../../static/modules/training-draft-runtime.js';

function dependencies() {
  return {createTrainingDraft, trainingInheritanceFromAlgorithm};
}

function setupDom() {
  globalThis.document = {
    addEventListener() {},
    removeEventListener() {},
    getElementById() { return null; },
  };
}

function cleanup(runtime) {
  runtime?.destroy();
  delete globalThis.window;
  delete globalThis.document;
}

test('TrainingDraftRuntime is wrapper-free and leaves classic entrypoints untouched', () => {
  setupDom();
  const state = {
    trainingDraft: createTrainingDraft({algorithmId: 'alg-1', materialIds: ['a'], newLabelCodes: ['fire']}),
    algorithms: [{id: 'alg-1', versions: []}],
  };
  const originalStart = function startAlgorithmTraining429() {};
  const originalConfirm = function confirmTrainMaterialPickerV3() {};
  const originalSplit = function setTrainSplitModeV3() {};
  const originalSave = function saveTrainSettings428() {};
  globalThis.window = {
    fetch: async () => ({ok: true}),
    startAlgorithmTraining429: originalStart,
    confirmTrainMaterialPickerV3: originalConfirm,
    setTrainSplitModeV3: originalSplit,
    saveTrainSettings428: originalSave,
  };

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  assert.equal(window.startAlgorithmTraining429, originalStart);
  assert.equal(window.confirmTrainMaterialPickerV3, originalConfirm);
  assert.equal(window.setTrainSplitModeV3, originalSplit);
  assert.equal(window.saveTrainSettings428, originalSave);
  assert.equal(runtime.state().classicWrapperOwner, false);
  assert.equal(runtime.state().networkOwner, false);

  const source = readFileSync(new URL('../../static/modules/training-draft-runtime.js', import.meta.url), 'utf8');
  for (const token of ['wrapLegacyMutation', 'directMutationFor', 'mutationWrappers', 'startAlgorithmTraining429']) {
    assert.equal(source.includes(token), false);
  }

  cleanup(runtime);
});

test('app.js visible training entrypoint owns canonical reset before rendering the modal', () => {
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const canonicalOwner = app.indexOf('window.startAlgorithmTraining429=function(aid){const a=');
  const earlyAlias = app.indexOf('window.startAlgorithmTraining423=window.startAlgorithmTraining429;', canonicalOwner);
  assert.ok(canonicalOwner >= 0 && earlyAlias > canonicalOwner);
  const ownerSource = app.slice(canonicalOwner, earlyAlias);
  const canonicalWrite = ownerSource.indexOf('window.TrainingDraftRuntime?.update?.({algorithmId:String(aid),materialIds:[],testMaterialIds:[],splitMode:\'random_test_from_training_pool\',experimentPercent:20,validationPercent:20,newLabelCodes:[]})');
  const modalOpen = ownerSource.indexOf('modal(`训练 · ${a.name}`');
  assert.ok(canonicalWrite >= 0 && modalOpen > canonicalWrite);

  // The current stable algorithm renderer is the user-visible training entrypoint.
  // It must call startAlgorithmTraining429, never the retired 423/425 chain.
  const stableCards = app.lastIndexOf('window.renderAlg412=function(){');
  const stablePage = app.lastIndexOf('window.renderAlgorithms423=function(){');
  assert.ok(stableCards >= 0 && stablePage > stableCards);
  const cardSource = app.slice(stableCards, stablePage);
  assert.match(cardSource, /startAlgorithmTraining429\('\$\{a\.id\}'\)/);
  assert.equal(cardSource.includes("startAlgorithmTraining423('${a.id}')"), false);
});

test('final classic picker split and settings actions own their canonical writes directly', () => {
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const confirmAt = app.lastIndexOf('window.confirmTrainMaterialPickerV3=function(){');
  const splitAt = app.lastIndexOf('window.setTrainSplitModeV3=mode=>{');
  const saveAt = app.lastIndexOf('window.saveTrainSettings428=function(){');
  assert.ok(confirmAt >= 0 && app.slice(confirmAt, confirmAt + 1400).includes('TrainingDraftRuntime.update(patch)'));
  assert.ok(splitAt >= 0 && app.slice(splitAt, splitAt + 800).includes('TrainingDraftRuntime.update({splitMode'));
  assert.ok(saveAt >= 0 && app.slice(saveAt, saveAt + 1800).includes('TrainingDraftRuntime?.update?.({config:c})'));
});
''', encoding='utf-8')
    print('direct-write tests migrated to wrapper-free owner contract')


def migrate_ci_guard() -> None:
    text = FRONTEND_CI.read_text(encoding='utf-8')
    if 'TrainingDraft classic wrapper guard' in text:
        print('permanent Draft wrapper guard already present')
        return
    anchor = """      - name: Canonical training network owner guard\n        run: |\n          if grep -n '/train/start' static/app.js; then\n            echo \"classic app.js must not own /train/start; TrainingSubmitRuntime is the sole network owner\" >&2\n            exit 1\n          fi\n"""
    guard = anchor + """      - name: TrainingDraft classic wrapper guard\n        run: |\n          for token in startAlgorithmTraining429 wrapLegacyMutation directMutationFor mutationWrappers __trainingDraftMutationWrapped; do\n            if grep -n \"$token\" static/modules/training-draft-runtime.js; then\n              echo \"TrainingDraftRuntime must stay wrapper-free; found $token\" >&2\n              exit 1\n            fi\n          done\n"""
    text = replace_one(text, anchor, guard, 'permanent TrainingDraft wrapper guard')
    FRONTEND_CI.write_text(text, encoding='utf-8')


def main() -> None:
    migrate_runtime()
    migrate_caches()
    migrate_direct_test()
    migrate_ci_guard()
    print('final TrainingDraft classic wrapper retired')


if __name__ == '__main__':
    main()
