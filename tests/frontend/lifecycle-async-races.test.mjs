import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8').replace(/\r\n/g, '\n');

function between(start, end) {
  const a = source.indexOf(start);
  const b = source.indexOf(end, a + start.length);
  assert.ok(a >= 0 && b > a, `runtime segment must exist: ${start}`);
  return source.slice(a, b);
}

function deferred() {
  let resolve, reject;
  const promise = new Promise((ok, fail) => {resolve = ok; reject = fail;});
  return {promise, resolve, reject};
}

function mountModalRuntime() {
  const state = {page: '自动标注及清洗', project: {id: 'project-1'}};
  const stack = [];
  const base = {classList: {contains: () => false}};
  let modal;
  const window = {
    ModalContentRuntime: {replace() {}},
    NavigationStability: {action(page) {return {isCurrent: () => state.page === page};}},
    PlatformCore: {presentation: {hideTooltip() {}}},
  };
  const context = vm.createContext({
    window, state, pid: () => state.project.id,
    dynamicModalStack: stack, baseModal: base,
    modal,
    closeModal: () => {},
    beforeCloseModal424: () => {},
    restoreModalFocus424: () => {},
    closeModalBase: () => {},
    modalBase: () => {},
    focusModal424: () => {},
    decorateImportModal424: layer => layer,
    makeLayer424: title => {
      const layer = {title, removed: false, remove() {this.removed = true;}};
      stack.push(layer);
      return layer;
    },
  });
  vm.runInContext(between('  let modalIntentEpoch424=0;', '  window.modal=modal;') + '\nwindow.modal=modal;', context);
  vm.runInContext(between('  closeModal=function closeModalStackCore424(){', '  window.closeModalCore424=closeModal;') + '\nwindow.closeModalCore424=closeModal;', context);
  return {state, stack, window, context};
}

test('late startup timer cannot recreate boot card after #view has a business page', () => {
  const state = {uiReady: false, __startupCanonicalPainted: false};
  const window = {PlatformCore: {presentation: {loadingSkeleton: () => ''}}};
  const context = vm.createContext({window, state, esc: value => String(value)});
  vm.runInContext(between(' function boot(st)', ' function apply(s)') + '\nglobalThis.paintBootForTest=paintBoot;', context);
  const view = {innerHTML: '业务页面', querySelector: () => null};
  assert.equal(context.paintBootForTest(view, {stage: '旧计时器'}), false);
  assert.equal(view.innerHTML, '业务页面');
  state.uiReady = true;
  assert.equal(context.paintBootForTest(view, {stage: '旧计时器'}, {allowCreate: true}), false);
  assert.equal(view.innerHTML, '业务页面');
  state.uiReady = false;
  assert.equal(context.paintBootForTest(view, {stage: '首次启动'}, {allowCreate: true}), true);
  assert.match(view.innerHTML, /data-boot-card/);
});

test('authoritative snapshot cannot commit to a different project or an A→B→A navigation', async () => {
  const requests = [];
  const state = {page: '算法列表', project: {id: 'P'}, __navigationEpoch: 1, datasets: [], labels: [], algorithms: []};
  const window = {PlatformCore: {materialPaging: {requiresFullMaterialPool: () => false}}};
  const context = vm.createContext({
    state, window,
    ensureWorkspace: async () => {},
    api: url => {const item = deferred(); requests.push({url, ...item}); return item.promise;},
  });
  vm.runInContext(between('  window.loadCore412=async function', '  async function pollAnnotationIndex412'), context);
  const first = window.loadCore412({authoritative: true});
  assert.equal(requests.length, 1);
  state.page = '训练任务'; state.__navigationEpoch++;
  state.page = '算法列表'; state.__navigationEpoch++;
  const second = window.loadCore412({authoritative: true});
  assert.equal(requests.length, 2);
  requests[0].resolve({algorithms: [{id: 'stale'}], jobs: []});
  assert.equal(await first, false);
  assert.equal(state.algorithms.length, 0);
  requests[1].resolve({algorithms: [{id: 'new'}], jobs: []});
  assert.equal(await second, true);
  assert.equal(state.algorithms[0].id, 'new');
});

test('a refresh started on page A cannot issue page-B extras when its core request settles', async () => {
  const state = {page: '算法列表', project: {id: 'P'}};
  const core = deferred();
  const extras = [];
  let epoch = 0;
  const window = {
    loadCore412: () => core.promise,
    NavigationStability: {action(page) {const origin = epoch; return {isCurrent: () => epoch === origin && state.page === page};}},
  };
  const context = vm.createContext({window, state, pid: () => state.project.id, extras412: page => {extras.push(page);}});
  vm.runInContext(between('  window.refreshCurrentPage413=async function', '  loadAll=window.refreshCurrentPage413;'), context);
  const refreshing = window.refreshCurrentPage413({authoritative: true});
  state.page = '训练任务'; epoch++;
  core.resolve(true);
  assert.equal(await refreshing, false);
  assert.deepEqual(extras, []);
});

test('async task-detail request is retired when another business modal opens', async () => {
  const {window, stack} = mountModalRuntime();
  const awaiting = deferred();
  const intent = window.ModalContentRuntime.beginAsyncOpen();
  const request = awaiting.promise.then(() => intent.isCurrent() && window.modal('旧任务详情', ''));
  window.modal('新业务弹窗', '');
  awaiting.resolve();
  await request;
  assert.equal(stack.length, 1);
  assert.equal(stack[0].title, '新业务弹窗');
  assert.equal(intent.isCurrent(), false);
});

test('closing an owned dialog retires a previously started async action before HTTP returns', async () => {
  const {window, stack} = mountModalRuntime();
  window.modal('正在读取 A', '');
  const lease = window.ModalContentRuntime.captureOwner();
  const fetch = deferred();
  const pending = fetch.promise.then(() => lease.isCurrent() && window.modal('迟到 A', ''));
  window.closeModalCore424();
  window.modal('新弹窗 B', '');
  fetch.resolve();
  await pending;
  assert.equal(stack.length, 1);
  assert.equal(stack[0].title, '新弹窗 B');
});

test('actual clean task detail does not open after a newer window replaces the pending request', async () => {
  const {window, state, stack, context} = mountModalRuntime();
  const fetch = deferred();
  const registry = {clear() {}, startTimeout() {throw new Error('stale task must not poll');}};
  Object.assign(window, {PollRegistryRuntime: registry, PlatformCore: {cleaning: {cleanTaskView: () => ({active: false})}}});
  Object.assign(context, {
    toast: () => assert.fail('stale request must not toast'),
    fetchTask429: () => fetch.promise,
    renderCleanProgress429: () => {window.modal('旧清洗详情', '');},
    cleanProgressPollKey429: id => `clean:${id}`,
  });
  vm.runInContext(between('  function armCleanProgressPoll429(id,ownerPage){', '  // Delegate to the canonical MaterialBatch retry/poll owner.'), context);
  const request = window.showCleanTaskProgress429('task-A');
  window.modal('新业务弹窗', '');
  fetch.resolve({id: 'task-A', status: 'running'});
  await request;
  assert.equal(stack.length, 1);
  assert.equal(stack[0].title, '新业务弹窗');
  assert.equal(state.page, '自动标注及清洗');
});

test('already-running clean poll cannot close or navigate over a newly opened dialog', async () => {
  const {window, stack, context} = mountModalRuntime();
  const fetch = deferred();
  let callback = null, detailOpens = 0, closes = 0;
  const registry = {clear() {}, startTimeout(key, pages, action) {callback = action; return 1;}};
  window.modal('清洗任务 A', '');
  window.PollRegistryRuntime = registry;
  window.PlatformCore = {cleaning: {cleanTaskView: () => ({active: true})}};
  window.cleanDetail429 = () => {detailOpens++;};
  window.closeModalLayer424 = () => {closes++; return true;};
  Object.assign(context, {
    cleanProgressPollKey429: id => `clean:${id}`,
    cleanProgressRoot429: () => ({}),
    fetchTask429: () => fetch.promise,
    renderCleanProgress429: () => assert.fail('old poll must not repaint'),
    toast: () => assert.fail('old poll must not toast'),
  });
  vm.runInContext(between('  function armCleanProgressPoll429(id,ownerPage){', '  // Delegate to the canonical MaterialBatch retry/poll owner.'), context);
  vm.runInContext('armCleanProgressPoll429("task-A", "自动标注及清洗")', context);
  const running = callback();
  window.modal('另一个业务弹窗 B', '');
  fetch.resolve({id: 'task-A', status: 'done'});
  await running;
  assert.equal(stack.at(-1).title, '另一个业务弹窗 B');
  assert.equal(closes, 0);
  assert.equal(detailOpens, 0);
});

test('actual AI detail async opener cannot paint after a newer modal opens', async () => {
  const {window, stack, context} = mountModalRuntime();
  const fetch = deferred();
  let painted = 0;
  Object.assign(window, {PlatformCore: {taskPoller: {waitForTaskTerminal: () => Promise.resolve({id: 'A'})}}});
  Object.assign(context, {
    aiDetailSession60: 0,
    stopAiTaskDetail60: () => {context.aiDetailSession60++;},
    state: context.state,
    taskApi: id => `/api/annotation-tasks/${id}`,
    api: () => fetch.promise,
    progressShell: () => {painted++;window.modal('旧 AI 详情', '');},
    renderProgress: () => {},
    toast: () => assert.fail('stale AI request must not toast'),
  });
  vm.runInContext(between('  window.showAiTask60=async function', '  window.showTaskProgress427=function'), context);
  const request = window.showAiTask60('A');
  window.modal('新弹窗 B', '');
  fetch.resolve({id: 'A', status: 'running'});
  await request;
  assert.equal(painted, 0);
  assert.equal(stack.at(-1).title, '新弹窗 B');
});

test('reopening the same AI task retires the first request even if its task id matches', async () => {
  const {window, context, stack} = mountModalRuntime();
  const first = deferred(), second = deferred(), pending = [first, second];
  let painted = 0;
  window.PlatformCore = {taskPoller: {waitForTaskTerminal: async () => ({id: 'task-1', status: 'done'})}};
  window.AutoLabelPollRuntime = {deactivate() {}, activate() {}};
  Object.assign(context, {
    aiDetailSession60: 0,
    stopAiTaskDetail60: () => {context.aiDetailSession60++;},
    taskApi: id => `/api/annotation-tasks/${id}`,
    api: () => pending.shift().promise,
    progressShell: () => {painted++;window.modal('AI task-1', '');},
    renderProgress: () => {},
    toast: () => assert.fail('older same-task response must not toast'),
  });
  vm.runInContext(between('  window.showAiTask60=async function', '  window.showTaskProgress427=function'), context);
  const old = window.showAiTask60('task-1');
  const newest = window.showAiTask60('task-1');
  first.resolve({id: 'task-1', status: 'running'});
  await old;
  assert.equal(painted, 0);
  second.resolve({id: 'task-1', status: 'done'});
  await newest;
  assert.equal(painted, 1);
  assert.equal(stack.at(-1).title, 'AI task-1');
});

test('completed AI retry POST remains a server fact but cannot close the newer dialog', async () => {
  const {window, context, stack} = mountModalRuntime();
  const post = deferred();
  let requests = 0, closes = 0, show = 0;
  window.modal('AI 任务 A', '');
  window.closeModalLayer424 = () => {closes++;};
  window.showAiTask60 = () => {show++;};
  Object.assign(context, {
    taskApi: id => `/api/annotation-tasks/${id}`,
    api: (url, options) => {assert.equal(options.method, 'POST'); requests++; return post.promise;},
    toast: () => assert.fail('stale POST must not toast'),
  });
  vm.runInContext(between('  window.retryAiTask60=async id=>', '\n\n  function explicitCanonicalAiLabelText'), context);
  const request = window.retryAiTask60('A');
  window.modal('新业务 B', '');
  post.resolve({id: 'A', status: 'queued'});
  const result = await request;
  assert.equal(result.id, 'A');
  assert.equal(requests, 1);
  assert.equal(closes, 0);
  assert.equal(show, 0);
  assert.equal(stack.at(-1).title, '新业务 B');
});

test('old conversion log GET cannot open a dialog after another modal owns the user action', async () => {
  const {window, context, stack} = mountModalRuntime();
  const response = deferred();
  const opened = [];
  Object.assign(context, {
    api: () => response.promise,
    toast: () => assert.fail('retired log read must not toast'),
    modal: (...args) => opened.push(args),
    esc: value => String(value),
    statusPill: () => '',
    document: {getElementById: () => null},
  });
  vm.runInContext(between('  window.openDeployLog=async id=>{', '\n  window.refreshDeployLog='), context);
  const old = window.openDeployLog('task-log-A');
  window.modal('新弹窗 B', '');
  response.resolve('旧任务日志内容');
  await old;
  assert.deepEqual(opened, []);
  assert.equal(stack.at(-1).title, '新弹窗 B');
});
