(() => {
  if (window.__materialPaging61?.installed) return;

  const originalFetch = window.fetch.bind(window);
  const state = {
    installed: true,
    mode: 'paged',
    pageSize: 48,
    lastPage: null,
    originalFetch,
  };
  window.__materialPaging61 = state;

  window.fetch = async function materialAwareFetch(input, init = undefined) {
    const method = String(init?.method || (input instanceof Request ? input.method : 'GET')).toUpperCase();
    if (state.mode !== 'paged' || method !== 'GET') return originalFetch(input, init);

    let requestUrl;
    try {
      requestUrl = new URL(typeof input === 'string' ? input : input.url, window.location.origin);
    } catch (_error) {
      return originalFetch(input, init);
    }

    const match = requestUrl.pathname.match(/^\/api\/projects\/([^/]+)\/images$/);
    if (!match) return originalFetch(input, init);

    const projectId = encodeURIComponent(decodeURIComponent(match[1]));
    const pagedUrl = new URL(`/api/v61/projects/${projectId}/materials`, window.location.origin);
    pagedUrl.searchParams.set('limit', String(state.pageSize));

    const signal = init?.signal || (input instanceof Request ? input.signal : undefined);
    const response = await originalFetch(pagedUrl.toString(), {
      method: 'GET',
      headers: {Accept: 'application/json'},
      credentials: 'same-origin',
      signal,
    });
    if (!response.ok) return response;

    const page = await response.json();
    state.lastPage = page;
    return new Response(JSON.stringify(Array.isArray(page.items) ? page.items : []), {
      status: response.status,
      statusText: response.statusText,
      headers: {
        'content-type': 'application/json; charset=utf-8',
        'cache-control': 'no-store',
      },
    });
  };
})();
