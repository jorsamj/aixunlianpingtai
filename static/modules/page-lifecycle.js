function abortReason(message) {
  try { return new DOMException(message, 'AbortError'); }
  catch (_error) { return new Error(message); }
}

export function createPageLifecycle({getPage = () => ''} = {}) {
  let page = String(getPage() || '');
  let pageGeneration = 0;
  let pageController = new AbortController();
  let modalGeneration = 0;
  let modalController = null;
  let bootstrapPromise = null;
  const requests = new Map();
  const disposers = new Set();

  function disposeSet(reason) {
    for (const dispose of [...disposers]) {
      disposers.delete(dispose);
      try { dispose(reason); } catch (error) { console.error(error); }
    }
  }

  function abortRequests(reason) {
    for (const controller of requests.values()) controller.abort(reason);
    requests.clear();
  }

  function leave(reason = 'page-leave') {
    pageController.abort(abortReason(reason));
    closeModal(reason);
    abortRequests(abortReason(reason));
    disposeSet(reason);
  }

  function enter(nextPage) {
    const normalized = String(nextPage || '');
    if (normalized === page && !pageController.signal.aborted) return token();
    leave('page-leave');
    page = normalized;
    pageGeneration += 1;
    pageController = new AbortController();
    return token();
  }

  function token() {
    return {page, generation: pageGeneration, signal: pageController.signal};
  }

  function isCurrent(value) {
    return Boolean(value && value.page === page && value.generation === pageGeneration && !value.signal?.aborted);
  }

  function request(key) {
    const name = String(key || 'default');
    requests.get(name)?.abort(abortReason('request-replaced'));
    const controller = new AbortController();
    const current = token();
    const onPageAbort = () => controller.abort(pageController.signal.reason || abortReason('page-leave'));
    current.signal.addEventListener('abort', onPageAbort, {once: true});
    requests.set(name, controller);
    const release = () => {
      current.signal.removeEventListener('abort', onPageAbort);
      if (requests.get(name) === controller) requests.delete(name);
    };
    return {key: name, signal: controller.signal, token: current, isCurrent: () => isCurrent(current) && !controller.signal.aborted, release};
  }

  function openModal() {
    closeModal('modal-replaced');
    modalGeneration += 1;
    modalController = new AbortController();
    return {generation: modalGeneration, signal: modalController.signal};
  }

  function closeModal(reason = 'modal-close') {
    if (!modalController) return;
    modalController.abort(abortReason(reason));
    modalController = null;
  }

  function signal({modal = false} = {}) {
    return modal && modalController ? modalController.signal : pageController.signal;
  }

  function onLeave(dispose) {
    if (typeof dispose !== 'function') return () => {};
    disposers.add(dispose);
    return () => disposers.delete(dispose);
  }

  function listen(target, type, listener, options) {
    target?.addEventListener?.(type, listener, options);
    const dispose = () => target?.removeEventListener?.(type, listener, options);
    onLeave(dispose);
    return dispose;
  }

  function startPolling(key, callback, delay = 1600) {
    const scope = request(`poll:${key}`);
    let timer = null;
    const stop = () => {
      if (timer != null) clearTimeout(timer);
      timer = null;
      scope.release();
    };
    const tick = async () => {
      if (!scope.isCurrent()) return stop();
      try { await callback({signal: scope.signal, token: scope.token}); }
      catch (error) { if (error?.name !== 'AbortError') throw error; }
      if (scope.isCurrent()) timer = setTimeout(tick, delay);
    };
    timer = setTimeout(tick, 0);
    scope.signal.addEventListener('abort', stop, {once: true});
    return stop;
  }

  function guard(callback, captured = token()) {
    return (...args) => isCurrent(captured) ? callback(...args) : undefined;
  }

  function bootstrap(callback) {
    if (!bootstrapPromise) bootstrapPromise = Promise.resolve().then(callback).catch(error => {
      bootstrapPromise = null;
      throw error;
    });
    return bootstrapPromise;
  }

  return {enter, leave, token, isCurrent, request, openModal, closeModal, signal, onLeave, listen, startPolling, guard, bootstrap};
}
