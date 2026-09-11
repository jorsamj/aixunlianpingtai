from pathlib import Path

RUNTIME = Path('static/modules/training-draft-runtime.js')
MAIN = Path('static/main.mjs')
INDEX = Path('static/index.html')
DIRECT_TEST = Path('tests/frontend/training-draft-direct-write.test.mjs')
BROWSER_TEST = Path('tests/browser/training-label-selector.spec.mjs')


def replace_one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and new and text.count(new) == 1:
        print(f'{label}: already migrated')
        return text
    if count != 1:
        raise SystemExit(f'expected one {label}, found {count}')
    print(f'{label}: migrated')
    return text.replace(old, new, 1)


def remove_between(text: str, start: str, end: str, label: str) -> str:
    a = text.find(start)
    b = text.find(end, a + 1 if a >= 0 else 0)
    if a < 0:
        print(f'{label}: already absent')
        return text
    if b < 0:
        raise SystemExit(f'{label}: end marker missing')
    print(f'{label}: removed')
    return text[:a] + text[b:]


def migrate_runtime() -> None:
    text = RUNTIME.read_text(encoding='utf-8')
    if "build: 'training-draft-runtime-422512'" in text:
        print('runtime already migrated')
        return

    text = remove_between(
        text,
        'function checkboxInput(id) {',
        'export function installTrainingDraftRuntime',
        'unused settings input helpers',
    )

    text = remove_between(
        text,
        '  function settingsPatch(s) {',
        '  function directMutationFor(',
        'runtime settingsPatch',
    )

    direct_start = text.find('  function directMutationFor(')
    direct_end = text.find('  function wrapLegacyMutation(', direct_start + 1)
    if direct_start < 0 or direct_end < 0:
        raise SystemExit('directMutationFor block markers missing')
    replacement = """  function directMutationFor(name, args) {\n    if (name !== 'startAlgorithmTraining429') return null;\n    const algorithmId = String(args?.[0] || '').trim();\n    if (!algorithmId) return null;\n    return {\n      algorithmId,\n      materialIds: [],\n      testMaterialIds: [],\n      splitMode: 'random_test_from_training_pool',\n      experimentPercent: 20,\n      validationPercent: 20,\n      newLabelCodes: [],\n    };\n  }\n\n"""
    text = text[:direct_start] + replacement + text[direct_end:]
    text = replace_one(
        text,
        '      const patch = directMutationFor(name, args, state());',
        '      const patch = directMutationFor(name, args);',
        'direct mutation call',
    )
    old_list = """  for (const name of [\n    'startAlgorithmTraining429',\n    'confirmTrainMaterialPickerV3',\n    'setTrainSplitModeV3',\n    'saveTrainSettings428',\n  ]) wrapLegacyMutation(name);"""
    new_list = "  for (const name of ['startAlgorithmTraining429']) wrapLegacyMutation(name);"
    text = replace_one(text, old_list, new_list, 'wrapper list')
    text = replace_one(
        text,
        "    build: 'training-draft-runtime-422511',",
        "    build: 'training-draft-runtime-422512',",
        'runtime build',
    )

    for retired in ('confirmTrainMaterialPickerV3', 'setTrainSplitModeV3', 'saveTrainSettings428'):
        if retired in text:
            raise SystemExit(f'redundant wrapper token still remains in TrainingDraftRuntime: {retired}')
    if 'settingsPatch' in text or 'normalizedCache' in text or 'checkboxInput' in text:
        raise SystemExit('retired wrapper-only settings helpers remain')
    RUNTIME.write_text(text, encoding='utf-8')


def migrate_main_and_index() -> None:
    text = MAIN.read_text(encoding='utf-8')
    text = replace_one(
        text,
        "./modules/training-draft-runtime.js?v=422511",
        "./modules/training-draft-runtime.js?v=422512",
        'runtime import cache',
    )
    MAIN.write_text(text, encoding='utf-8')

    text = INDEX.read_text(encoding='utf-8')
    text = replace_one(
        text,
        '/static/main.mjs?v=42.25.40',
        '/static/main.mjs?v=42.25.41',
        'main outer cache',
    )
    INDEX.write_text(text, encoding='utf-8')


def migrate_direct_test() -> None:
    text = DIRECT_TEST.read_text(encoding='utf-8')
    if "redundant classic callbacks are no longer wrapped by TrainingDraftRuntime" in text:
        print('direct-write test already migrated')
        return

    text = replace_one(
        text,
        "import assert from 'node:assert/strict';\n",
        "import assert from 'node:assert/strict';\nimport {readFileSync} from 'node:fs';\n",
        'fs test import',
    )
    first = text.find("test('train-v3 material confirmation updates canonical draft before legacy callback runs'")
    third = text.find("test('opening a different algorithm resets canonical training selection before legacy start runs'", first + 1)
    fourth = text.find("test('training settings write canonical resource values before legacy save and are not overwritten afterward'", third + 1)
    if first < 0 or third < 0 or fourth < 0:
        raise SystemExit('direct-write test markers changed')

    source_test = r'''test('redundant classic callbacks are no longer wrapped by TrainingDraftRuntime because app.js owns canonical writes', () => {
  setupDom();
  const state = {
    trainingDraft: createTrainingDraft({algorithmId: 'alg-1', materialIds: ['a'], newLabelCodes: ['fire']}),
    algorithms: [{id: 'alg-1', versions: []}],
  };
  const original = {
    startAlgorithmTraining429() {},
    confirmTrainMaterialPickerV3() {},
    setTrainSplitModeV3() {},
    saveTrainSettings428() {},
  };
  globalThis.window = {fetch: async () => ({ok: true}), ...original};

  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});
  assert.notEqual(window.startAlgorithmTraining429, original.startAlgorithmTraining429);
  assert.equal(window.confirmTrainMaterialPickerV3, original.confirmTrainMaterialPickerV3);
  assert.equal(window.setTrainSplitModeV3, original.setTrainSplitModeV3);
  assert.equal(window.saveTrainSettings428, original.saveTrainSettings428);

  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const confirmAt = app.lastIndexOf('window.confirmTrainMaterialPickerV3=function(){');
  const splitAt = app.lastIndexOf('window.setTrainSplitModeV3=mode=>{');
  const saveAt = app.lastIndexOf('window.saveTrainSettings428=function(){');
  assert.ok(confirmAt >= 0 && app.slice(confirmAt, confirmAt + 1400).includes('TrainingDraftRuntime.update(patch)'));
  assert.ok(splitAt >= 0 && app.slice(splitAt, splitAt + 800).includes('TrainingDraftRuntime.update({splitMode'));
  assert.ok(saveAt >= 0 && app.slice(saveAt, saveAt + 1800).includes('TrainingDraftRuntime?.update?.({config:c})'));

  cleanup(runtime);
});

'''
    text = text[:first] + source_test + text[third:fourth]
    DIRECT_TEST.write_text(text, encoding='utf-8')


def migrate_browser_test() -> None:
    text = BROWSER_TEST.read_text(encoding='utf-8')
    text = replace_one(
        text,
        "training-draft-runtime-422511",
        "training-draft-runtime-422512",
        'browser runtime build',
    )
    BROWSER_TEST.write_text(text, encoding='utf-8')


def main() -> None:
    migrate_runtime()
    migrate_main_and_index()
    migrate_direct_test()
    migrate_browser_test()
    print('redundant TrainingDraft wrappers retired; startAlgorithmTraining429 wrapper intentionally retained')


if __name__ == '__main__':
    main()
