import {test, expect} from '@playwright/test';


async function createReviewProject(request) {
  const labels = [
    {code:'person',display_name:'人员',color:'#3b82f6'},
    {code:'helmet',display_name:'安全帽',color:'#ef4444'},
    ...Array.from({length:32},(_,index)=>({
      code:`label_${String(index+1).padStart(2,'0')}`,
      display_name:`平台标签 ${String(index+1).padStart(2,'0')}`,
      color:'#64748b',
    })),
  ];
  const response = await request.post('/api/projects',{data:{
    name:`AI审核浏览器-${Date.now()}`,
    labels,
  }});
  expect(response.ok()).toBeTruthy();
  return response.json();
}

async function selectReviewProject(page, projectId) {
  await page.route('**/api/v53/bootstrap/snapshot**', async route => {
    const url = new URL(route.request().url());
    url.searchParams.set('preferred_project_id', projectId);
    await route.fallback({url:url.toString()});
  });
  await page.addInitScript(() => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({page:'自动标注及清洗'}));
  });
}


test('auto-label active task polling updates rows without replacing the page root and stops on navigation', async ({page}) => {
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error));

  let requests = 0;
  await page.route(/\/api\/v60\/projects\/[^/]+\/annotation-tasks\?limit=50$/, async route => {
    requests += 1;
    const completed = Math.min(3, requests);
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({items: [{
        id: 'auto-browser-1',
        name: '浏览器自动标注任务',
        status: 'RUNNING',
        requested_labels: ['fire'],
        progress: completed * 25,
        completed_count: completed,
        total_count: 4,
        failed_count: 0,
        created_at: '2026-09-11T00:00:00Z',
        updated_at: '2026-09-11T00:00:10Z',
        summary: {total: 4, completed, failed: 0, boxes: completed * 2},
      }]})
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect.poll(() => page.evaluate(() => window.AutoLabelPollRuntime?.build || null))
    .toBe('auto-label-poll-422502');
  expect(await page.evaluate(() => ({
    wrapper: window.AutoLabelPollRuntime?.snapshot?.().classicWrapperOwner,
    timer: window.AutoLabelPollRuntime?.snapshot?.().timerOwner,
  }))).toEqual({wrapper: false, timer: false});

  await page.evaluate(() => window.setPage('自动标注及清洗'));
  await expect(page.locator('#title')).toContainText('自动标注及清洗');
  await expect(page.locator('#ai60TaskRows')).toBeVisible({timeout: 10_000});
  await expect(page.locator('#ai60TaskRows')).toContainText('浏览器自动标注任务');

  await page.evaluate(() => {
    window.__autoLabelStableRoot = document.getElementById('view');
    window.__autoLabelStableRow = document.querySelector('[data-task-id="auto-browser-1"]');
    window.__autoLabelStableProgress = window.__autoLabelStableRow?.querySelector('.op427-progress em') || null;
  });

  await expect.poll(async () => page.evaluate(() => {
    const row = window.PollRegistryRuntime?.snapshot?.().find(item => item.key === 'auto-label-v60');
    return row ? {managed: row.managed, delay: row.delay} : null;
  })).toEqual({managed: true, delay: 1800});

  await expect.poll(() => requests, {timeout: 8_000}).toBeGreaterThanOrEqual(2);
  await expect.poll(async () => page.evaluate(() => {
    const text = document.querySelector('[data-task-id="auto-browser-1"]')?.textContent || '';
    const match = text.match(/(\d+)\s*\/\s*4/);
    return match ? Number(match[1]) : 0;
  }), {timeout: 8_000}).toBeGreaterThanOrEqual(2);
  const completedProgress = await page.evaluate(() => {
    const text = document.querySelector('[data-task-id="auto-browser-1"]')?.textContent || '';
    const match = text.match(/(\d+)\s*\/\s*4/);
    return match ? Number(match[1]) : 0;
  });
  expect(completedProgress).toBeLessThanOrEqual(3);

  const rootStayedStable = await page.evaluate(() => (
    window.__autoLabelStableRoot === document.getElementById('view')
  ));
  expect(rootStayedStable).toBe(true);
  expect(await page.evaluate(() => (
    window.__autoLabelStableRow === document.querySelector('[data-task-id="auto-browser-1"]')
  ))).toBe(true);
  expect(await page.evaluate(() => (
    window.__autoLabelStableProgress === document.querySelector('[data-task-id="auto-browser-1"] .op427-progress em')
  ))).toBe(true);

  await page.evaluate(() => window.setPage('数据集'));
  await expect(page.locator('#title')).toContainText('数据集');
  await expect.poll(async () => page.evaluate(() => (
    window.PollRegistryRuntime?.snapshot?.().some(item => item.key === 'auto-label-v60') || false
  ))).toBe(false);

  expect(pageErrors).toEqual([]);
});


test('AI candidate review keeps searchable mapping edits and inline labels through accept-all', async ({page,request}) => {
  const project = await createReviewProject(request);
  const encoded = encodeURIComponent(project.id);
  await selectReviewProject(page, project.id);

  const pixel='data:image/svg+xml,%3Csvg xmlns="http://www.w3.org/2000/svg" width="100" height="80"%3E%3Crect width="100" height="80" fill="%23ddd"/%3E%3C/svg%3E';
  const sourceLabels=['toukui1','toukui2','smoke_old'];
  const items=Array.from({length:54},(_,index)=>{
    const label=sourceLabels[index%sourceLabels.length];
    return {
      image_id:`candidate-${index+1}`,
      filename:`candidate-${String(index+1).padStart(2,'0')}.jpg`,
      url:pixel,
      width:100,
      height:80,
      status:'candidate',
      accepted:true,
      boxes:[{
        id:`box-${index+1}`,
        label,
        class_id:index%3,
        x1:10,y1:10,x2:60,y2:55,
        confidence:0.88,
        source:'ai_candidate',
      }],
    };
  });
  const labelSummary=sourceLabels.map(label=>({
    label,
    images:items.filter(item=>item.boxes[0].label===label).length,
    boxes:items.filter(item=>item.boxes[0].label===label).length,
  }));

  let decisionsBody=null;
  let candidateRace=false;
  await page.route(`**/api/v60/projects/${encoded}/annotation-tasks?limit=50`, async route => {
    await route.fulfill({
      status:200,
      contentType:'application/json',
      body:JSON.stringify({items:[{
        id:'review-browser-1',
        name:'AI候选审核浏览器任务',
        status:'AWAITING_CONFIRMATION',
        phase:'AWAITING_CONFIRMATION',
        requested_labels:sourceLabels,
        progress:100,
        completed_count:54,
        total_count:54,
        failed_count:0,
        summary:{total:54,completed:54,failed:0,boxes:54},
        created_at:'2026-09-23T00:00:00Z',
        updated_at:'2026-09-23T00:01:00Z',
      }]}),
    });
  });
  await page.route(`**/api/v60/projects/${encoded}/annotation-tasks/review-browser-1/candidates**`, async route => {
    const url=new URL(route.request().url());
    const cursor=Number(url.searchParams.get('cursor')||0);
    const limit=Number(url.searchParams.get('limit')||24);
    if(candidateRace&&cursor===0)await new Promise(resolve=>setTimeout(resolve,260));
    if(candidateRace&&cursor===48)await new Promise(resolve=>setTimeout(resolve,20));
    await route.fulfill({
      status:200,
      contentType:'application/json',
      body:JSON.stringify({
        total:items.length,
        items:items.slice(cursor,cursor+limit),
        label_summary:labelSummary,
      }),
    });
  });
  await page.route(`**/api/v60/projects/${encoded}/annotation-tasks/review-browser-1`, async route => {
    await route.fulfill({
      status:200,
      contentType:'application/json',
      body:JSON.stringify({
        id:'review-browser-1',name:'AI候选审核浏览器任务',status:'SUCCEEDED',phase:'SUCCEEDED',
        progress:100,completed_count:54,total_count:54,failed_count:0,
        summary:{total:54,completed:54,failed:0,boxes:54},
        created_at:'2026-09-23T00:00:00Z',updated_at:'2026-09-23T00:02:00Z',
      }),
    });
  });

  await page.route(`**/api/v60/projects/${encoded}/annotation-tasks/review-browser-1/decisions`, async route => {
    decisionsBody=route.request().postDataJSON();
    await route.fulfill({
      status:200,
      contentType:'application/json',
      body:JSON.stringify({
        ok:true,
        queued_for_commit:true,
        task:{
          id:'review-browser-1',name:'AI候选审核浏览器任务',status:'QUEUED',phase:'REVIEW_QUEUED',
          progress:92,completed_count:54,total_count:54,failed_count:0,
          summary:{total:54,completed:54,failed:0,boxes:54},
          created_at:'2026-09-23T00:00:00Z',updated_at:'2026-09-23T00:01:30Z',
        },
        review:{total:54,accepted:54,rejected:0,unreviewed:0,failed:0},
        label_summary:labelSummary,
      }),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toContainText('自动标注及清洗',{timeout:15_000});
  const taskRow=page.locator('#ai60TaskRows [data-task-id="review-browser-1"]');
  await expect(taskRow).toBeVisible({timeout:10_000});
  await taskRow.getByRole('button',{name:'审核'}).click();

  const review=page.getByRole('dialog',{name:'AI待确认标注 · 审核工作台',exact:true});
  await expect(review).toBeVisible();
  await expect(review.locator('#ai60ReviewGrid .review427-card')).toHaveCount(24);
  await expect(review.locator('#ai60PlatformLabelOptions option')).toHaveCount(34);

  const mappingRoot=review.locator('#ai60LabelMapping');
  await expect(mappingRoot.locator('.ai60-mapping-row')).toHaveCount(3);
  await page.evaluate(() => {
    window.__stableAiMappingFirst = document.querySelector('#ai60LabelMapping .ai60-mapping-row');
    window.renderAiLabelMapping60?.();
  });
  expect(await page.evaluate(() =>
    window.__stableAiMappingFirst === document.querySelector('#ai60LabelMapping .ai60-mapping-row')
  )).toBe(true);

  const sourceFilter=mappingRoot.getByPlaceholder('筛选来源标签');
  await sourceFilter.fill('toukui2');
  await expect(mappingRoot.locator('.ai60-mapping-row:not([hidden])')).toHaveCount(1);
  await expect(mappingRoot.locator('.ai60-mapping-row:not([hidden])')).toHaveAttribute('data-ai-label-source','toukui2');
  await sourceFilter.fill('');

  await mappingRoot.locator('#ai60MapAllTarget').fill('helmet');
  await mappingRoot.getByRole('button',{name:'全部映射'}).click();
  await expect(mappingRoot.locator('.ai60-label-combobox')).toHaveCount(3);
  for(const input of await mappingRoot.locator('.ai60-label-combobox').all()){
    await expect(input).toHaveValue('helmet');
  }

  const smokeRow=mappingRoot.locator('.ai60-mapping-row[data-ai-label-source="smoke_old"]');
  await smokeRow.getByRole('button',{name:'＋ 新建标签'}).click();
  const create=page.getByRole('dialog',{name:'新建平台标签'});
  await expect(create).toBeVisible();
  await create.locator('#inlineLabel414Code').fill('smoke');
  await create.locator('#inlineLabel414Name').fill('烟雾');
  await create.getByRole('button',{name:'创建并使用'}).click();
  await expect(create).toBeHidden();
  await expect(review).toBeVisible();
  await expect(smokeRow.locator('.ai60-label-combobox')).toHaveValue('smoke');
  await expect(review.locator('#ai60PlatformLabelOptions option[value="smoke"]')).toHaveCount(1);

  await review.locator('#ai60BulkTarget').fill('person');
  await review.getByRole('button',{name:'应用到已勾选图片'}).click();
  await expect(review.locator('#ai66Edited')).toHaveText('24');

  const firstCard=review.locator('#ai60ReviewGrid .review427-card').first();
  await firstCard.getByRole('button',{name:'编辑候选框'}).click();
  const editor=page.getByRole('dialog',{name:'编辑AI候选框'});
  await expect(editor).toBeVisible();
  await editor.locator('.ai66-edit-object select').first().selectOption('helmet');
  await editor.locator('.ai66-edit-advanced').evaluate(node=>{node.open=true});
  await editor.locator('.ai66-edit-coord input[type="number"]').first().fill('12');
  await editor.getByRole('button',{name:'保存候选修改'}).click();
  await expect(editor).toBeHidden();
  await expect(review).toBeVisible();

  await review.locator('#ai60ReviewPager').getByRole('button',{name:'下一页'}).click();
  await expect(review.locator('#ai60ReviewGrid .review427-card')).toHaveCount(24);
  await expect(review.locator('#ai60ReviewSummary')).toContainText('第 25–48 / 54 张');
  await expect(review.locator('#ai60ReviewSummary')).toContainText('已人工修改 24 张');
  await review.locator('#ai60ReviewPager').getByRole('button',{name:'上一页'}).click();
  await expect(review.locator('#ai60ReviewGrid .review427-card')).toHaveCount(24);
  await expect(review.locator('#ai60ReviewSummary')).toContainText('第 1–24 / 54 张');
  const firstAfterPaging=review.locator('#ai60ReviewGrid .review427-card').first();
  await expect(firstAfterPaging).toContainText('安全帽');
  await firstAfterPaging.getByRole('button',{name:'编辑候选框'}).click();
  const editorAfterPaging=page.getByRole('dialog',{name:'编辑AI候选框'});
  await expect(editorAfterPaging).toBeVisible();
  await expect(editorAfterPaging.locator('.ai66-edit-object select').first()).toHaveValue('helmet');
  await editorAfterPaging.locator('.ai66-edit-advanced').evaluate(node=>{node.open=true});
  await expect(editorAfterPaging.locator('.ai66-edit-coord input[type="number"]').first()).toHaveValue('12');
  await editorAfterPaging.getByRole('button',{name:'取消'}).click();
  await expect(editorAfterPaging).toBeHidden();
  await expect(review).toBeVisible();

  await review.locator('#ai60ReviewPager').getByRole('button',{name:'下一页'}).click();
  await expect(review.locator('#ai60ReviewSummary')).toContainText('第 25–48 / 54 张');
  candidateRace=true;
  await page.evaluate(() => {
    void window.aiReviewPage60(-1);
    void window.aiReviewPage60(1);
  });
  await expect(review.locator('#ai60ReviewSummary')).toContainText('第 49–54 / 54 张',{timeout:5000});
  await page.waitForTimeout(320);
  await expect(review.locator('#ai60ReviewSummary')).toContainText('第 49–54 / 54 张');
  candidateRace=false;

  await review.locator('#ai60ReviewPager').getByRole('button',{name:'上一页'}).click();
  await expect(review.locator('#ai60ReviewSummary')).toContainText('第 25–48 / 54 张');

  candidateRace=true;
  await page.evaluate(() => { void window.aiReviewPage60(-1); });
  await review.getByRole('button',{name:'全部接受'}).click();
  await expect.poll(()=>decisionsBody,{timeout:5000}).not.toBeNull();
  await expect(review).toBeHidden();
  await page.waitForTimeout(320);
  await expect(review).toBeHidden();
  candidateRace=false;

  expect(decisionsBody.commit).toBe(true);
  expect(decisionsBody.accept_unmentioned).toBe(true);
  expect(decisionsBody.reject_unmentioned).toBe(false);
  expect(decisionsBody.decisions).toHaveLength(24);
  expect(decisionsBody.label_mapping).toEqual({
    toukui1:'helmet',
    toukui2:'helmet',
    smoke_old:'smoke',
  });
  const firstDecision=decisionsBody.decisions.find(item=>item.image_id==='candidate-1');
  expect(firstDecision.accepted).toBe(true);
  expect(firstDecision.boxes).toHaveLength(1);
  expect(firstDecision.boxes[0].label).toBe('helmet');
  expect(firstDecision.boxes[0].x1).toBe(12);
  const secondDecision=decisionsBody.decisions.find(item=>item.image_id==='candidate-2');
  expect(secondDecision.boxes[0].label).toBe('person');

  const labelsResponse=await request.get(`/api/v12/projects/${project.id}/labels`);
  expect(labelsResponse.ok()).toBeTruthy();
  const labels=(await labelsResponse.json()).items||[];
  expect(labels.some(label=>label.code==='smoke'&&label.display_name==='烟雾')).toBe(true);
});
