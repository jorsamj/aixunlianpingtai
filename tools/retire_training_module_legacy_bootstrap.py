from pathlib import Path

DRAFT = Path('static/modules/training-draft.js')
RUNTIME = Path('static/modules/training-draft-runtime.js')
LABELS = Path('static/modules/training-labels.js')
MAIN = Path('static/main.mjs')
DRAFT_TEST = Path('tests/frontend/training-draft.test.mjs')
RUNTIME_TEST = Path('tests/frontend/training-draft-runtime.test.mjs')
DIRECT_TEST = Path('tests/frontend/training-draft-direct-write.test.mjs')
GENERIC_TEST = Path('tests/frontend/training-draft-generic-sync.test.mjs')
LABEL_TEST = Path('tests/frontend/training-labels.test.mjs')

RETIRED = ('trainSplitV3', 'trainingLabelSelected', 'train429Selected', 'train428AlgorithmId', 'train428Config')


def replace_one(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'expected one {label}, found {count}')
    return text.replace(old, new, 1)


def migrate_draft() -> None:
    text = DRAFT.read_text(encoding='utf-8')
    start = text.find('export function trainingDraftFromLegacyState(')
    end = text.find('export function trainingDraftToRequest(', start + 1)
    if start < 0 or end < 0:
        raise SystemExit('trainingDraftFromLegacyState block missing')
    text = text[:start] + text[end:]
    for token in RETIRED:
        if token in text:
            raise SystemExit(f'{token} remains in training-draft.js')
    DRAFT.write_text(text, encoding='utf-8')


def migrate_runtime() -> None:
    text = RUNTIME.read_text(encoding='utf-8')
    text = replace_one(text, '  trainingDraftFromLegacyState,\n', '', 'legacy dependency parameter')
    text = replace_one(
        text,
        "  if (![createTrainingDraft, trainingDraftFromLegacyState, trainingInheritanceFromAlgorithm].every(fn => typeof fn === 'function')) {",
        "  if (![createTrainingDraft, trainingInheritanceFromAlgorithm].every(fn => typeof fn === 'function')) {",
        'dependency validation',
    )
    text = replace_one(text, '  let legacyBootstrapCount = 0;\n', '  let initializationCount = 0;\n', 'initialization counter')
    text = replace_one(
        text,
        '  function inheritanceFor(s, algorithmId = s.trainingDraft?.algorithmId || s.train428AlgorithmId) {',
        '  function inheritanceFor(s, algorithmId = s.trainingDraft?.algorithmId) {',
        'inheritance canonical algorithm',
    )
    retire_start = text.find('  function retireOldMirrors(s) {')
    retire_end = text.find('  function commitDraft(', retire_start + 1)
    if retire_start < 0 or retire_end < 0:
        raise SystemExit('retireOldMirrors block missing')
    text = text[:retire_start] + text[retire_end:]
    text = replace_one(text, '    retireOldMirrors(s);\n', '', 'retired mirror mutation')
    old_bootstrap = """  function bootstrapFromLegacy(s) {\n    const inheritance = inheritanceFor(s);\n    const draft = withLiveControls(trainingDraftFromLegacyState(s, {\n      inheritedLabelCodes: inheritance.codes,\n      inheritancePending: inheritance.legacy,\n      baseVersionId: inheritance.versionId,\n    }));\n    legacyBootstrapCount += 1;\n    return {draft, inheritance};\n  }\n"""
    new_bootstrap = """  function initializeCanonical(s) {\n    const draft = withLiveControls(createTrainingDraft());\n    const inheritance = inheritanceFor(s, draft.algorithmId);\n    initializationCount += 1;\n    return {draft, inheritance};\n  }\n"""
    text = replace_one(text, old_bootstrap, new_bootstrap, 'canonical initializer')
    text = text.replace('bootstrapFromLegacy(s)', 'initializeCanonical(s)')
    text = replace_one(text, "    build: 'training-draft-runtime-422509',", "    build: 'training-draft-runtime-422511',", 'runtime build')
    text = replace_one(
        text,
        '    state() { return {directWrites, directControlSkips, legacyBootstrapCount, networkOwner: false}; },',
        '    state() { return {directWrites, directControlSkips, initializationCount, networkOwner: false}; },',
        'runtime diagnostic state',
    )
    for token in RETIRED:
        if token in text:
            raise SystemExit(f'{token} remains in training-draft-runtime.js')
    if 'trainingDraftFromLegacyState' in text or 'bootstrapFromLegacy' in text or 'legacyBootstrapCount' in text:
        raise SystemExit('legacy bootstrap terminology remains in training-draft-runtime.js')
    RUNTIME.write_text(text, encoding='utf-8')


def migrate_labels() -> None:
    text = LABELS.read_text(encoding='utf-8')
    old_material = """  if (preferV429) {\n    const draft = state?.trainingDraft;\n    if (draft && String(draft?.algorithmId || '').trim()) {\n      return unique(draft?.materialIds || []);\n    }\n    return unique([...(state?.train429Selected || new Set())]);\n  }"""
    new_material = """  if (preferV429) {\n    return unique(state?.trainingDraft?.materialIds || []);\n  }"""
    text = replace_one(text, old_material, new_material, 'canonical v3 material source')
    old_algorithm = """  const canonical = String(state?.trainingDraft?.algorithmId || '').trim();\n  const fixed = canonical || String(state?.train428AlgorithmId || '').trim();\n  const fallback = document.getElementById('tr425AssetAlg')?.value\n    || document.getElementById('train423Asset')?.value\n    || '';\n  const id = fixed || String(fallback || '').trim();"""
    new_algorithm = """  const canonical = String(state?.trainingDraft?.algorithmId || '').trim();\n  const fallback = document.getElementById('tr425AssetAlg')?.value\n    || document.getElementById('train423Asset')?.value\n    || '';\n  const id = canonical || String(fallback || '').trim();"""
    text = replace_one(text, old_algorithm, new_algorithm, 'canonical algorithm source')
    for token in RETIRED:
        if token in text:
            raise SystemExit(f'{token} remains in training-labels.js')
    LABELS.write_text(text, encoding='utf-8')


def migrate_main() -> None:
    text = MAIN.read_text(encoding='utf-8')
    text = replace_one(
        text,
        "import {createTrainingDraft, trainingDraftFromLegacyState, trainingDraftToRequest, trainingInheritanceFromAlgorithm} from './modules/training-draft.js?v=422505';",
        "import {createTrainingDraft, trainingDraftToRequest, trainingInheritanceFromAlgorithm} from './modules/training-draft.js?v=422506';",
        'training draft import',
    )
    text = replace_one(text, "import {installTrainingLabelRuntime} from './modules/training-labels.js?v=422507';", "import {installTrainingLabelRuntime} from './modules/training-labels.js?v=422508';", 'training label cache')
    text = replace_one(text, "import {installTrainingDraftRuntime} from './modules/training-draft-runtime.js?v=422510';", "import {installTrainingDraftRuntime} from './modules/training-draft-runtime.js?v=422511';", 'training draft runtime cache')
    text = replace_one(text, '  trainingDraftFromLegacyState,\n', '', 'runtime legacy dependency')
    text = replace_one(
        text,
        '  trainingDraft: {createTrainingDraft, trainingDraftFromLegacyState, trainingDraftToRequest, trainingInheritanceFromAlgorithm},',
        '  trainingDraft: {createTrainingDraft, trainingDraftToRequest, trainingInheritanceFromAlgorithm},',
        'PlatformCore legacy adapter export',
    )
    if 'trainingDraftFromLegacyState' in text:
        raise SystemExit('legacy adapter remains in main.mjs')
    MAIN.write_text(text, encoding='utf-8')


def migrate_draft_test() -> None:
    text = DRAFT_TEST.read_text(encoding='utf-8')
    text = replace_one(text, '  trainingDraftFromLegacyState,\n', '', 'draft test legacy import')
    start = text.find("test('legacy adapter keeps split ownership canonical and ignores retired split mirror values'")
    end = text.find("test('request uses new labels for the task while inherited labels remain in effective schema'", start + 1)
    if start < 0 or end < 0:
        raise SystemExit('legacy draft test range missing')
    replacement = """test('empty canonical draft has safe defaults and no hidden legacy state dependency', () => {\n  const draft = createTrainingDraft();\n  assert.equal(draft.algorithmId, '');\n  assert.deepEqual(draft.materialIds, []);\n  assert.deepEqual(draft.testMaterialIds, []);\n  assert.deepEqual(draft.newLabelCodes, []);\n  assert.deepEqual(draft.inheritedLabelCodes, []);\n  assert.equal(draft.splitMode, 'random_test_from_training_pool');\n  assert.equal(draft.experimentPercent, 20);\n  assert.equal(draft.validationPercent, 20);\n  assert.deepEqual(draft.resource, {strategy: 'auto', device: 'auto', gpuPolicy: 'auto', batch: null, workers: null, cache: null});\n  assert.equal(draft.priority, 50);\n});\n\n"""
    text = text[:start] + replacement + text[end:]
    DRAFT_TEST.write_text(text, encoding='utf-8')


def remove_legacy_dependency_from_test(path: Path) -> str:
    text = path.read_text(encoding='utf-8')
    text = replace_one(text, '  trainingDraftFromLegacyState,\n', '', f'{path.name} legacy import')
    text = replace_one(text, '    trainingDraftFromLegacyState,\n', '', f'{path.name} legacy dependency')
    return text


def migrate_runtime_test() -> None:
    text = remove_legacy_dependency_from_test(RUNTIME_TEST)
    text = text.replace('runtime.state().legacyBootstrapCount', 'runtime.state().initializationCount')
    text = replace_one(text, "test('canonical draft wins over stale legacy mirrors and retired mirrors stay deleted', () => {", "test('canonical draft ignores stale retired mirror-shaped fields without mutating them', () => {", 'canonical contamination test title')
    text = replace_one(text, "  assert.equal(Object.hasOwn(state, 'trainSplitV3'), false);\n  assert.equal(Object.hasOwn(state, 'trainingLabelSelected'), false);", "  assert.deepEqual([...state.trainSplitV3.train], ['legacy-wrong']);\n  assert.deepEqual([...state.trainingLabelSelected], ['legacy-label']);", 'retired fixture immutability assertions')
    start = text.find("test('legacy state is consumed once only when canonical draft is absent'")
    end = text.find("test('TrainingDraftRuntime never intercepts train-start fetches'", start + 1)
    if start < 0 or end < 0:
        raise SystemExit('runtime legacy bootstrap test range missing')
    replacement = """test('missing draft initializes empty canonical state and ignores retired mirror-shaped fields', () => {\n  setupDom({tr429Priority: '40'});\n  const state = {\n    train428AlgorithmId: 'legacy-alg',\n    train429Selected: new Set(['legacy-a', 'legacy-b']),\n    train428Config: {device: 'cpu', batch: 8},\n    algorithms: [{id: 'legacy-alg', versions: []}],\n  };\n  globalThis.window = {fetch: async () => ({ok: true})};\n  const runtime = installTrainingDraftRuntime({getState: () => state, ...dependencies()});\n  assert.equal(state.trainingDraft.algorithmId, '');\n  assert.deepEqual(state.trainingDraft.materialIds, []);\n  assert.equal(state.trainingDraft.priority, 40);\n  assert.equal(state.trainingDraft.resource.device, 'auto');\n  assert.equal(runtime.state().initializationCount, 1);\n  state.train429Selected = new Set(['changed-legacy']);\n  state.train428AlgorithmId = 'changed-legacy-alg';\n  state.train428Config = {device: 'changed-legacy-device'};\n  runtime.sync();\n  assert.equal(state.trainingDraft.algorithmId, '');\n  assert.deepEqual(state.trainingDraft.materialIds, []);\n  assert.equal(state.trainingDraft.resource.device, 'auto');\n  assert.equal(runtime.state().initializationCount, 1);\n  cleanup(runtime);\n});\n\n"""
    text = text[:start] + replacement + text[end:]
    RUNTIME_TEST.write_text(text, encoding='utf-8')


def migrate_direct_test() -> None:
    text = remove_legacy_dependency_from_test(DIRECT_TEST)
    text = text.replace("  assert.equal(Object.hasOwn(state, 'trainSplitV3'), false);", "  assert.ok(state.trainSplitV3 instanceof Object);", 3)
    text = text.replace("  assert.equal(Object.hasOwn(state, 'trainingLabelSelected'), false);\n", "", 2)
    DIRECT_TEST.write_text(text, encoding='utf-8')


def migrate_generic_test() -> None:
    text = remove_legacy_dependency_from_test(GENERIC_TEST)
    GENERIC_TEST.write_text(text, encoding='utf-8')


def migrate_label_test() -> None:
    text = LABEL_TEST.read_text(encoding='utf-8')
    start = text.find("test('current training modal falls back to legacy selected materials before canonical draft exists'")
    end = text.find("test('previous version labels are inherited and only material labels are selectable additions'", start + 1)
    if start < 0 or end < 0:
        raise SystemExit('legacy material fallback test range missing')
    replacement = """test('current training modal returns no materials before canonical draft exists', () => {\n  const state = {train429Selected: new Set(['retired-legacy-value'])};\n  assert.deepEqual(selectedTrainingMaterialIds(state, {preferV429: true}), []);\n});\n\n"""
    text = text[:start] + replacement + text[end:]
    LABEL_TEST.write_text(text, encoding='utf-8')


def main() -> None:
    migrate_draft()
    migrate_runtime()
    migrate_labels()
    migrate_main()
    migrate_draft_test()
    migrate_runtime_test()
    migrate_direct_test()
    migrate_generic_test()
    migrate_label_test()
    for path in (DRAFT, RUNTIME, LABELS):
        body = path.read_text(encoding='utf-8')
        found = [token for token in RETIRED if token in body]
        if found:
            raise SystemExit(f'{path}: retired mirrors remain: {found}')
    print('canonical-only training module bootstrap migration complete')


if __name__ == '__main__':
    main()
