from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected exactly 1 match, found {count}')
    return text.replace(old, new, 1)


nav_path = Path('static/modules/navigation-stability.js')
nav = nav_path.read_text(encoding='utf-8')
nav = replace_once(
    nav,
    "  beforeInvokeNavigation,\n} = {}) {",
    "  beforeInvokeNavigation,\n  performNavigation,\n} = {}) {",
    'navigation option',
)
nav = replace_once(
    nav,
    "  const originalSetPage = window.setPage;\n  if (typeof originalSetPage === 'function') {\n",
    "  const originalSetPage = window.setPage;\n  const hasClassicPredecessor = typeof originalSetPage === 'function';\n  const hasNamedNavigationOwner = typeof performNavigation === 'function';\n  if (hasClassicPredecessor || hasNamedNavigationOwner) {\n",
    'navigation owner install gate',
)
nav = replace_once(
    nav,
    "      const invokeOriginal = () => {\n        try {\n          beforeInvokeNavigation?.(requested);\n          return settleResult(originalSetPage.call(this, requested, ...args));\n        } catch (error) {\n          finalizeNavigation(requested, navigationEpoch);\n          throw error;\n        }\n      };\n",
    "      const invokeNavigationOwner = () => {\n        try {\n          beforeInvokeNavigation?.(requested);\n          if (hasNamedNavigationOwner) {\n            return settleResult(performNavigation.call(this, requested, ...args));\n          }\n          return settleResult(originalSetPage.call(this, requested, ...args));\n        } catch (error) {\n          finalizeNavigation(requested, navigationEpoch);\n          throw error;\n        }\n      };\n",
    'named actual-navigation owner',
)
nav = nav.replace('          () => invokeOriginal(),', '          () => invokeNavigationOwner(),')
nav = nav.replace('      return invokeOriginal();', '      return invokeNavigationOwner();')
if nav.count('invokeOriginal') != 0:
    raise SystemExit('invokeOriginal token remains')
if nav.count('performNavigation') < 3:
    raise SystemExit('performNavigation owner was not installed completely')
nav_path.write_text(nav, encoding='utf-8')

main_path = Path('static/main.mjs')
main = main_path.read_text(encoding='utf-8')
main = replace_once(
    main,
    "import {installNavigationStability} from './modules/navigation-stability.js?v=422510';",
    "import {installNavigationStability} from './modules/navigation-stability.js?v=422511';",
    'navigation module cache',
)
main = replace_once(
    main,
    "  beforeInvokeNavigation: () => window.toggleMobileSidebarV37?.(false),\n});",
    "  beforeInvokeNavigation: () => window.toggleMobileSidebarV37?.(false),\n  performNavigation: page => {\n    state.page = page;\n    render();\n  },\n});",
    'main named page application',
)
main_path.write_text(main, encoding='utf-8')

index_path = Path('static/index.html')
index = index_path.read_text(encoding='utf-8')
index = replace_once(index, '/static/main.mjs?v=42.25.57', '/static/main.mjs?v=42.25.58', 'main cache bump')
index_path.write_text(index, encoding='utf-8')

test_path = Path('tests/frontend/navigation-stability.test.mjs')
test_text = test_path.read_text(encoding='utf-8')
anchor = "test('readiness gate runs before UI cleanup and predecessor page mutation', async () => {"
if test_text.count(anchor) != 1:
    raise SystemExit('navigation unit anchor mismatch')
new_tests = r'''test('named performNavigation is the sole actual page owner when configured', () => {
  const state = {page: '算法列表'};
  const calls = [];
  const view = {dataset: {}};
  let classicCalls = 0;
  let applyCalls = 0;
  let renders = 0;

  globalThis.document = {
    getElementById(id) { return id === 'view' ? view : null; },
  };
  globalThis.window = {
    setPage(page) {
      classicCalls += 1;
      calls.push(`classic:${page}`);
      state.page = page;
    },
  };

  const runtime = installNavigationStability({
    getState: () => state,
    beforeInvokeNavigation(page) { calls.push(`ui:close:${page}`); },
    performNavigation(page) {
      applyCalls += 1;
      calls.push(`apply:${page}`);
      state.page = page;
      renders += 1;
    },
  });

  globalThis.window.setPage('数据集');

  assert.equal(classicCalls, 0, 'classic predecessor must be bypassed when named owner is configured');
  assert.equal(applyCalls, 1);
  assert.equal(renders, 1, 'actual navigation must render exactly once');
  assert.equal(state.page, '数据集');
  assert.deepEqual(calls, ['ui:close:数据集', 'apply:数据集']);

  runtime.destroy();
  cleanup();
});

test('named performNavigation installs global setPage without a classic predecessor', () => {
  const state = {page: '算法列表'};
  let renders = 0;
  const view = {dataset: {}};

  globalThis.document = {
    getElementById(id) { return id === 'view' ? view : null; },
  };
  globalThis.window = {};

  const runtime = installNavigationStability({
    getState: () => state,
    performNavigation(page) {
      state.page = page;
      renders += 1;
    },
  });

  assert.equal(typeof globalThis.window.setPage, 'function');
  globalThis.window.setPage('数据集');
  assert.equal(state.page, '数据集');
  assert.equal(renders, 1);
  assert.equal(view.dataset.navigationPage, '数据集');

  runtime.destroy();
  cleanup();
});

'''
test_text = test_text.replace(anchor, new_tests + anchor, 1)
test_path.write_text(test_text, encoding='utf-8')

print('staged named performNavigation owner; classic bootstrap remains for equivalence')
