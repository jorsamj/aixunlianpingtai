// A retired read must settle so the caller's finally releases its state.
export const PAGE_NAVIGATION_CANCELLED = '__PAGE_NAVIGATION_CANCELLED__';
export function isPageNavigationCancelled(value) {
  return value?.code === 'PAGE_NAVIGATION_CANCELLED'
    || String(typeof value === 'string' ? value : value?.message || '').includes(PAGE_NAVIGATION_CANCELLED);
}
function cancelledNavigation() {
  const error = new Error(PAGE_NAVIGATION_CANCELLED);
  error.name = 'AbortError';
  error.code = 'PAGE_NAVIGATION_CANCELLED';
  return error;
}

function requestMethod(input, init = {}) {
  return String(init?.method || input?.method || 'GET').toUpperCase();
}

function requestUrl(input) {
  if (typeof input === 'string') return input;
  if (typeof URL !== 'undefined' && input instanceof URL) return input.href;
  return String(input?.url || '');
}

function apiPath(input) {
  const raw = requestUrl(input);
  if (!raw) return '';
  if (raw.startsWith('/api/')) return raw.split('?')[0];
  if (typeof location === 'undefined') {
    const match = raw.match(/\/api\/[^?#]*/);
    return match?.[0] || '';
  }
  try {
    const parsed = new URL(raw, location.href);
    return parsed.origin === location.origin ? parsed.pathname : '';
  } catch (_) {
    return '';
  }
}

function isApiRequest(input) {
  return apiPath(input).startsWith('/api/');
}

function isApplicationLifecycleRequest(input) {
  const path = apiPath(input);
  return path === '/api/v53/bootstrap/status'
    || path === '/api/v53/bootstrap/snapshot'
    || path === '/api/v53/bootstrap/start';
}

export class PageRequestScope {
  constructor({page = '', fetchImpl} = {}) {
    this.page = String(page || '');
    this.generation = 0;
    this.controller = new AbortController();
    this.fetchImpl = fetchImpl;
    this.abortedRequests = 0;
  }

  navigate(page) {
    this.controller.abort('page-navigation');
    this.generation += 1;
    this.page = String(page || '');
    this.controller = new AbortController();
    return this.generation;
  }

  alignPage(page) {
    this.page = String(page || '');
  }

  isCurrent(generation, page = this.page) {
    return generation === this.generation && String(page || '') === this.page;
  }

  async fetch(input, init = {}) {
    const nativeFetch = this.fetchImpl;
    if (typeof nativeFetch !== 'function') throw new Error('PageRequestScope requires fetchImpl');

    const method = requestMethod(input, init);
    const scopeEligible = (method === 'GET' || method === 'HEAD')
      && isApiRequest(input)
      && !isApplicationLifecycleRequest(input)
      // Request objects can already own a signal; do not override it with the
      // page signal when init.signal is absent.
      && !init?.signal
      && !input?.signal;
    if (!scopeEligible) return nativeFetch(input, init);

    const generation = this.generation;
    const page = this.page;
    const controller = this.controller;

    // Some transports and test doubles do not reject when AbortSignal fires.
    // Race their response against the owner's retirement so a cancelled page
    // settles even if the underlying fetch ignores cancellation entirely.
    let onRetire;
    const retired = new Promise((_resolve, reject) => {
      onRetire = () => reject(cancelledNavigation());
      controller.signal.addEventListener('abort', onRetire, {once: true});
      if (controller.signal.aborted) onRetire();
    });
    try {
      const response = await Promise.race([
        nativeFetch(input, {...init, signal: controller.signal}),
        retired,
      ]);
      if (controller.signal.aborted || !this.isCurrent(generation, page)) throw cancelledNavigation();
      return response;
    } catch (error) {
      if (controller.signal.aborted || !this.isCurrent(generation, page)) {
        this.abortedRequests += 1;
        throw cancelledNavigation();
      }
      throw error;
    } finally {
      controller.signal.removeEventListener('abort', onRetire);
    }
  }

  destroy() {
    this.controller.abort('scope-destroyed');
  }
}

export function installPageRequestScope({getPage} = {}) {
  if (typeof window === 'undefined' || typeof window.fetch !== 'function') return null;
  if (window.__pageRequestScopeInstalled) return window.PageRequestScopeRuntime;

  const originalFetch = window.fetch.bind(window);
  const scope = new PageRequestScope({page: getPage?.() || '', fetchImpl: originalFetch});
  const scopedFetch = scope.fetch.bind(scope);
  scopedFetch.__pageRequestScopeWrapped = true;
  scopedFetch.__pageRequestScopeOriginal = originalFetch;
  window.fetch = scopedFetch;
  window.__pageRequestScopeInstalled = true;

  const runtime = {
    scope,
    navigate(page) { return scope.navigate(page); },
    alignPage(page) { scope.alignPage(page); },
    stats() {
      return {
        page: scope.page,
        generation: scope.generation,
        abortedRequests: scope.abortedRequests,
      };
    },
    destroy() {
      scope.destroy();
      if (window.fetch === scopedFetch) window.fetch = originalFetch;
      if (window.PageRequestScopeRuntime === runtime) window.PageRequestScopeRuntime = null;
      window.__pageRequestScopeInstalled = false;
    },
  };
  window.PageRequestScopeRuntime = runtime;
  return runtime;
}
