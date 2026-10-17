// One delegated presentation owner for the existing entity-more action markup.
// Business handlers/disabled permissions remain on the original buttons.
export function rowMenuPosition(anchor, menu, viewport) {
  const gap = 6;
  const edge = 8;
  const above = anchor.bottom + gap + menu.height > viewport.height - edge
    && anchor.top - gap - menu.height >= edge;
  return {
    left: Math.max(edge, Math.min(anchor.right - menu.width, viewport.width - menu.width - edge)),
    top: Math.max(edge, Math.min(above ? anchor.top - gap - menu.height : anchor.bottom + gap, viewport.height - menu.height - edge)),
    above,
  };
}

export function installRowActionMenu({doc = document, win = window} = {}) {
  if (win.RowActionMenuRuntime) return win.RowActionMenuRuntime;
  let active = null;
  let exiting = null;
  let frame = 0;
  let serial = 0;
  const paths = {
    edit: 'M16 3l5 5M4 16L16 4l4 4L8 20H4z',
    delete: 'M3 6h18M9 6V3h6v3M5 6l1 15h12l1-15M10 10v7M14 10v7',
    stop: 'M6 6h12v12H6z',
  };

  function close({focus = false, animate = false} = {}) {
    if (!active) return;
    const current = active;
    active = null;
    current.summary.setAttribute('aria-expanded', 'false');
    current.summary.removeAttribute('aria-controls');
    if (focus && current.summary.isConnected) current.summary.focus({preventScroll: true});
    // Remove hit testing immediately; exit motion never leaves a click-blocking layer.
    current.menu.style.pointerEvents = 'none';
    current.menu.inert = true;
    if (animate && !win.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      exiting?.remove();
      exiting = current.menu;
      const motion = current.menu.animate([{opacity: 1}, {opacity: 0}], {duration: 80});
      motion.finished.then(() => current.menu.remove(), () => current.menu.remove());
    } else current.menu.remove();
  }

  function position() {
    if (!active) return;
    const {summary, menu, source} = active;
    if (!summary.isConnected || summary.nextElementSibling !== source || !source.isConnected) return close();
    const anchor = summary.getBoundingClientRect();
    if (anchor.bottom <= 0 || anchor.top >= win.innerHeight || anchor.right <= 0 || anchor.left >= win.innerWidth) return close();
    for (let parent = summary.parentElement; parent && parent !== doc.body; parent = parent.parentElement) {
      const style = win.getComputedStyle(parent);
      if (!/(auto|scroll|hidden|clip)/.test(style.overflowX + style.overflowY)) continue;
      const bounds = parent.getBoundingClientRect();
      if (anchor.bottom <= bounds.top || anchor.top >= bounds.bottom || anchor.right <= bounds.left || anchor.left >= bounds.right) return close();
    }
    const point = rowMenuPosition(anchor, menu.getBoundingClientRect(), {width: win.innerWidth, height: win.innerHeight});
    menu.style.left = `${point.left}px`;
    menu.style.top = `${point.top}px`;
    menu.style.transformOrigin = point.above ? 'bottom right' : 'top right';
  }

  function schedulePosition() {
    if (active && !frame) frame = win.requestAnimationFrame(() => { frame = 0; position(); });
  }

  function open(summary, keyboard) {
    close();
    exiting?.remove();
    exiting = null;
    const source = summary.nextElementSibling;
    if (!source) return;
    const menu = doc.createElement('div');
    menu.className = 'entity-action-menu';
    menu.id = `row-action-menu-${++serial}`;
    menu.setAttribute('role', 'menu');
    menu.setAttribute('aria-label', '记录操作');
    menu.setAttribute('popover', 'manual');
    for (const original of source.querySelectorAll('button')) {
      const item = doc.createElement('button');
      item.type = 'button';
      item.className = original.className;
      item.disabled = original.disabled;
      item.setAttribute('role', 'menuitem');
      const path = original.classList.contains('danger') ? paths.delete : /编辑/.test(original.textContent) ? paths.edit : paths.stop;
      item.innerHTML = `<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="${path}"/></svg>`;
      const label = doc.createElement('span');
      label.textContent = original.textContent;
      item.appendChild(label);
      // Delegate exactly once to the existing business action, never copy/reimplement it.
      item.addEventListener('click', () => {
        if (active?.menu !== menu || original.disabled || !original.isConnected) return;
        close({focus: true});
        original.click();
      });
      menu.appendChild(item);
    }
    summary.setAttribute('aria-expanded', 'true');
    summary.setAttribute('aria-controls', menu.id);
    active = {summary, source, menu};
    doc.body.appendChild(menu);
    menu.showPopover();
    position();
    if (!active) return;
    if (!win.matchMedia('(prefers-reduced-motion: reduce)').matches) {
      menu.animate([{opacity: 0, transform: 'translateY(4px)'}, {opacity: 1, transform: 'translateY(0)'}], {duration: 140, easing: 'cubic-bezier(.2,.8,.2,1)'});
    }
    if (keyboard) menu.querySelector('button:not(:disabled)')?.focus({preventScroll: true});
  }

  doc.addEventListener('click', event => {
    const summary = event.target.closest?.('.entity-more > summary');
    if (summary) {
      event.preventDefault();
      event.stopPropagation();
      if (active?.summary === summary) close({focus: true, animate: true});
      else open(summary, event.detail === 0);
    } else if (active && !active.menu.contains(event.target)) close({animate: true});
  }, true);
  doc.addEventListener('keydown', event => {
    if (!active) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopPropagation();
      close({focus: true});
    } else if (active.menu.contains(event.target)) {
      if (event.key === 'Tab') return close({focus: true});
      const items = [...active.menu.querySelectorAll('button:not(:disabled)')];
      const index = items.indexOf(doc.activeElement);
      const next = {ArrowDown: (index + 1) % items.length, ArrowUp: (index + items.length - 1) % items.length, Home: 0, End: items.length - 1}[event.key];
      if (next != null) { event.preventDefault(); items[next]?.focus(); }
    }
  }, true);
  doc.addEventListener('input', () => close(), true);
  doc.addEventListener('change', () => close(), true);
  doc.addEventListener('scroll', schedulePosition, true);
  win.addEventListener('resize', schedulePosition);
  // Only checks the active anchor; no table scan or business polling.
  const observer = new win.MutationObserver(() => {
    if (active && (!active.summary.isConnected || active.summary.nextElementSibling !== active.source)) close();
    else schedulePosition();
  });
  const view = doc.getElementById('view');
  if (view) observer.observe(view, {childList: true, subtree: true});
  const runtime = {close, build: 'row-action-menu-1'};
  win.RowActionMenuRuntime = runtime;
  return runtime;
}
