import {test, expect} from '@playwright/test';

test.use({trace: 'on'});

async function algorithms(page) {
  // Shared backend fixtures may contain live ZIPs from earlier specs. Use an empty
  // isolated project rather than misclassifying their legitimate inventory poll.
  const response = await page.request.post('/api/projects', {data:{name:`行菜单隔离-${Date.now()}`,labels:[]}});
  expect(response.ok()).toBe(true);
  const project = await response.json();
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', project.id);
    await route.continue({url:url.toString()});
  });
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state.uiReady))).toBe(true);
  await expect.poll(() => page.evaluate(() => state.project?.id)).toBe(project.id);
  await expect.poll(() => page.evaluate(() => Boolean(window.ZipImportRuntime))).toBe(true);
  await page.evaluate(() => window.ZipImportRuntime.reconcile('browser-test-setup'));
  await page.evaluate(() => window.setPage('算法列表'));
  await expect.poll(() => page.evaluate(() => window.AlgorithmListRuntime?.state().inflight)).toBe(false);
  await page.evaluate(() => {
    state.algorithms = Array.from({length: 1200}, (_, i) => ({id: `menu-${i}`, name: `菜单验收算法 ${i}`, industry: '测试', algorithm_type: 'yolo_ultralytics', versions: []}));
    state.jobs = [];
    window.AlgorithmListRuntime.resetFilters();
    window.AlgorithmListRuntime.render();
  });
}

test('row menu: measured response, viewport, keyboard and single owner', async ({page}, info) => {
  await algorithms(page);
  const cdp = await page.context().newCDPSession(page);
  const trace = [];
  cdp.on('Tracing.dataCollected', ({value}) => trace.push(...value));
  await cdp.send('Tracing.start', {categories: 'devtools.timeline,blink.user_timing', transferMode: 'ReportEvents'});
  const measures = [];
  const api = [];
  page.on('request', req => { if (new URL(req.url()).pathname.startsWith('/api/')) api.push(req.url()); });
  for (const [width, height] of [[1920,1080], [1440,900], [1366,768], [375,812]]) {
    await page.setViewportSize({width, height});
    const summary = page.locator('.entity-more summary').first();
    await summary.scrollIntoViewIfNeeded();
    const result = await summary.evaluate(async el => {
      const card = el.closest('[data-algorithm-id]');
      const start = performance.now();
      el.click();
      await new Promise(requestAnimationFrame);
      await new Promise(requestAnimationFrame);
      const menu = document.querySelector('.entity-action-menu') || el.nextElementSibling;
      const rect = menu.getBoundingClientRect();
      return {ms: performance.now() - start, width: rect.width, height: rect.height, x: rect.x, y: rect.y,
        font: getComputedStyle(menu.querySelector('button')).fontSize,
        itemHeight: menu.querySelector('button').getBoundingClientRect().height,
        sameCard: card === document.querySelector('[data-algorithm-id="' + card.dataset.algorithmId + '"]') && el.isConnected};
    });
    measures.push({viewportWidth: width, viewportHeight: height, ...result});
    await page.locator('.entity-action-menu').evaluate(el => Promise.all(el.getAnimations().map(animation => animation.finished)));
    await page.screenshot({path: info.outputPath(`after-${width}.png`)});
    {
      expect(result.ms).toBeLessThan(100);
      expect(result.width).toBeGreaterThanOrEqual(220);
      expect(result.itemHeight).toBeGreaterThanOrEqual(42);
      expect(parseFloat(result.font)).toBeGreaterThanOrEqual(14);
      expect(result.x).toBeGreaterThanOrEqual(0);
      expect(result.y).toBeGreaterThanOrEqual(0);
      expect(result.x + result.width).toBeLessThanOrEqual(width);
      expect(result.y + result.height).toBeLessThanOrEqual(height);
      expect(result.sameCard).toBe(true);
    }
    await page.keyboard.press('Escape');
  }
  await info.attach('menu-performance', {body: JSON.stringify(measures, null, 2), contentType:'application/json'});
  const ended = new Promise(resolve => cdp.once('Tracing.tracingComplete', resolve));
  await cdp.send('Tracing.end');
  await ended;
  await info.attach('chrome-performance', {body: JSON.stringify({traceEvents: trace}), contentType: 'application/json'});
  console.log('AFTER', JSON.stringify(measures));
  expect(api).toEqual([]);
  await expect(page.locator('.nav-project, #projectBadge')).toHaveCount(0);
  const first = page.locator('.entity-more summary').first();
  await first.focus();
  await page.keyboard.press('Enter');
  await expect(page.locator('.entity-action-menu')).toBeVisible();
  await expect(first).toHaveAttribute('aria-expanded', 'true');
  await page.keyboard.press('Escape');
  await expect(first).toBeFocused();
  await expect(page.locator('.entity-action-menu')).toHaveCount(0);
  await first.click();
  await page.locator('.entity-more summary').nth(1).click();
  await expect(page.locator('.entity-action-menu')).toHaveCount(1);
  await expect(first).toHaveAttribute('aria-expanded', 'false');
  await page.locator('#title').click();
  await expect(page.locator('.entity-action-menu')).toHaveCount(0);
});

test('training polling preserves open menu, changed actions and pagination invalidate it', async ({page}, info) => {
  await algorithms(page);
  await page.evaluate(() => window.setPage('训练任务'));
  await expect.poll(() => page.evaluate(() => window.TrainingTaskRuntime?.state().inflight)).toBe(false);
  await page.evaluate(() => {
    window.PollRegistryRuntime.clear('training-jobs');
    state.jobs = Array.from({length: 1200}, (_, i) => ({id: `menu-job-${i}`, status: 'running', progress_percent: 10, current_epoch: 1, total_epochs: 100, asset_algorithm_name: `菜单训练 ${i}`}));
    window.TrainingTaskVisibilityRuntime.render();
  });
  const summary = page.locator('.entity-more summary').first();
  await summary.click();
  const retained = await page.evaluate(() => {
    const original = document.querySelector('.entity-more summary');
    state.jobs[0].progress_percent = 20;
    state.jobs[0].current_epoch = 2;
    window.TrainingTaskVisibilityRuntime.render();
    return original === document.querySelector('.entity-more summary');
  });
  await info.attach('polling-evidence', {body: JSON.stringify({retained}), contentType:'application/json'});
  console.log('POLLING', {retained});
  expect(retained).toBe(true);
  await expect(page.locator('.entity-action-menu')).toBeVisible();
  await page.route('**/api/projects/*/jobs', async route => {
    const jobs = await page.evaluate(() => state.jobs.map(job => ({...job, progress_percent: 21, current_epoch: 3})));
    await route.fulfill({json:jobs});
  });
  await page.evaluate(() => window.TrainingTaskRuntime.refresh({render:true,force:true,source:'browser-test'}));
  await expect(page.locator('.entity-action-menu')).toBeVisible();
  await expect(summary).toHaveAttribute('aria-expanded','true');
  await expect(page.locator('[data-job-id="menu-job-0"]')).toContainText('21%');
  for (const [width,height] of [[1920,1080],[1440,900],[1366,768],[375,812]]) {
    await page.keyboard.press('Escape');
    await page.setViewportSize({width,height});
    await summary.scrollIntoViewIfNeeded();
    await summary.click();
    const menu = page.locator('.entity-action-menu');
    await menu.evaluate(el => Promise.all(el.getAnimations().map(animation => animation.finished)));
    const rect = await menu.boundingBox();
    expect(rect.x).toBeGreaterThanOrEqual(8);
    expect(rect.x + rect.width).toBeLessThanOrEqual(width - 8);
    expect(rect.y + rect.height).toBeLessThanOrEqual(height - 8);
    expect(await menu.evaluate(el => {
      const rect = el.querySelector('button').getBoundingClientRect();
      return el.contains(document.elementFromPoint(rect.x + rect.width / 2, rect.y + rect.height / 2));
    })).toBe(true);
    await page.screenshot({path:info.outputPath(`training-${width}.png`)});
  }
  // An anchor outside a shortened viewport must dismiss, not leave a floating action.
  await page.setViewportSize({width:375,height:300});
  await summary.evaluate(el => { for (let parent = el.parentElement; parent; parent = parent.parentElement) parent.scrollTop = 0; });
  expect((await summary.boundingBox()).y).toBeGreaterThanOrEqual(300);
  await expect(page.locator('.entity-action-menu')).toHaveCount(0);
  await page.setViewportSize({width:375,height:812});
  await summary.scrollIntoViewIfNeeded();
  await summary.click();
  // The actual original stop confirmation is still required; dismiss causes no mutation.
  const requests = [];
  page.on('request', req => { if (req.method() === 'POST') requests.push(req.url()); });
  page.once('dialog', dialog => { expect(dialog.message()).toContain('确认停止这个训练任务'); return dialog.dismiss(); });
  await page.getByRole('menuitem', {name:'停止',exact:true}).click();
  expect(requests).toEqual([]);
  await summary.click();
  await page.evaluate(() => { state.jobs[0].status = 'stopping'; window.TrainingTaskVisibilityRuntime.render(); });
  await expect(page.locator('.entity-action-menu')).toHaveCount(0);
  await page.locator('.entity-more summary').first().scrollIntoViewIfNeeded();
  await page.locator('.entity-more summary').first().click();
  await page.getByRole('button', {name: '下一页', exact: true}).click();
  await expect(page.locator('.entity-action-menu')).toHaveCount(0);
  await expect(page.locator('[data-job-id="menu-job-10"]')).toHaveCount(1);
});

test('bottom/scroll boundaries, real pointer response, deletion confirmation and project UI', async ({page}, info) => {
  await algorithms(page);
  const responses = [];
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const [width,height] of [[1920,1080],[1440,900],[1366,768],[375,812]]) {
    await page.setViewportSize({width,height});
    const summary = page.locator('.entity-more summary').last();
    await summary.evaluate(el => el.scrollIntoView({block:'end',inline:'nearest'}));
    await page.evaluate(() => {
      document.addEventListener('pointerup', () => {
        const start = performance.now();
        requestAnimationFrame(() => requestAnimationFrame(() => {
          window.__pointerMenuMs = performance.now() - start;
        }));
      }, {once:true,capture:true});
      window.__pointerMenuMs = null;
    });
    await summary.click();
    await expect.poll(() => page.evaluate(() => window.__pointerMenuMs)).not.toBeNull();
    const elapsed = await page.evaluate(() => window.__pointerMenuMs);
    responses.push({width,height,ms:elapsed});
    expect(elapsed).toBeLessThan(100);
    const anchor = await summary.boundingBox();
    const bounds = await page.locator('.entity-action-menu').boundingBox();
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(anchor.y);
    expect(bounds.x).toBeGreaterThanOrEqual(8);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width - 8);
    expect(await page.locator('.entity-action-menu').evaluate(el => el.matches(':popover-open'))).toBe(true);
    await page.locator('.entity-action-menu').evaluate(el => Promise.all(el.getAnimations().map(animation => animation.finished)));
    await page.screenshot({path:info.outputPath(`bottom-${width}.png`)});
    await page.keyboard.press('Escape');
  }
  console.log('REAL POINTER', JSON.stringify(responses));
  await info.attach('real-pointer-response', {body:JSON.stringify(responses),contentType:'application/json'});
  await page.emulateMedia({reducedMotion:'reduce'});
  const summary = page.locator('.entity-more summary').first();
  await summary.scrollIntoViewIfNeeded();
  await summary.focus();
  await page.keyboard.press('Space');
  await expect(page.getByRole('menuitem', {name:'编辑'})).toBeFocused();
  expect(await page.locator('.entity-action-menu').evaluate(el => el.getAnimations().length)).toBe(0);
  await page.keyboard.press('ArrowDown');
  await expect(page.getByRole('menuitem', {name:'删除',exact:true})).toBeFocused();
  await page.keyboard.press('Escape');
  await summary.focus();
  await page.keyboard.press('Space');
  await page.keyboard.press('Tab');
  await expect(page.locator('.entity-action-menu')).toHaveCount(0);

  let deletes = 0;
  await page.route('**/api/v12/projects/*/algorithms/menu-0', async route => {
    if (route.request().method() !== 'DELETE') return route.continue();
    deletes++;
    await route.fulfill({json:{ok:true}});
  });
  page.once('dialog', dialog => { expect(dialog.message()).toContain('确认删除算法'); return dialog.dismiss(); });
  await summary.click();
  await page.getByRole('menuitem', {name:'删除',exact:true}).click();
  expect(deletes).toBe(0);
  await expect(page.locator('[data-algorithm-id="menu-0"]')).toHaveCount(1);
  page.once('dialog', dialog => dialog.accept());
  await summary.click();
  await page.getByRole('menuitem', {name:'删除',exact:true}).evaluate(el => { el.click(); el.click(); });
  await expect.poll(() => deletes).toBe(1);
  await expect(page.locator('[data-algorithm-id="menu-0"]')).toHaveCount(0);

  const project = await page.evaluate(() => state.project.id);
  await page.evaluate(() => { window.toggleSidebarV37(); window.toggleSidebarV37(); window.renderNav(); });
  await expect(page.locator('.nav-project, #projectBadge')).toHaveCount(0);
  expect(await page.evaluate(() => state.project.id)).toBe(project);
  await page.evaluate(() => { state.algorithms[0].source_type = 'EXTERNAL'; window.AlgorithmListRuntime.render(); });
  await page.locator('.entity-more summary').first().click();
  await expect(page.getByRole('menuitem', {name:'编辑'})).toBeDisabled();
  await expect(page.getByRole('menuitem', {name:'删除',exact:true})).toBeDisabled();
  await page.keyboard.press('Escape');
  await page.reload();
  await expect.poll(() => page.evaluate(() => Boolean(state.uiReady))).toBe(true);
  await expect(page.locator('.nav-project, #projectBadge')).toHaveCount(0);
  expect(await page.evaluate(() => state.project.id)).toBe(project);
  expect(errors).toEqual([]);
});
