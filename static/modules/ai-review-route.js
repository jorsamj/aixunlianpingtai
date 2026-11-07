// Address-bar state for the existing AI Candidate review owner. This module
// never reads candidates, decides annotations or commits GT.
const REVIEW_PREFIX = '#ai-review/';
const TASK_ID = /^[A-Za-z0-9_-]{1,128}$/;

export function readAiReviewRoute(hash) {
  const raw = String(hash || '');
  if (!raw.startsWith(REVIEW_PREFIX)) return null;
  try {
    const id = decodeURIComponent(raw.slice(REVIEW_PREFIX.length));
    return TASK_ID.test(id) ? id : null;
  } catch (_) {
    return null;
  }
}

export function aiReviewUrl(href, id) {
  if (!TASK_ID.test(String(id || ''))) throw new Error('无效的AI审核任务编号');
  const url = new URL(href);
  url.hash = `ai-review/${encodeURIComponent(id)}`;
  return url.pathname + url.search + url.hash;
}

export function aiReviewListUrl(href) {
  const url = new URL(href);
  if (readAiReviewRoute(url.hash)) url.hash = '';
  return url.pathname + url.search + url.hash;
}

export function installAiReviewRoute({getReview, open, close, notify} = {}) {
  if (typeof window === 'undefined') return null;
  let navigationEpoch = 0;
  const routeId = () => readAiReviewRoute(window.location.hash);
  const restoreAddress = id => {
    window.history.pushState({aiReviewTask:id}, '', aiReviewUrl(window.location.href, id));
  };
  const runtime = {
    open(id) {
      if (routeId() !== String(id)) restoreAddress(String(id));
    },
    leave() {
      if (routeId()) window.history.replaceState(null, '', aiReviewListUrl(window.location.href));
    },
    beforeNavigate(page) {
      if (page === '自动标注及清洗') return true;
      const review = getReview?.();
      if (!review || review.closed) {runtime.leave();return true}
      return close?.({skipRender:true}) !== false;
    },
    async restore() {
      const epoch = ++navigationEpoch;
      const id = routeId();
      const review = getReview?.();
      if (!id) {
        if (review && !review.closed && close?.({fromRoute:true}) === false) {
          restoreAddress(String(review.id));
        }
        return;
      }
      if (review && !review.closed && String(review.id) === id) return;
      try {
        const result = await open?.(id, {fromRoute:true});
        if (epoch !== navigationEpoch) return;
        if (result === false && getReview?.()?.id !== id) {
          const active = getReview?.();
          if (active && !active.closed) restoreAddress(String(active.id));
        }
      } catch (error) {
        if (epoch === navigationEpoch) notify?.(error?.message || error);
      }
    },
  };
  window.addEventListener('popstate', () => {void runtime.restore()});
  window.addEventListener('hashchange', () => {void runtime.restore()});
  return runtime;
}
