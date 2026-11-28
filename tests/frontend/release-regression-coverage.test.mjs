import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

test('long-lived branch actually triggers the duplicate and material safety release tests', () => {
  const source = fs.readFileSync(new URL('../../.github/workflows/v42.25-release-regression.yml', import.meta.url), 'utf8');
  const push = source.match(/^  push:\r?\n([\s\S]*?)(?=^\S)/m)?.[1] || '';
  const branches = push.match(/    branches:\r?\n([\s\S]*?)(?=^    paths:)/m)?.[1] || '';
  const paths = push.match(/    paths:\r?\n([\s\S]*)/m)?.[1] || '';
  assert.ok(branches.includes('      - feature/external-algorithm-publishing'));
  for (const path of [
    'platform_core/training_compatibility.py',
    'platform_core/training_splits.py',
    'platform_core/training_recovery_api.py',
    'tests/unit/test_training_duplicate_conflicts.py',
    'tests/unit/test_material_reference_reasons.py',
    'tests/api/test_material_integrity.py',
    'tests/api/test_runtime_router_app_mount.py',
  ]) assert.ok(paths.includes(`      - ${path}`), `missing push path: ${path}`);
  const jobs = source.slice(source.indexOf('\njobs:'));
  for (const path of [
    'tests/unit/test_training_duplicate_conflicts.py',
    'tests/unit/test_material_reference_reasons.py',
    'tests/api/test_material_integrity.py',
    'tests/api/test_runtime_router_app_mount.py',
  ]) assert.ok(jobs.includes(path), `triggered release jobs must run: ${path}`);
  const hardening = fs.readFileSync(new URL('../../.github/workflows/training-final-validation-hardening.yml', import.meta.url), 'utf8');
  assert.match(hardening, /branches:\r?\n(?:      - [^\r\n]+\r?\n)*      - feature\/external-algorithm-publishing/);
});
