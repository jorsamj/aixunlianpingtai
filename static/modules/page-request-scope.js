const NEVER = new Promise(() => {});

function requestMethod(input, init = {}) {
  return String(init?.method || input?.method || 'GET').toUpperCase();
}

function requestUrl(input) {
  if (typeof input === 'string') return input;
  if (typeof URL !== 'undefined' && input instanceof URL) return input.href;
  return String(input?.url || '');
}

function isApiRequest(input) {
  const raw = requestUrl(input);
  if (!raw) return false;
  if (raw.startsWith('/api/')) return true;
  if (typeof location === 'undefined') return /\/api\//.test(raw);
  try {
    const parsed = new URL(raw, location.href);
    return parsed.origin === location.origin && parsed.pathname.startsWith('/api/');
  } catch (_) {
    return false;
  }
}

function isAbortError(error) {
  return error?.name === 'AbortError' || error?.code === 20;
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
      && !init?.signal;
    if (!scopeEligible) return nativeFetch(input, init);

    const generation = this.generation;
    const page = this.page;
    const controller = this.controller;

    try {
      const response = await nativeFetch(input, {...init, signal: controller.signal});
      if (controller.signal.aborted || !this.isCurrent(generation, page)) {
        this.abortedRequests += 1;
        return NEVER;
      }
      return response;
    } catch (error) {
      if (isAbortError(error) && (controller.signal.aborted || !this.isCurrent(generation, page))) {
        this.abortedRequests += 1;
        // Legacy app.js callers often catch every error and show a toast. Keep a request
        // invalidated by navigation suspended instead: its caller can no longer mutate state/DOM,
        // and no spurious "request failed" message is shown to the user.
        return NEVER;
      }
      throw error;
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
