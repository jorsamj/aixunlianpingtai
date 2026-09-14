from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}: {old[:120]!r}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Backend: keep the explicit string contract, but accept a stale/legacy browser
# that still submits a JSON boolean and normalize it before Pydantic field validation.
replace_once(
    "app.py",
    '''        if isinstance(value, dict):\n            value = {**value, "device": normalize_training_device(value.get("device", "auto"))}\n        return value\n''',
    '''        if isinstance(value, dict):\n            value = dict(value)\n            if isinstance(value.get("cache"), bool):\n                value["cache"] = "True" if value["cache"] else "False"\n            value["device"] = normalize_training_device(value.get("device", "auto"))\n        return value\n''',
)

# Canonical browser request: draft state may remain boolean, but the HTTP request
# must match TrainReq/cache and train_worker CLI's False/True/ram/disk string contract.
replace_once(
    "static/modules/training-draft.js",
    '''function numberOr(value, fallback) {\n  const parsed = Number(value);\n  return Number.isFinite(parsed) ? parsed : fallback;\n}\n\n''',
    '''function numberOr(value, fallback) {\n  const parsed = Number(value);\n  return Number.isFinite(parsed) ? parsed : fallback;\n}\n\nfunction trainingCacheRequestValue(value) {\n  if (value === true) return 'True';\n  if (value === false || value === null || value === undefined || value === '') return 'False';\n  const normalized = String(value).trim().toLowerCase();\n  if (['true', '1', 'yes', 'on'].includes(normalized)) return 'True';\n  if (['false', '0', 'no', 'off', 'none'].includes(normalized)) return 'False';\n  if (normalized === 'ram' || normalized === 'disk') return normalized;\n  throw new Error('Cache 只支持 False / True / ram / disk');\n}\n\n''',
)
replace_once(
    "static/modules/training-draft.js",
    '''  if (normalized.resource.cache != null) request.cache = normalized.resource.cache;\n  return request;\n''',
    '''  if (normalized.resource.cache != null) request.cache = normalized.resource.cache;\n  if (Object.hasOwn(request, 'cache')) request.cache = trainingCacheRequestValue(request.cache);\n  return request;\n''',
)

# Unit contracts.
replace_once(
    "tests/frontend/training-draft.test.mjs",
    '''  assert.equal(request.cache, false);\n  assert.equal(request.queue_priority, 30);\n''',
    '''  assert.equal(request.cache, 'False');\n  assert.equal(request.queue_priority, 30);\n''',
)
replace_once(
    "tests/frontend/training-draft.test.mjs",
    '''test('legacy inherited schema pending allows backend snapshot recovery without frontend guessing', () => {\n''',
    '''test('request serializes cache into the backend string contract', () => {\n  const base = {algorithmId: 'alg-1', materialIds: ['a', 'b'], newLabelCodes: ['fire']};\n  for (const [cache, expected] of [[false, 'False'], [true, 'True'], ['False', 'False'], ['True', 'True'], ['ram', 'ram'], ['disk', 'disk']]) {\n    const request = trainingDraftToRequest(createTrainingDraft({...base, resource: {cache}}));\n    assert.equal(request.cache, expected);\n  }\n});\n\ntest('legacy inherited schema pending allows backend snapshot recovery without frontend guessing', () => {\n''',
)
replace_once(
    "tests/frontend/training-submit.test.mjs",
    '''  assert.equal(payload.cache, false);\n  assert.equal(payload.model, 'custom.pt');\n''',
    '''  assert.equal(payload.cache, 'False');\n  assert.equal(payload.model, 'custom.pt');\n''',
)
replace_once(
    "tests/frontend/training-submit.test.mjs",
    '''  assert.equal(sent.queue_priority, 7);\n  assert.equal(reloaded, 1);\n''',
    '''  assert.equal(sent.queue_priority, 7);\n  assert.equal(sent.cache, 'False');\n  assert.equal(reloaded, 1);\n''',
)
replace_once(
    "tests/browser/training-label-selector.spec.mjs",
    '''  expect(submitted.cache).toBe(false);\n''',
    '''  expect(submitted.cache).toBe('False');\n''',
)
replace_once(
    "tests/api/test_training_request.py",
    '''def test_training_job_locks_snapshot_base_and_requested_parameters(client, seeded_project, monkeypatch):\n''',
    '''def test_training_request_normalizes_legacy_boolean_cache_before_string_validation():\n    import app as app_module\n\n    assert app_module.TrainReq(cache=False).cache == "False"\n    assert app_module.TrainReq(cache=True).cache == "True"\n    assert app_module.TrainReq(cache="ram").cache == "ram"\n    assert app_module.TrainReq(cache="disk").cache == "disk"\n\n\ndef test_training_job_locks_snapshot_base_and_requested_parameters(client, seeded_project, monkeypatch):\n''',
)

# Cache bust the changed canonical draft module and then the main module itself.
replace_once(
    "static/main.mjs",
    "./modules/training-draft.js?v=422506",
    "./modules/training-draft.js?v=422507",
)
replace_once(
    "static/index.html",
    "/static/main.mjs?v=42.25.97",
    "/static/main.mjs?v=42.25.98",
)

print("patched training cache request contract")
