export function createModalStack() {
  const items = [];
  return {
    push: item => items.push(item),
    pop: () => items.pop(),
    peek: () => items.at(-1),
    size: () => items.length
  };
}

// Extend the existing native title/aria descriptions through one delegated owner.
// Text and business actions stay on their original controls, including SVG charts.
export function installModalPresentation({doc = document, win = window} = {}) {
  if (win.ModalPresentationRuntime) return win.ModalPresentationRuntime;
  const tip = doc.createElement('div');
  tip.id = 'platform-icon-description';
  tip.className = 'ui-icon-tooltip';
  tip.setAttribute('role', 'tooltip');
  tip.setAttribute('popover', 'manual');
  tip.hidden = true;
  doc.body.appendChild(tip);
  const controller = new AbortController();
  let active = null;
  let described = null;
  let savedTitle = null;
  function hideTooltip() {
    if (active) {
      if (described === null) active.removeAttribute('aria-describedby');
      else active.setAttribute('aria-describedby', described);
      if (savedTitle !== null) active.setAttribute('title', savedTitle);
    }
    active = null;
    savedTitle = null;
    tip.hidden = true;
    if (tip.matches(':popover-open')) tip.hidePopover();
  }
  function position(x, y) {
    if (!active?.isConnected) return hideTooltip();
    const box = tip.getBoundingClientRect();
    let left = x + 14, top = y + 18;
    if (left + box.width > win.innerWidth - 8) left = x - box.width - 14;
    if (top + box.height > win.innerHeight - 8) top = y - box.height - 12;
    tip.style.left = `${Math.max(8, Math.min(left, win.innerWidth-box.width-8))}px`;
    tip.style.top = `${Math.max(8, Math.min(top, win.innerHeight-box.height-8))}px`;
  }
  function enter(event) {
    if (event.pointerType === 'touch') return;
    const node = event.target.closest?.('button[title],a[title],button[aria-label],.icon,[data-icon-hint],svg circle,svg rect');
    if (!node || node === active || node.disabled) return;
    const text = node.getAttribute('title') || node.getAttribute('aria-label') || node.querySelector('title')?.textContent;
    if (!text?.trim()) return;
    hideTooltip();
    active = node;
    described = node.getAttribute('aria-describedby');
    savedTitle = node.getAttribute('title');
    if (savedTitle !== null) node.removeAttribute('title');
    node.setAttribute('aria-describedby', [described,tip.id].filter(Boolean).join(' '));
    tip.textContent = text.trim();
    tip.hidden = false;
    tip.showPopover?.();
    const box = node.getBoundingClientRect();
    position(event.type === 'focusin' ? box.left : event.clientX, event.type === 'focusin' ? box.bottom : event.clientY);
  }
  const options = {signal: controller.signal};
  doc.addEventListener('pointerover', enter, options);
  doc.addEventListener('focusin', enter, options);
  doc.addEventListener('pointermove', event => {if (active) position(event.clientX,event.clientY);}, {...options,passive:true});
  doc.addEventListener('pointerout', event => {if (active && !active.contains(event.relatedTarget)) hideTooltip();}, options);
  doc.addEventListener('focusout', hideTooltip, options);
  doc.addEventListener('pointerdown', hideTooltip, options);
  doc.addEventListener('keydown', event => {if (event.key === 'Escape') hideTooltip();}, options);
  doc.addEventListener('scroll', hideTooltip, {...options,capture:true,passive:true});
  win.addEventListener('resize', hideTooltip, options);
  const runtime = {hideTooltip, destroy() {hideTooltip();controller.abort();tip.remove();delete win.ModalPresentationRuntime;}};
  win.ModalPresentationRuntime = runtime;
  return runtime;
}

export function loadingSkeleton(label = '正在读取数据') {
  const text = String(label).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  return `<section class="ui-skeleton" aria-busy="true" role="status" aria-label="${text}"><div class="loading">${text}</div><div class="ui-skeleton-block ui-skeleton-title"></div><div class="ui-skeleton-block ui-skeleton-filter"></div><div class="ui-skeleton-cards">${'<div class="ui-skeleton-block ui-skeleton-card"></div>'.repeat(3)}</div><div class="ui-skeleton-block ui-skeleton-chart"></div><div class="ui-skeleton-block ui-skeleton-table"></div></section>`;
}

