const DEFAULT_PAGE_SIZE = 20;
const DEFAULT_PAGE_SIZES = Object.freeze([10, 20, 50, 100]);

function positiveInteger(value, fallback) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : fallback;
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

export function normalizePagination(input = {}) {
  const pageSize = positiveInteger(input.pageSize ?? input.page_size, DEFAULT_PAGE_SIZE);
  const total = Math.max(0, Number.isFinite(Number(input.total)) ? Math.trunc(Number(input.total)) : 0);
  const computedPages = Math.max(1, Math.ceil(total / pageSize));
  const authoritativePages = positiveInteger(input.totalPages ?? input.total_pages, computedPages);
  const totalPages = Math.max(1, authoritativePages);
  const requestedPage = positiveInteger(input.page, 1);
  const page = Math.min(requestedPage, totalPages);
  return {
    page,
    pageSize,
    total,
    totalPages,
    hasPrevious: input.hasPrevious ?? input.has_previous ?? page > 1,
    hasNext: input.hasNext ?? input.has_next ?? page < totalPages,
    loading: input.loading === true,
    error: String(input.error || ''),
  };
}

export function paginationTokens(page, totalPages) {
  const current = Math.max(1, positiveInteger(page, 1));
  const pages = Math.max(1, positiveInteger(totalPages, 1));
  if (pages <= 7) return Array.from({length: pages}, (_, index) => index + 1);

  const selected = new Set([1, pages, current]);
  if (current <= 4) {
    for (let value = 2; value <= 5; value += 1) selected.add(value);
  } else if (current >= pages - 3) {
    for (let value = pages - 4; value < pages; value += 1) selected.add(value);
  } else {
    for (let value = current - 2; value <= current + 2; value += 1) selected.add(value);
  }
  const ordered = [...selected]
    .filter(value => value >= 1 && value <= pages)
    .sort((left, right) => left - right);
  const tokens = [];
  ordered.forEach((value, index) => {
    if (index && value - ordered[index - 1] > 1) tokens.push('ellipsis');
    tokens.push(value);
  });
  return tokens;
}

export function validatePageInput(value, totalPages) {
  const normalized = String(value ?? '').trim();
  const maximum = Math.max(1, positiveInteger(totalPages, 1));
  if (!/^\d+$/.test(normalized)) {
    return {ok: false, page: null, error: `请输入 1-${maximum} 的整数页码`};
  }
  const page = Number(normalized);
  if (!Number.isSafeInteger(page) || page < 1 || page > maximum) {
    return {ok: false, page: null, error: `页码必须在 1-${maximum} 之间`};
  }
  return {ok: true, page, error: ''};
}

export function renderPagination(input = {}, options = {}) {
  const state = normalizePagination(input);
  const disabled = state.loading ? ' disabled' : '';
  const previousDisabled = state.loading || !state.hasPrevious ? ' disabled' : '';
  const nextDisabled = state.loading || !state.hasNext ? ' disabled' : '';
  const tokens = paginationTokens(state.page, state.totalPages).map((token, index) => {
    if (token === 'ellipsis') {
      return `<span class="platform-pagination__ellipsis" aria-hidden="true" data-pagination-ellipsis="${index}">…</span>`;
    }
    const current = token === state.page;
    return `<button type="button" class="platform-pagination__page${current ? ' is-current' : ''}" data-pagination-page="${token}" aria-label="第 ${token} 页"${current ? ' aria-current="page"' : ''}${disabled}>${token}</button>`;
  }).join('');
  const pageSizes = [...new Set((options.pageSizes || DEFAULT_PAGE_SIZES)
    .map(value => positiveInteger(value, 0))
    .filter(Boolean))];
  if (!pageSizes.includes(state.pageSize)) pageSizes.push(state.pageSize);
  pageSizes.sort((left, right) => left - right);
  const sizeControl = options.showPageSize
    ? `<label class="platform-pagination__size"><span>每页</span><select data-pagination-size aria-label="每页条数"${disabled}>${pageSizes.map(value => `<option value="${value}"${value === state.pageSize ? ' selected' : ''}>${value}</option>`).join('')}</select><span>条</span></label>`
    : '';
  const label = escapeHtml(options.label || '分页导航');
  return `<nav class="platform-pagination${state.loading ? ' is-loading' : ''}" aria-label="${label}" aria-busy="${state.loading ? 'true' : 'false'}">
    <div class="platform-pagination__controls">
      <button type="button" class="platform-pagination__direction" data-pagination-page="${Math.max(1, state.page - 1)}" aria-label="上一页"${previousDisabled}>上一页</button>
      <div class="platform-pagination__pages" aria-label="页码">${tokens}</div>
      <button type="button" class="platform-pagination__direction" data-pagination-page="${Math.min(state.totalPages, state.page + 1)}" aria-label="下一页"${nextDisabled}>下一页</button>
      <span class="platform-pagination__divider" aria-hidden="true"></span>
      <label class="platform-pagination__jump"><span>前往</span><input type="text" inputmode="numeric" autocomplete="off" data-pagination-input value="${state.page}" aria-label="指定页码" aria-invalid="${state.error ? 'true' : 'false'}"><span>页</span></label>
      <button type="button" class="platform-pagination__submit" data-pagination-jump${disabled}>跳转</button>
      ${sizeControl}
    </div>
    <div class="platform-pagination__footer"><span>共 ${state.total} 条 · ${state.totalPages} 页 · 当前第 ${state.page} 页</span><span class="platform-pagination__loading"${state.loading ? '' : ' hidden'}>加载中…</span></div>
    <div class="platform-pagination__error" data-pagination-error role="alert">${escapeHtml(state.error)}</div>
  </nav>`;
}

export function mountPagination(rootOrSelector, input = {}, options = {}) {
  const root = typeof rootOrSelector === 'string'
    ? document.querySelector(rootOrSelector)
    : rootOrSelector;
  if (!root) return null;
  root.__platformPaginationDestroy?.();

  let active = true;
  let busy = false;
  let state = normalizePagination(input);
  let settings = {...options};

  const paint = () => {
    root.innerHTML = renderPagination({...state, loading: state.loading || busy}, settings);
  };
  const showError = message => {
    state = {...state, error: String(message || '')};
    const error = root.querySelector?.('[data-pagination-error]');
    const inputElement = root.querySelector?.('[data-pagination-input]');
    if (error) error.textContent = state.error;
    inputElement?.setAttribute?.('aria-invalid', state.error ? 'true' : 'false');
  };
  const run = async callback => {
    if (busy || state.loading || typeof callback !== 'function') return false;
    busy = true;
    paint();
    try {
      await callback();
      return true;
    } catch (error) {
      if (active) showError(error?.message || error || '分页请求失败，请重试');
      return false;
    } finally {
      busy = false;
      if (active) paint();
    }
  };
  const jump = () => {
    const inputElement = root.querySelector?.('[data-pagination-input]');
    const result = validatePageInput(inputElement?.value, state.totalPages);
    if (!result.ok) {
      showError(result.error);
      inputElement?.focus?.();
      return false;
    }
    showError('');
    if (result.page === state.page) return true;
    return run(() => settings.onPageChange?.(result.page));
  };
  const click = event => {
    const jumpButton = event.target?.closest?.('[data-pagination-jump]');
    if (jumpButton) {
      event.preventDefault?.();
      void jump();
      return;
    }
    const pageButton = event.target?.closest?.('[data-pagination-page]');
    if (!pageButton || pageButton.disabled) return;
    const page = positiveInteger(pageButton.dataset?.paginationPage, state.page);
    if (page === state.page) return;
    event.preventDefault?.();
    void run(() => settings.onPageChange?.(page));
  };
  const keydown = event => {
    if (event.key !== 'Enter' || !event.target?.matches?.('[data-pagination-input]')) return;
    event.preventDefault?.();
    void jump();
  };
  const change = event => {
    if (!event.target?.matches?.('[data-pagination-size]')) return;
    const pageSize = positiveInteger(event.target.value, state.pageSize);
    if (pageSize === state.pageSize) return;
    void run(() => settings.onPageSizeChange?.(pageSize));
  };
  const destroy = () => {
    if (!active) return;
    active = false;
    root.removeEventListener('click', click);
    root.removeEventListener('keydown', keydown);
    root.removeEventListener('change', change);
    if (root.__platformPaginationDestroy === destroy) {
      delete root.__platformPaginationDestroy;
    }
  };

  root.addEventListener('click', click);
  root.addEventListener('keydown', keydown);
  root.addEventListener('change', change);
  root.__platformPaginationDestroy = destroy;
  paint();
  return {
    update(nextInput = {}, nextOptions = settings) {
      state = normalizePagination(nextInput);
      settings = {...nextOptions};
      paint();
    },
    destroy,
  };
}

export const paginationPageSizes = DEFAULT_PAGE_SIZES;
