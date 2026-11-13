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


test('13B scoped report CSS preserves normal, minimized import and nested dialog scroll owners',async({page})=>{
  await page.setViewportSize({width:1280,height:720});
  await ready(page);

  await page.evaluate(()=>window.modal('ZIP 导入布局回归','<section style="height:1700px">导入正文</section>',true));
  const importModal=page.locator('#modal');
  await expect(importModal.locator('[data-import-minimize]')).toBeVisible();
  await importModal.locator('[data-import-minimize]').click();
  await expect(importModal).toHaveClass(/import350-minimized/);
  const minimized=await importModal.evaluate(node=>({
    overflowY:getComputedStyle(node).overflowY,
    contents:getComputedStyle(node.querySelector('.modal-body')).display,
  }));
  expect(minimized.overflowY).not.toBe('auto');
  expect(minimized.contents).toBe('none');
  await page.evaluate(()=>window.closeModal());

  await page.evaluate(()=>window.modal('算法综合训练报告','<section data-algorithm-report-loading><div style="height:2200px">报告加载长内容</div></section>',true));
  const report=page.getByRole('dialog',{name:'算法综合训练报告',exact:true});
  const reportCard=report.locator('.modal-card'),reportBody=report.locator('.modal-body');
  await expect(report).toBeVisible();
  const frame=await reportCard.evaluate(node=>{const bounds=node.getBoundingClientRect();return{top:bounds.top,bottom:bounds.bottom}});
  expect(frame.top).toBeGreaterThanOrEqual(-2);
  expect(frame.bottom).toBeLessThanOrEqual(722);
  await reportBody.evaluate(node=>{node.scrollTop=350});
  expect(await reportBody.evaluate(node=>node.scrollTop)).toBeGreaterThan(0);

  await page.evaluate(()=>window.modal('普通二次确认','<p>应当只是小型确认窗口</p>',false));
  const child=page.getByRole('dialog',{name:'普通二次确认',exact:true});
  await expect(child).toBeVisible();
  const childHeight=await child.locator('.modal-card').evaluate(node=>node.getBoundingClientRect().height);
  expect(childHeight).toBeLessThan(500);
  await page.keyboard.press('Escape');
  await expect(child).toHaveCount(0);
  await expect(report).toBeVisible();
  await reportBody.evaluate(node=>{node.scrollTop=510});
  expect(await reportBody.evaluate(node=>node.scrollTop)).toBeGreaterThan(0);
  await page.evaluate(()=>window.closeModal());
  await expect(report).toBeHidden();
});

test('late annotation save cannot dismiss a newly reused base modal', async ({page}) => {
  await ready(page);
  await expect(page.locator('#modal')).toBeHidden();
  const evidence = await page.evaluate(async () => {
    const originalSave = window.saveAnn;
    const originalWorkbench = state.annotationWorkbench;
    const originalEditor = state.annotationEditor;
    let signalSaveStarted;
    let releaseSave;
    const saveStarted = new Promise(resolve => {signalSaveStarted = resolve;});
    const holdSave = new Promise(resolve => {releaseSave = resolve;});
    let saveCalls = 0;
    let cancelCalls = 0;
    try {
      window.saveAnn = async () => {
        saveCalls++;
        signalSaveStarted();
        await holdSave;
        return true;
      };
      state.annotationWorkbench = {dirty:true, cancel() {cancelCalls++}};
      state.annotationEditor = {flush() {}};
      window.modal('原标注弹窗', '<section class="ann420-stable"><input value="原草稿"></section>');
      const oldClose = window.closeModal();
      await saveStarted;
      // A different owner retires the original base layer while saving.
      window.closeModalCore424();
      // The next modal deliberately reuses #modal, so a DOM identity guard
      // alone would incorrectly close it when the old save finishes.
      window.modal('重新打开的业务弹窗', '<input id="new-modal-draft" value="必须保留">');
      releaseSave();
      const closeResult = await oldClose;
      const root = document.getElementById('modal');
      return {
        closeResult, saveCalls, cancelCalls,
        title:root.querySelector('#modalTitle')?.textContent,
        draft:root.querySelector('#new-modal-draft')?.value,
        hidden:root.classList.contains('hidden'),
      };
    } finally {
      releaseSave?.();
      window.saveAnn = originalSave;
      state.annotationWorkbench = originalWorkbench;
      state.annotationEditor = originalEditor;
      await window.closeModal();
    }
  });
  expect(evidence).toMatchObject({
    closeResult:false,
    saveCalls:1,
    cancelCalls:0,
    title:'重新打开的业务弹窗',
    draft:'必须保留',
    hidden:false,
  });
});
