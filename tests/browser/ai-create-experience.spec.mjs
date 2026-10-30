import {test, expect} from '@playwright/test';

const PIXEL = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
const models = {items: [{
  id: 'vision-model-1', name: '场景视觉模型', model_name: 'vision-v1',
  provider_type: 'local_openai', provider_adapter: 'local_openai',
  default_for_annotation: true, annotation_prompt_template: '检测 {{labels_json}} {{output_schema}}',
}]};
const templates = {items: [{
  id: 'prompt-1', name: '烟火检测模板', version: 4, version_id: 'prompt-v4',
  model_config_id: 'vision-model-1', labels: ['fire'],
  prompt: '只检测 {{labels_json}}，尺寸 {{image_width}}x{{image_height}}。{{output_schema}}',
}]};
const labels = {items: [
  {code: 'fire', display_name_zh: '明火', status: 'active'},
  {code: 'smoke', display_name_zh: '烟雾', status: 'active'},
]};

async function installDelayedCreationApis(page, {materialDelayMs = 1200} = {}) {
  const requests = [];
  page.on('request', request => requests.push(new URL(request.url()).pathname));
  const delayed = async (route, body, delayMs = 1200) => {
    await new Promise(resolve => setTimeout(resolve, delayMs));
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(body)});
  };
  await page.route('**/api/v35/model-configs', route => delayed(route, models));
  await page.route('**/api/v35/prompt-templates', route => delayed(route, templates));
  await page.route('**/api/v12/projects/*/labels', route => delayed(route, labels));
  await page.route('**/api/v61/projects/*/materials**', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.endsWith('/materials/ids')) {
      await new Promise(resolve => setTimeout(resolve, 3000));
      return route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({items: [], total: 0})});
    }
    const reference = url.searchParams.get('annotated') === 'true';
    return delayed(route, {
      items: Array.from({length: 6}, (_, index) => ({
        id: `${reference ? 'reference' : 'ai-image'}-${index + 1}`,
        filename: `${reference ? 'reference' : 'scene'}-${index + 1}.jpg`, url: PIXEL,
        width: 640, height: 480, annotated: reference,
        labels: reference ? ['smoke'] : [], size_bytes: 1024,
      })),
      total: 50_000, page: 1, page_size: 12, total_pages: 4167, next_cursor: null,
    }, materialDelayMs);
  });
  return requests;
}

async function ready(page) {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => ({
    ui: typeof state !== 'undefined' ? !!state.uiReady : false,
    create: typeof window.createAiLabel429 === 'function',
  })), {timeout: 20_000}).toEqual({ui: true, create: true});
}

test('AI create opens immediately while configuration and material pages load lazily', async ({page}, testInfo) => {
  const requests = await installDelayedCreationApis(page, {materialDelayMs: 10_000});
  await ready(page);
  const before = requests.length;
  const elapsed = await page.evaluate(() => {
    const started = performance.now();
    window.createAiLabel429();
    if (!document.querySelector('.ai-create-workbench')) throw new Error('dialog shell missing');
    return performance.now() - started;
  });
  expect(elapsed).toBeLessThan(300);
  await expect(page.getByRole('dialog', {name: '创建AI自动标注任务'})).toBeVisible();
  await expect(page.locator('#ai429Hydration')).toContainText('正在同步');
  await expect.poll(()=>requests.slice(before).filter(item=>item.endsWith('/materials')).length).toBe(1);
  expect(requests.slice(before).some(item => item.endsWith('/materials/ids'))).toBe(false);

  await expect(page.locator('#ai429Models')).toContainText('场景视觉模型', {timeout: 5000});
  await expect(page.locator('#ai429LabelGrid')).toContainText('明火');
  await expect(page.locator('#ai429MaterialGrid')).toContainText('scene-1.jpg', {timeout: 15_000});
  await expect(page.locator('#ai429MaterialCount')).toContainText('匹配 50000 张');
  await expect(page.locator('#ai429MaterialGrid button')).toHaveCount(6);
  await page.evaluate(() => { document.querySelector('#modalBody').scrollTop = 0; });
  await page.screenshot({path: testInfo.outputPath('ai-create-1366x768.png'), fullPage: false});
  await page.getByRole('button', {name: /明火/}).click();
  await page.locator('#ai429Template').selectOption('prompt-1');
  await expect(page.locator('#ai429Prompt')).toHaveValue(/只检测/);
  await page.locator('.ai-create-preview').click();
  await expect(page.locator('#ai429PromptPreview')).toContainText('"code": "fire"', {timeout: 5000});

  await page.locator('.ai-create-advanced').click();
  await expect(page.locator('#ai429RefGrid')).toContainText('reference-1.jpg', {timeout: 15_000});
  await page.locator('#ai429RefGrid button').first().click();
  await expect(page.locator('#ai429ReferenceCount')).toContainText('已选 1 张');
  await expect(page.locator('#ai429Labels')).toHaveValue('fire');

  await page.screenshot({path: testInfo.outputPath('ai-create-prompt-1366x768.png'), fullPage: false});
});

test('closing and reopening fences stale AI create hydration and remains usable on mobile', async ({page}, testInfo) => {
  await page.setViewportSize({width: 390, height: 844});
  await installDelayedCreationApis(page);
  await ready(page);
  await page.evaluate(() => window.createAiLabel429());
  const first = await page.locator('.ai-create-workbench').getAttribute('data-ai-create-epoch');
  await page.getByRole('button', {name: '取消'}).click();
  await page.evaluate(() => window.createAiLabel429());
  const second = await page.locator('.ai-create-workbench').getAttribute('data-ai-create-epoch');
  expect(Number(second)).toBeGreaterThan(Number(first));
  await expect(page.locator('#ai429Models')).toContainText('场景视觉模型', {timeout: 5000});
  await expect(page.locator('.ai-create-workbench')).toHaveAttribute('data-ai-create-epoch', second);
  await expect(page.locator('#ai429Submit')).toBeVisible();
  await page.screenshot({path: testInfo.outputPath('ai-create-mobile-390x844.png'), fullPage: false});
});

test('AI create keeps the form on configuration or submit failure and fences duplicate submit', async ({page}) => {
  let modelReads = 0;
  let submitCount = 0;
  await page.route('**/api/v35/model-configs', async route => {
    modelReads += 1;
    if (modelReads === 1) {
      await route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({message: '模型配置暂不可用'})});
      return;
    }
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(models)});
  });
  await page.route('**/api/v35/prompt-templates', route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(templates)}));
  await page.route('**/api/v12/projects/*/labels', route => route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(labels)}));
  await page.route('**/api/v61/projects/*/materials**', route => route.fulfill({
    status: 200, contentType: 'application/json', body: JSON.stringify({
      items: [{id: 'retry-image', filename: 'retry.jpg', url: PIXEL, width: 640, height: 480, annotated: false}],
      total: 1, page: 1, page_size: 12, total_pages: 1,
    }),
  }));
  await page.route('**/api/v60/projects/*/annotation-tasks', async route => {
    if (route.request().method() !== 'POST') return route.continue();
    submitCount += 1;
    await new Promise(resolve => setTimeout(resolve, 250));
    await route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({message: '模型连接失败'})});
  });

  await ready(page);
  await page.evaluate(() => window.createAiLabel429());
  await expect(page.locator('#ai429Hydration')).toContainText('部分配置读取失败');
  await page.locator('#ai429Hydration').getByRole('button', {name: '重试'}).click();
  await expect(page.locator('#ai429Models')).toContainText('场景视觉模型');
  await page.getByRole('button', {name: /明火/}).click();
  // Creation no longer implicitly selects an entire material page. The user
  // must explicitly choose the image before submitting the task.
  await expect(page.locator('#ai429MaterialGrid button')).toHaveCount(1);
  await page.locator('#ai429MaterialGrid button').first().click();
  await expect(page.locator('#ai429MaterialCount')).toContainText('已选 1 张');
  await page.locator('#ai429Prompt').fill('保留本次输入 {{labels_json}} {{output_schema}}');
  await page.locator('#ai429Submit').click();
  await page.evaluate(() => window.submitAiLabel429());
  await expect.poll(() => submitCount).toBe(1);
  await expect(page.getByRole('dialog', {name: '创建AI自动标注任务'})).toBeVisible();
  await expect(page.locator('#ai429Prompt')).toHaveValue('保留本次输入 {{labels_json}} {{output_schema}}');
  await expect(page.locator('#ai429Labels')).toHaveValue('fire');
  await expect(page.locator('#ai429Submit')).toBeEnabled();
});

test('AI create resolves all filtered pages atomically, preserves earlier choices, and rejects stale revisions', async ({page}, testInfo) => {
  await installDelayedCreationApis(page, {materialDelayMs: 30});
  const calls=[];
  await page.route('**/api/v61/projects/*/materials/ids**', route => {
    const url=new URL(route.request().url()),query=url.searchParams.get('query')||'';
    calls.push({query,revision:url.searchParams.get('expected_revision'),narrow:url.searchParams.get('narrow')});
    if(query==='conflict')return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'素材库已更新，请重试'})});
    const rows=query==='alpha'?Array.from({length:100},(_,i)=>`a-${i}`):
      Array.from({length:50},(_,i)=>i<20?`a-${i}`:`b-${i}`);
    const pageNumber=Number(url.searchParams.get('cursor')||'0'),size=Math.ceil(rows.length/5);
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      repository_revision:7,total:pageNumber===0?rows.length:-1,
      items:rows.slice(pageNumber*size,(pageNumber+1)*size),
      next_cursor:pageNumber<4?String(pageNumber+1):null,
    })});
  });
  await ready(page);
  await page.evaluate(()=>window.createAiLabel429());
  const search=page.locator('#ai429MaterialQ');
  await search.fill('alpha');
  await expect.poll(()=>page.evaluate(()=>state.ai429Create?.query==='alpha'&&!state.ai429Create.materialLoading)).toBe(true);
  await page.getByRole('button',{name:'全选当前筛选结果'}).click();
  await expect(page.locator('#ai429MaterialCount')).toContainText('已选 100 张');
  await search.fill('beta');
  await expect.poll(()=>page.evaluate(()=>state.ai429Create?.query==='beta'&&!state.ai429Create.materialLoading)).toBe(true);
  await page.getByRole('button',{name:'全选当前筛选结果'}).click();
  await expect(page.locator('#ai429MaterialCount')).toContainText('已选 130 张');
  expect(calls.filter(call=>call.query==='alpha')).toHaveLength(5);
  expect(calls.filter(call=>call.query==='beta')).toHaveLength(5);
  expect(calls.every(call=>call.narrow==='true')).toBe(true);
  expect(calls.filter(call=>call.revision!==null).every(call=>call.revision==='7')).toBe(true);
  await search.fill('conflict');
  await expect.poll(()=>page.evaluate(()=>state.ai429Create?.query==='conflict'&&!state.ai429Create.materialLoading)).toBe(true);
  await page.getByRole('button',{name:'全选当前筛选结果'}).click();
  await expect(page.locator('#ai429BulkFeedback')).toContainText('素材库已更新');
  await expect(page.locator('#ai429MaterialCount')).toContainText('已选 130 张');
  for(const viewport of [{width:1920,height:1080},{width:1440,height:900},{width:1366,height:768}]){
    await page.setViewportSize(viewport);
    await page.screenshot({path:testInfo.outputPath(`ai-create-filtered-${viewport.width}x${viewport.height}.png`),fullPage:false});
  }
});

test('AI candidate editor stays inside the review workspace without opening a nested dialog', async ({page}, testInfo) => {
  await ready(page);
  await page.route('**/api/v60/projects/*/annotation-tasks/ai-ux-fixture/candidates**', route=>route.fulfill({
    status:200,contentType:'application/json',body:JSON.stringify({
      total:2,items:[{image_id:'one',filename:'scene-one.png',url:PIXEL,width:1,height:1,status:'completed',boxes:[]},
        {image_id:'two',filename:'scene-two.png',url:PIXEL,width:1,height:1,status:'completed',boxes:[]}],label_summary:[],
    }),
  }));
  await page.evaluate(()=>window.reviewAiLabel427('ai-ux-fixture'));
  const before=await page.locator('.v424-modal-layer').count();
  await page.getByRole('button',{name:'编辑候选框'}).first().click();
  await expect(page.locator('.ai66-review.ai66-editing .ai66-edit')).toBeVisible();
  expect(await page.locator('.v424-modal-layer').count()).toBe(before);
  await expect(page.locator('#ai66EditQueue')).toContainText('scene-two.png');
  await page.locator('.ai66-edit-queue-item').nth(1).click();
  await expect(page.locator('#ai66EditFilename')).toContainText('scene-two.png');
  for(const viewport of [{width:1920,height:1080},{width:1440,height:900},{width:1366,height:768}]){
    await page.setViewportSize(viewport);
    await page.screenshot({path:testInfo.outputPath(`ai-inline-review-${viewport.width}x${viewport.height}.png`),fullPage:false});
  }
  await page.getByRole('button',{name:'返回列表'}).click();
  await expect(page.locator('.ai66-review.ai66-editing')).toHaveCount(0);
  await expect(page.locator('.ai66-review-grid')).toBeVisible();
  for(const viewport of [{width:1920,height:1080},{width:1440,height:900},{width:1366,height:768}]){
    await page.setViewportSize(viewport);
    await page.screenshot({path:testInfo.outputPath(`ai-review-${viewport.width}x${viewport.height}.png`),fullPage:false});
  }
});

test('AI task list pages on the server and keeps search/status scoped to the visible page', async ({page}) => {
  const requests=[];
  await page.route('**/api/v60/projects/*/annotation-tasks?**', route=>{
    const url=new URL(route.request().url()),second=url.searchParams.get('cursor')==='cursor-two';
    requests.push(url.searchParams.get('cursor')||'first');
    const item={id:second?'task-beta':'task-alpha',name:second?'Beta 标注':'Alpha 标注',status:second?'SUCCEEDED':'QUEUED',
      created_at:'2026-10-30T01:00:00Z',total_count:30,completed_count:second?30:0,model_config_name:'视觉模型',progress:second?100:0};
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:[item],next_cursor:second?null:'cursor-two'})});
  });
  await ready(page);
  await page.evaluate(()=>{state.page='自动标注及清洗';state.v427OpsTab='label';window.renderOps427()});
  await expect(page.locator('#ai60TaskRows')).toContainText('Alpha 标注');
  await page.locator('#ai60TaskSearch').fill('missing');
  await expect(page.locator('#ai60TaskRows')).toContainText('没有匹配');
  await page.locator('#ai60TaskSearch').fill('');
  await page.locator('#ai60TaskPager').getByRole('button',{name:'下一页'}).click();
  await expect(page.locator('#ai60TaskRows')).toContainText('Beta 标注');
  expect(requests).toContain('cursor-two');
  await page.locator('#ai60TaskStatus').selectOption('QUEUED');
  await expect(page.locator('#ai60TaskRows')).toContainText('没有匹配');
  await page.locator('#ai60TaskStatus').selectOption('');
  await expect(page.locator('#ai60TaskRows')).toContainText('Beta 标注');
});

test('AI candidate page opens immediately and offers retry instead of indefinite skeleton', async ({page}) => {
  await ready(page);
  let reads=0;
  await page.route('**/api/v60/projects/*/annotation-tasks/ai-retry-fixture/candidates**', route=>{
    reads++;
    return route.fulfill({status:reads===1?503:200,contentType:'application/json',body:reads===1?
      JSON.stringify({detail:'暂时无法读取候选结果'}):JSON.stringify({items:[],total:0,label_summary:[]})});
  });
  await page.evaluate(()=>{void window.reviewAiLabel427('ai-retry-fixture')});
  await expect(page.locator('.ai66-review')).toBeVisible();
  await expect(page.locator('.ai66-review-grid')).toContainText('暂时无法读取候选结果');
  await page.locator('.ai66-review-grid').getByRole('button',{name:'重试'}).click();
  await expect(page.locator('.ai66-review-grid')).toContainText('没有候选图片');
  await expect(page.locator('.ai66-review-grid .ai-create-loading')).toHaveCount(0);
  expect(reads).toBe(2);
});
