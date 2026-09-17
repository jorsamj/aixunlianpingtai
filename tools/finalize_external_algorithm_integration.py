from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"missing expected block in {path}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def append_once(path: str, marker: str, content: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + content.strip() + "\n", encoding="utf-8")


# Persist the exact analysis binding carried by the trained version.
replace_once(
    "platform_core/external_algorithm_publish.py",
    'str(algorithm.get("external_product_id") or ""), str(algorithm.get("external_analysis_id") or ""),\n                    str(version.get("version_name") or version.get("id") or ""), stamp, stamp,',
    'str(algorithm.get("external_product_id") or ""), str(version.get("external_analysis_id") or algorithm.get("external_analysis_id") or ""),\n                    str(version.get("version_name") or version.get("id") or ""), stamp, stamp,',
)

# Pure mapping helper used by detail rendering and contract tests.
replace_once(
    "static/modules/external-algorithm-platform.js",
    "export function normalizeExternalPlatformConfig(body = {}) {",
    '''export function externalAlgorithmMapping(algorithm = {}) {\n  const analyses = externalAnalysisOptions(algorithm);\n  return {\n    source: algorithmSourceLabel(algorithm),\n    productId: String(algorithm.external_product_id || ''),\n    categoryId: String(algorithm.external_category_id || ''),\n    analysisIds: analyses.map(row => row.id),\n    analysisNames: analyses.map(row => row.name || row.id),\n    active: algorithm.external_active !== false,\n    syncedAt: String(algorithm.external_last_synced_at || ''),\n  };\n}\n\nexport function normalizeExternalPlatformConfig(body = {}) {''',
)

# Detail panel decorator without wrapping the legacy detail renderer.
replace_once(
    "static/modules/external-algorithm-platform.js",
    "  function decorateAlgorithmCards() {",
    '''  function decorateAlgorithmDetail(algorithm) {\n    if (!isExternalAlgorithm(algorithm)) return;\n    const detail = document.querySelector('#modalBody .alg428-detail');\n    if (!detail || detail.querySelector('[data-external-algorithm-detail]')) return;\n    const mapping = externalAlgorithmMapping(algorithm);\n    const panel = document.createElement('section');\n    panel.dataset.externalAlgorithmDetail = '1';\n    panel.innerHTML = `<div class="alg428-version-head"><b>外部平台映射</b><span>${escapeHtml(mapping.source)}</span></div>\n      <dl class="report429-dl">\n        <dt>来源平台</dt><dd>${escapeHtml(mapping.source)}</dd>\n        <dt>Product ID</dt><dd>${escapeHtml(mapping.productId || '-')}</dd>\n        <dt>Category ID</dt><dd>${escapeHtml(mapping.categoryId || '-')}</dd>\n        <dt>Analysis ID</dt><dd>${escapeHtml(mapping.analysisIds.join('、') || '-')}</dd>\n        <dt>分析方式</dt><dd>${escapeHtml(mapping.analysisNames.join('、') || '-')}</dd>\n        <dt>同步状态</dt><dd>${mapping.active ? '正常' : '已下架'}</dd>\n        <dt>最近同步</dt><dd>${escapeHtml(timeText(mapping.syncedAt))}</dd>\n      </dl>`;\n    detail.insertBefore(panel, detail.children[1] || null);\n    if (!mapping.active) {\n      for (const button of detail.querySelectorAll('button')) {\n        if (/开始训练/.test(String(button.textContent || ''))) {\n          button.disabled = true;\n          button.title = '该算法已在新畅联下架，不能新建训练任务';\n        }\n      }\n    }\n  }\n\n  function decorateAlgorithmCards() {''',
)

# In external mode, the canonical filter is the synced ChangLian category tree;
# do not show the old local industry selector at the same time.
replace_once(
    "static/modules/external-algorithm-platform.js",
    "    const root = document.getElementById('alg412List');\n    if (!root) return;\n\n    for (const card of root.querySelectorAll('.alg428-card')) {",
    '''    const root = document.getElementById('alg412List');\n    if (!root) return;\n\n    const legacyIndustry = document.getElementById('alg412Industry');\n    if (legacyIndustry) {\n      if (externalMode()) {\n        if (legacyIndustry.value !== 'all') {\n          legacyIndustry.value = 'all';\n          algorithmListRuntime?.renderCards?.();\n          return;\n        }\n        legacyIndustry.hidden = true;\n      } else {\n        legacyIndustry.hidden = false;\n      }\n    }\n\n    for (const card of root.querySelectorAll('.alg428-card')) {''',
)

# Bind external detail decoration to the existing detail action.
replace_once(
    "static/modules/external-algorithm-platform.js",
    "      if (!isExternalAlgorithm(algorithm)) continue;\n      if (algorithm.external_active === false && title && !title.querySelector('[data-external-inactive]')) {",
    '''      if (!isExternalAlgorithm(algorithm)) continue;\n      const detailButton = [...card.querySelectorAll('button')].find(button =>\n        String(button.getAttribute('onclick') || '').includes("viewAlgorithm429(")\n      );\n      if (detailButton && !detailButton.dataset.externalDetailBound) {\n        detailButton.dataset.externalDetailBound = '1';\n        detailButton.addEventListener('click', () => setTimeout(() => decorateAlgorithmDetail(algorithm), 0));\n      }\n      if (algorithm.external_active === false && title && !title.querySelector('[data-external-inactive]')) {''',
)

# Remove external category selector when switching back to local mode.
replace_once(
    "static/modules/external-algorithm-platform.js",
    "      select.innerHTML = options.join('');\n      select.value = selectedCategoryId;\n    }\n\n    const create = document.querySelector('.alg428-toolbar [data-action=\"algorithm.create\"]');",
    '''      select.innerHTML = options.join('');\n      select.value = selectedCategoryId;\n    }\n    if (toolbar && !externalMode()) {\n      toolbar.querySelector('[data-external-category-filter]')?.remove();\n      selectedCategoryId = '';\n    }\n\n    const create = document.querySelector('.alg428-toolbar [data-action="algorithm.create"]');''',
)

# Frontend helper contract.
replace_once(
    "tests/frontend/external-algorithm-platform.test.mjs",
    "  algorithmSourceLabel,\n  externalAnalysisOptions,",
    "  algorithmSourceLabel,\n  externalAlgorithmMapping,\n  externalAnalysisOptions,",
)
append_once(
    "tests/frontend/external-algorithm-platform.test.mjs",
    "external mapping exposes provider ids",
    '''test('external mapping exposes provider ids and sync state', () => {\n  const mapping = externalAlgorithmMapping({\n    source_type: 'EXTERNAL',\n    provider_type: 'CHANG_LIAN',\n    external_product_id: 'p-1',\n    external_category_id: 'c-1',\n    external_active: false,\n    external_last_synced_at: '2026-09-17T06:30:00Z',\n    external_analyses: [\n      {analysis_id: 'a-1', analysis_name: '视觉分析 A'},\n      {analysis_id: 'a-2', analysis_name: '视觉分析 B'},\n    ],\n  });\n  assert.equal(mapping.source, '新畅联');\n  assert.equal(mapping.productId, 'p-1');\n  assert.equal(mapping.categoryId, 'c-1');\n  assert.deepEqual(mapping.analysisIds, ['a-1', 'a-2']);\n  assert.equal(mapping.active, false);\n  assert.equal(mapping.syncedAt, '2026-09-17T06:30:00Z');\n});''',
)

# Publishing contract: the durable publication must preserve the per-training analysis binding.
append_once(
    "tests/unit/test_external_algorithm_publish.py",
    "test_publication_persists_training_analysis_binding",
    '''def test_publication_persists_training_analysis_binding(tmp_path: Path):\n    FakePublishingClient.reset()\n    memory = MemorySecretStore()\n    _configure_external(tmp_path, memory)\n    _seed_external_algorithm(tmp_path)\n    algorithms = list_algorithms(_algorithms_file(tmp_path, "p1"))\n    algorithms[0]["versions"][0]["external_analysis_id"] = "analysis-2"\n    save_algorithms(_algorithms_file(tmp_path, "p1"), algorithms)\n    _seed_conversion(tmp_path)\n    service = _service(tmp_path, memory)\n\n    result = service.publish(project_id="p1", algorithm_id="a1", version_id="v1")\n\n    assert result["publication"]["external_analysis_id"] == "analysis-2"\n''',
)

print('final external integration refinements applied')
