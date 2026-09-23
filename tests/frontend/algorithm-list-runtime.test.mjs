import test from 'node:test';
import assert from 'node:assert/strict';

import {
  algorithmCategoryColumns,
  algorithmCategorySearch,
  algorithmListSearchMatch,
  algorithmVersionMap50,
  installAlgorithmListRuntime,
} from '../../static/modules/algorithm-list-runtime.js';

function response(body) {
  return {
    ok: true,
    status: 200,
    async json() { return body; },
    async text() { return JSON.stringify(body); },
  };
}

function cleanup() {
  delete globalThis.window;
  delete globalThis.document;
}

test('algorithm expand/collapse is local-only and never fetches the algorithm list', () => {
  const state = {
    page: '算法列表',
    project: {id: 'p1'},
    algorithms: [{id: 'a1', versions: [{id: 'v1'}]}],
    jobs: [],
    alg428Expanded: {},
  };
  let requests = 0;
  globalThis.window = {
    fetch: async () => { requests += 1; return response({items: []}); },
  };

  const runtime = installAlgorithmListRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });

  assert.equal(window.toggleAlgorithm412('a1'), true);
  assert.equal(state.alg428Expanded.a1, true);
  assert.equal(requests, 0);

  assert.equal(window.toggleAlgorithm428('a1'), false);
  assert.equal(state.alg428Expanded.a1, false);
  assert.equal(requests, 0);

  runtime.destroy();
  cleanup();
});

test('focused refresh fetches only algorithms and jobs and updates the visible cards', async () => {
  const state = {
    page: '算法列表',
    project: {id: 'project 1'},
    algorithms: [{id: 'old'}],
    jobs: [{id: 'old-job'}],
    alg428Expanded: {},
  };
  const urls = [];
  globalThis.window = {
    async fetch(url) {
      urls.push(url);
      if (url.includes('/algorithms')) return response({items: [{id: 'a2', name: '烟火检测', versions: []}]});
      if (url.endsWith('/jobs')) return response([{id: 'j2', status: 'running'}]);
      throw new Error(`unexpected URL: ${url}`);
    },
  };

  const runtime = installAlgorithmListRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  const result = await runtime.refresh();

  assert.deepEqual(urls.sort(), [
    '/api/projects/project%201/jobs',
    '/api/v12/projects/project%201/algorithms',
  ]);
  assert.deepEqual(state.algorithms.map(row => row.id), ['a2']);
  assert.deepEqual(state.jobs.map(row => row.id), ['j2']);
  assert.equal(result.cached, false);
  assert.equal(result.stale, false);

  runtime.destroy();
  cleanup();
});

test('concurrent focused refreshes share one request pair', async () => {
  const state = {
    page: '算法列表',
    project: {id: 'p1'},
    algorithms: [],
    jobs: [],
    alg428Expanded: {},
  };
  const urls = [];
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  globalThis.window = {
    async fetch(url) {
      urls.push(url);
      await gate;
      return url.includes('/algorithms') ? response({items: []}) : response([]);
    },
    renderAlg412: () => {},
  };

  const runtime = installAlgorithmListRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  const first = runtime.refresh();
  const second = runtime.refresh();
  await Promise.resolve();

  assert.equal(urls.length, 2);
  release();
  await Promise.all([first, second]);
  assert.equal(urls.length, 2);

  runtime.destroy();
  cleanup();
});

test('minimum refresh age can reuse fresh algorithm state without network traffic', async () => {
  const state = {
    page: '算法列表',
    project: {id: 'p1'},
    algorithms: [],
    jobs: [],
    alg428Expanded: {},
  };
  let requests = 0;
  globalThis.window = {
    async fetch(url) {
      requests += 1;
      return url.includes('/algorithms') ? response({items: []}) : response([]);
    },
    renderAlg412: () => {},
  };

  const runtime = installAlgorithmListRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  await runtime.refresh({render: false});
  const second = await runtime.refresh({render: false, minAgeMs: 10_000});

  assert.equal(requests, 2);
  assert.equal(second.cached, true);

  runtime.destroy();
  cleanup();
});

test('focused refresh uses raw fetch but discards results after navigation and always releases inflight', async () => {
  const state = {
    page: '算法列表',
    project: {id: 'p1'},
    algorithms: [{id: 'before'}],
    jobs: [{id: 'before-job'}],
    alg428Expanded: {},
  };
  let generation = 7;
  let release;
  const gate = new Promise(resolve => { release = resolve; });
  let rawRequests = 0;
  let scopedRequests = 0;
  const raw = async url => {
    rawRequests += 1;
    await gate;
    return url.includes('/algorithms')
      ? response({items: [{id: 'after'}]})
      : response([{id: 'after-job'}]);
  };
  const scoped = async () => {
    scopedRequests += 1;
    throw new Error('scoped fetch should not own modular algorithm refresh');
  };
  scoped.__pageRequestScopeOriginal = raw;
  globalThis.window = {
    fetch: scoped,
    PageRequestScopeRuntime: {stats: () => ({generation})},
    renderAlg412: () => { throw new Error('stale refresh must not render'); },
  };

  const runtime = installAlgorithmListRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });
  const pending = runtime.refresh();
  await Promise.resolve();
  state.page = '数据集';
  generation += 1;
  release();
  const result = await pending;

  assert.equal(rawRequests, 2);
  assert.equal(scopedRequests, 0);
  assert.equal(result.stale, true);
  assert.deepEqual(state.algorithms.map(row => row.id), ['before']);
  assert.deepEqual(state.jobs.map(row => row.id), ['before-job']);
  assert.equal(runtime.state().inflight, false);

  runtime.destroy();
  cleanup();
});

test('algorithm runtime exposes no DOM decorator layer', () => {
  const state = {page: '算法列表', project: {id: 'p1'}, algorithms: [], jobs: [], alg428Expanded: {}};
  globalThis.window = {fetch: async () => response({items: []})};
  const runtime = installAlgorithmListRuntime({getState: () => state, projectId: () => 'p1'});
  assert.equal(runtime.registerDecorator, undefined);
  assert.equal(runtime.runDecorators, undefined);
  runtime.destroy();
  cleanup();
});


test('algorithm runtime owns unified list filters and searches provider identifiers', () => {
  const state = {
    page: '算法列表',
    project: {id: 'p1'},
    algorithms: [],
    jobs: [],
    alg428Expanded: {},
  };
  globalThis.window = {
    fetch: async () => response({items: []}),
    renderAlg412: () => {},
  };
  const runtime = installAlgorithmListRuntime({
    getState: () => state,
    projectId: () => state.project.id,
  });

  assert.deepEqual(runtime.filterState(), {
    query: '',
    selectedCategoryIds: [],
    source: 'all',
    status: 'all',
  });

  const next = runtime.setFilters({
    query: ' PROD-42 ',
    selectedCategoryIds: ['root-a', 'root-a', '', 'child-a'],
    source: 'external',
    status: 'trainable',
  }, {render: false});
  assert.deepEqual(next, {
    query: 'PROD-42',
    selectedCategoryIds: ['root-a', 'child-a'],
    source: 'external',
    status: 'trainable',
  });

  assert.equal(runtime.matchesSearch({
    name: '抽烟检测',
    external_product_id: 'prod-42',
  }), true);
  assert.equal(algorithmListSearchMatch({algorithm_code: 'helmet-v2'}, 'HELMET'), true);
  assert.equal(algorithmListSearchMatch({productCode: 'safe-prod'}, 'SAFE-PROD'), true);
  assert.equal(algorithmListSearchMatch({name: '烟火检测'}, 'helmet'), false);

  runtime.destroy();
  cleanup();
});

test('category filtering uses only real external_category_id and separates draft from applied state', () => {
  const state = {
    page: '算法列表', project: {id: 'p1'}, jobs: [], alg428Expanded: {},
    algorithms: [
      {id: 'local', name: '本地车辆算法', source_type: 'LOCAL', industry: '车辆', versions: []},
      {id: 'external-match', name: '外部算法', source_type: 'EXTERNAL', external_category_id: 'leaf', versions: []},
      {id: 'external-other', name: '车辆相关外部算法', source_type: 'EXTERNAL', external_category_id: 'other', versions: []},
    ],
  };
  const categories = [
    {categoryId: 'root', categoryName: '车辆相关', parentId: ''},
    {categoryId: 'leaf', categoryName: '机动车检测', parentId: 'root'},
    {categoryId: 'other', categoryName: '人脸识别', parentId: ''},
  ];
  globalThis.window = {fetch: async () => response({items: []})};
  const runtime = installAlgorithmListRuntime({getState: () => state, projectId: () => 'p1'});
  runtime.setExternalProvider({
    snapshot: () => ({
      categories,
      externalMode: true,
      categoryRows: [
        {id: 'root', name: '车辆相关', parentId: '', ancestorIds: [], path: '车辆相关', hasChildren: true},
        {id: 'leaf', name: '机动车检测', parentId: 'root', ancestorIds: ['root'], path: '车辆相关 / 机动车检测', hasChildren: false},
        {id: 'other', name: '人脸识别', parentId: '', ancestorIds: [], path: '人脸识别', hasChildren: false},
      ],
    }),
    matches: (algorithm, filters) => {
      if (!filters.selectedCategoryIds.length) return true;
      return filters.selectedCategoryIds.includes(String(algorithm.external_category_id || ''));
    },
  });

  assert.deepEqual(runtime.visibleAlgorithms().map(row => row.id), ['local', 'external-match', 'external-other']);
  runtime.openCategoryPicker();
  runtime.toggleDraftCategory('root');
  runtime.confirmCategoryPicker();
  assert.deepEqual(runtime.filterState().selectedCategoryIds, []);
  runtime.openCategoryPicker();
  runtime.toggleDraftCategory('leaf');
  assert.deepEqual(runtime.filterState().selectedCategoryIds, []);
  assert.deepEqual(runtime.visibleAlgorithms().map(row => row.id), ['local', 'external-match', 'external-other']);
  runtime.cancelCategoryPicker();
  assert.deepEqual(runtime.filterState().selectedCategoryIds, []);
  runtime.openCategoryPicker();
  runtime.toggleDraftCategory('leaf');
  runtime.confirmCategoryPicker();
  assert.deepEqual(runtime.filterState().selectedCategoryIds, ['leaf']);
  assert.deepEqual(runtime.visibleAlgorithms().map(row => row.id), ['external-match']);

  runtime.destroy();
  cleanup();
});

test('trainable filter matches the real training affordance for local and external algorithms', () => {
  const state = {
    page: '算法列表',
    project: {id: 'p1'},
    jobs: [],
    alg428Expanded: {},
    algorithms: [
      {id: 'local-yolo', name: '本地 YOLO', source_type: 'LOCAL', algorithm_type: 'yolo_ultralytics', versions: []},
      {id: 'local-opencv', name: 'OpenCV', source_type: 'LOCAL', algorithm_type: 'opencv', versions: []},
      {id: 'external-ready', name: '畅联可训练', source_type: 'EXTERNAL', provider_type: 'CHANG_LIAN', versions: []},
      {id: 'external-blocked', name: '畅联不可训练', source_type: 'EXTERNAL', provider_type: 'CHANG_LIAN', versions: []},
    ],
  };
  globalThis.window = {fetch: async () => response({items: []})};
  const runtime = installAlgorithmListRuntime({getState: () => state, projectId: () => 'p1'});
  runtime.setExternalProvider({
    snapshot: () => ({categories: [], categoryRows: [], externalMode: true}),
    matches: () => true,
    meta: algorithm => ({
      external: String(algorithm.source_type || '').toUpperCase() === 'EXTERNAL',
      sourceLabel: '测试',
      readiness: {ready: algorithm.id !== 'external-blocked', message: ''},
    }),
  });
  runtime.setFilters({status: 'trainable'}, {render: false});
  assert.deepEqual(runtime.visibleAlgorithms().map(row => row.id).sort(), ['external-ready', 'local-yolo']);
  runtime.destroy();
  cleanup();
});

test('algorithm registry source keeps card-wide expansion and explicit trainable quick filter', async () => {
  const {readFileSync} = await import('node:fs');
  const source = readFileSync(new URL('../../static/modules/algorithm-list-runtime.js', import.meta.url), 'utf8');
  assert.match(source, /class="algorithm-card-grid"/);
  assert.match(source, /data-algorithm-card="1"/);
  assert.match(source, /data-algorithm-trainable-only/);
  assert.match(source, /仅看可训练/);
  assert.match(source, /!event\.target\.closest\('button,a,input,select,textarea,label,details,summary'\)/);
  assert.match(source, /scheduleTrainingWarmup\(rows\)/);
});

test('category presentation supports real arbitrary depth in three visible panes and full-path search', () => {
  const rows = [
    {id: 'root', name: '安全治理', parentId: '', depth: 0, ancestorIds: [], path: '安全治理', hasChildren: true},
    {id: 'vehicle', name: '车辆', parentId: 'root', depth: 1, ancestorIds: ['root'], path: '安全治理 / 车辆', hasChildren: true},
    {id: 'parking', name: '违停', parentId: 'vehicle', depth: 2, ancestorIds: ['root', 'vehicle'], path: '安全治理 / 车辆 / 违停', hasChildren: true},
    {id: 'night', name: '夜间违停', parentId: 'parking', depth: 3, ancestorIds: ['root', 'vehicle', 'parking'], path: '安全治理 / 车辆 / 违停 / 夜间违停', hasChildren: false},
  ];
  const columns = algorithmCategoryColumns(rows, ['root', 'vehicle', 'parking']);
  assert.equal(columns.length, 3);
  assert.deepEqual(columns.map(column => column.parentId), ['root', 'vehicle', 'parking']);
  assert.deepEqual(algorithmCategorySearch(rows, '夜间').map(row => row.path), ['安全治理 / 车辆 / 违停 / 夜间违停']);
});


test('current mAP50 never falls back to generic accuracy', () => {
  assert.equal(algorithmVersionMap50({accuracy: 0.91}), null);
  assert.ok(Math.abs(algorithmVersionMap50({map50: 0.926}) - 92.6) < 1e-9);
  assert.equal(algorithmVersionMap50({metrics: {mAP50: 0.8}}), 80);
});
