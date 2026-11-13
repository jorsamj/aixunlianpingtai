import {test, expect} from '@playwright/test';

async function ready(page) {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => state.uiReady), {timeout: 20000}).toBe(true);
}

test('reused base modal retires business layout classes through 100 open/close cycles', async ({page}, testInfo) => {
  test.setTimeout(120000);
  await ready(page);
  const metrics = await page.evaluate(async () => {
    const removed = ['annotation-workbench-layer', 'training-create-modal-layer', 'ai-review-workbench-layer', 'import350-modal', 'import350-minimized'];
    const cardRemoved = ['annotation-workbench-modal', 'training-create-modal-card', 'ai-review-workbench-modal'];
    let maxResidual = 0;
    for (let i = 0; i < 100; i++) {
      window.modal('弹窗复用回归', '<input id="modal-cycle-input" value="draft"><div>正文</div>', true);
      const layer = document.getElementById('modal'), card = layer.querySelector('.modal-card');
      if (layer.classList.contains('hidden')) throw new Error('dialog did not open');
      layer.classList.add(...removed);
      card.classList.add(...cardRemoved);
      // Clearing one dialog must not retire the canonical stack or its business close hooks.
      await window.closeModal();
      const residual = [...removed.filter(name => layer.classList.contains(name)), ...cardRemoved.filter(name => card.classList.contains(name))];
      maxResidual = Math.max(maxResidual, residual.length);
      if (!layer.classList.contains('hidden') || layer.querySelector('#modal-cycle-input')) throw new Error('modal remained open after close');
    }
    window.modal('最终干净弹窗', '<input id="modal-cycle-final">', false);
    const layer = document.getElementById('modal');
    const card = layer.querySelector('.modal-card');
    const result = {
      maxResidual,
      leftoverLayers: document.querySelectorAll('.v424-modal-layer').length,
      widthClass: card.classList.contains('wide'),
      activeTitle: layer.querySelector('.modal-title')?.textContent,
      bodyScrollStyle: getComputedStyle(layer.querySelector('.modal-body')).overflowY,
    };
    await window.closeModal();
    return result;
  });
  expect(metrics).toMatchObject({
    maxResidual: 0,
    leftoverLayers: 0,
    widthClass: false,
    activeTitle: '最终干净弹窗',
    bodyScrollStyle: 'auto',
  });
  await testInfo.attach('modal-100-cycle-evidence.json', {body: JSON.stringify(metrics, null, 2), contentType: 'application/json'});
});

test('Escape closes only the top nested layer and keeps its underlying dialog and draft', async ({page}) => {
  await ready(page);
  await page.evaluate(() => {
    window.modal('父弹窗', '<input id="parent-draft" value="must-survive">');
    window.modal('子弹窗', '<input id="child-draft" value="child">');
  });
  await expect(page.locator('.modal:not(.hidden)')).toHaveCount(2);
  await expect(page.locator('#parent-draft')).toHaveValue('must-survive');
  await page.keyboard.press('Escape');
  await expect(page.locator('.v424-modal-layer')).toHaveCount(0);
  await expect(page.locator('#parent-draft')).toHaveValue('must-survive');
  await expect(page.locator('#modal')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.locator('#modal')).toBeHidden();
});

for (const viewport of [{width: 390, height: 844}, {width: 1280, height: 720}]) {
  test(`long-content modal scroll remains reachable at ${viewport.width}px without changing the page scrolling owner`, async ({page}) => {
    await page.setViewportSize(viewport);
    await ready(page);
    await page.evaluate(() => {
      window.modal('超长内容验证', '<div id="modal-tall-content">' + Array.from({length: 120}, (_, i) => '<p>滚动测试 ' + i + '</p>').join('') + '</div>', true);
    });
    const content = page.locator('#modal .modal-body');
    const layout = await content.evaluate(node => {
      const card = node.closest('.modal-card');
      const box = card.getBoundingClientRect();
      return {
        scrollHeight: node.scrollHeight,
        clientHeight: node.clientHeight,
        top: box.top,
        bottom: box.bottom,
        overflowY: getComputedStyle(node).overflowY,
        bodyOverflow: getComputedStyle(document.body).overflowY,
      };
    });
    expect(layout.scrollHeight).toBeGreaterThan(layout.clientHeight);
    expect(layout.overflowY).toBe('auto');
    expect(layout.top).toBeGreaterThanOrEqual(-2);
    expect(layout.bottom).toBeLessThanOrEqual(viewport.height + 2);
    await content.hover();
    await page.mouse.wheel(0, 680);
    await expect.poll(() => content.evaluate(node => node.scrollTop)).toBeGreaterThan(0);
    await page.evaluate(() => window.closeModal());
    await expect(page.locator('#modal')).toBeHidden();
    // The application intentionally scrolls .view while body remains hidden.
    expect(layout.bodyOverflow).toBe('hidden');
  });
}
