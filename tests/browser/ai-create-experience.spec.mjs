import {test, expect} from '@playwright/test';

const PIXEL = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
// Deterministic 640×480 scene fixtures for browser *visual* QA only. The
// single-pixel API fixture exercises requests, but cannot validate image
// placement, candidate overlays, or the Annotorious fit/zoom experience.
function reviewVisualScene(offset=0){
  const source=`<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">
    <defs><linearGradient id="wall" x2="0" y2="1"><stop stop-color="#cbd5df"/><stop offset="1" stop-color="#899ba9"/></linearGradient><linearGradient id="floor" x2="0" y2="1"><stop stop-color="#677987"/><stop offset="1" stop-color="#394956"/></linearGradient></defs>
    <rect width="640" height="480" fill="url(#wall)"/><path d="M0 270L640 240V480H0Z" fill="url(#floor)"/>
    <path d="M0 272L640 241M40 480L250 266M610 480L425 249" stroke="#e7ecee" stroke-width="3" opacity=".55"/>
    <rect x="22" y="64" width="160" height="182" rx="6" fill="#657887" stroke="#e2e9ee" stroke-width="6"/>
    <rect x="33" y="73" width="137" height="127" fill="#a7c4d0"/><path d="M37 167l45-42 35 34 52-49" fill="none" stroke="#c5dce5" stroke-width="8"/>
    <rect x="440" y="104" width="169" height="157" rx="7" fill="#465d72" stroke="#a5b5c0" stroke-width="5"/>
    <rect x="457" y="119" width="51" height="109" rx="3" fill="#9bb4bc"/><rect x="525" y="119" width="65" height="109" rx="3" fill="#889eaa"/>
    <g transform="translate(${offset} 0)"><ellipse cx="305" cy="388" rx="65" ry="16" fill="#2c3947" opacity=".35"/>
      <path d="M282 322l-6 72m50-72 9 72" stroke="#303e4d" stroke-width="20" stroke-linecap="round"/>
      <path d="M271 233h66l14 108h-94Z" fill="#f3a836" stroke="#c5812b" stroke-width="4"/>
      <path d="M269 249l-27 73m103-73 24 70" stroke="#bb8061" stroke-width="15" stroke-linecap="round"/>
      <circle cx="303" cy="206" r="25" fill="#b98567"/><path d="M274 203a29 29 0 0 1 58 0" fill="#f1cc38" stroke="#b18d18" stroke-width="5"/>
    </g><rect x="44" y="362" width="134" height="78" rx="4" fill="#b68954" stroke="#f4d29b" stroke-width="4"/>
    <path d="M44 384h134M110 362v78" stroke="#835e3c" stroke-width="3"/><circle cx="600" cy="38" r="11" fill="#2b455b" stroke="#e9edf0" stroke-width="4"/>
  </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(source)}`;
}
const REVIEW_SCENE_ONE=reviewVisualScene(0),REVIEW_SCENE_TWO=reviewVisualScene(95);
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
  await expect.poll(() => page.evaluate(() => state.ai429Create === null)).toBe(true);
  await page.evaluate(() => window.createAiLabel429());
  const second = await page.locator('.ai-create-workbench').getAttribute('data-ai-create-epoch');
  expect(Number(second)).toBeGreaterThan(Number(first));
  await expect(page.locator('#ai429Models')).toContainText('场景视觉模型', {timeout: 5000});
  await expect(page.locator('.ai-create-workbench')).toHaveAttribute('data-ai-create-epoch', second);
  await expect(page.locator('#ai429Submit')).toBeVisible();
  await page.screenshot({path: testInfo.outputPath('ai-create-mobile-390x844.png'), fullPage: false});
});

test('AI create keeps the form on configuration or submit failure and fences duplicate submit', async ({page}, testInfo) => {
  let modelReads = 0;
  let submitCount = 0;
  const submitRequestIds = [];
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
    submitRequestIds.push(route.request().postDataJSON()?.request_id);
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
  for(const viewport of [{width:1920,height:1080},{width:1440,height:900},{width:1366,height:768}]){
    await page.setViewportSize(viewport);
    await page.screenshot({path:testInfo.outputPath(`ai-create-before-confirmation-${viewport.width}x${viewport.height}.png`),fullPage:false});
  }
  await page.locator('#ai429Submit').click();
  await expect(page.locator('#ai429Confirmation')).toBeVisible();
  await expect(page.locator('#ai429Confirmation')).toContainText('1张素材');
  await expect(page.locator('#ai429Confirmation')).toContainText('场景视觉模型');
  await expect(page.locator('#ai429Confirmation')).toContainText('fire · 明火');
  expect(submitCount).toBe(0);
  await page.locator('.ai-create-advanced').click();
  await page.locator('#ai429Threshold').fill('0.6');
  await expect(page.locator('#ai429Confirmation')).toBeHidden();
  await page.locator('#ai429Submit').click();
  await expect(page.locator('#ai429Confirmation')).toContainText('60%');
  expect(submitCount).toBe(0);
  for(const viewport of [{width:1920,height:1080},{width:1440,height:900},{width:1366,height:768}]){
    await page.setViewportSize(viewport);
    await page.screenshot({path:testInfo.outputPath(`ai-create-confirmation-${viewport.width}x${viewport.height}.png`),fullPage:false});
  }
  await page.locator('#ai429Submit').click();
  await page.evaluate(() => window.submitAiLabel429());
  await expect.poll(() => submitCount).toBe(1);
  await expect(page.getByRole('dialog', {name: '创建AI自动标注任务'})).toBeVisible();
  await expect(page.locator('#ai429Prompt')).toHaveValue('保留本次输入 {{labels_json}} {{output_schema}}');
  await expect(page.locator('#ai429Labels')).toHaveValue('fire');
  await expect(page.locator('#ai429Submit')).toBeEnabled();
  await page.locator('#ai429Submit').click();
  await expect.poll(() => submitCount).toBe(2);
  expect(submitRequestIds[0]).toMatch(/^ai-[0-9a-f]{32}$/);
  expect(submitRequestIds[1]).toBe(submitRequestIds[0]);
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

test('AI creation preview calls the real single-image endpoint without creating a task', async ({page}, testInfo) => {
  await installDelayedCreationApis(page, {materialDelayMs: 20});
  const payloads=[];
  let previewCount=0,created=0;
  await page.route('**/api/v60/projects/*/annotation-preview', async route => {
    payloads.push(route.request().postDataJSON());
    previewCount++;
    return route.fulfill({status:previewCount===2?503:200,contentType:'application/json',body:JSON.stringify(previewCount===2?
      {detail:'暂时无法联系模型'}:{preview_only:true,image:{id:'ai-image-1',filename:'scene-1.jpg',url:PIXEL,width:640,height:480},
        boxes:[{label:'fire',confidence:0.93,x1:80,y1:60,x2:200,y2:220}],latency_ms:145,model:'vision-v1',provider:'local_openai'})});
  });
  await page.route('**/api/v60/projects/*/annotation-tasks', route=>{created++;return route.abort()});
  await ready(page);
  await page.evaluate(()=>window.createAiLabel429());
  await expect(page.locator('#ai429MaterialGrid button')).toHaveCount(6);
  await page.locator('#ai429MaterialGrid button').first().click();
  await page.getByRole('button',{name:/明火/}).click();
  await expect(page.locator('#ai429PreviewImage')).toHaveValue('ai-image-1');
  await page.locator('#ai429InferenceStart').click();
  await expect(page.locator('#ai429InferenceResult')).toContainText('1 个候选框');
  await expect(page.locator('#ai429InferenceResult .data412-box')).toHaveCount(1);
  expect(payloads[0].image_ids).toEqual(['ai-image-1']);
  expect(payloads[0].labels_text).toBe('fire');
  expect(created).toBe(0);
  await page.locator('#ai429Prompt').fill('本轮提示词 {{labels_json}} {{output_schema}}');
  await expect(page.locator('#ai429InferenceResult')).toContainText('配置或素材已变化');
  await page.locator('#ai429InferenceStart').click();
  await expect(page.locator('#ai429InferenceResult')).toContainText('暂时无法联系模型');
  await page.locator('#ai429InferenceResult').getByRole('button',{name:'重试'}).click();
  await expect(page.locator('#ai429InferenceResult')).toContainText('1 个候选框');
  expect(payloads[2].prompt_override).toContain('本轮提示词');
  expect(created).toBe(0);
  for(const viewport of [{width:1920,height:1080},{width:1440,height:900},{width:1366,height:768}]){
    await page.setViewportSize(viewport);
    await page.screenshot({path:testInfo.outputPath(`ai-one-image-preview-${viewport.width}x${viewport.height}.png`),fullPage:false});
  }
});

test('AI candidate editor stays inside the review workspace without opening a nested dialog', async ({page}, testInfo) => {
  await ready(page);
  await page.route('**/api/v60/projects/*/annotation-tasks/ai-ux-fixture/candidates**', route=>route.fulfill({
    status:200,contentType:'application/json',body:JSON.stringify({
      total:2,items:[{image_id:'one',filename:'scene-one.png',url:REVIEW_SCENE_ONE,width:640,height:480,status:'completed',boxes:[{id:'seed-one',label:'fire',x1:243,y1:175,x2:360,y2:408,confidence:0.94}]},
        {image_id:'two',filename:'scene-two.png',url:REVIEW_SCENE_TWO,width:640,height:480,status:'completed',boxes:[{id:'seed-two',label:'fire',x1:330,y1:175,x2:453,y2:408,confidence:0.88}]}],label_summary:[{label:'fire',images:2,boxes:2}],
    }),
  }));
  await page.evaluate(()=>window.reviewAiLabel427('ai-ux-fixture'));
  await expect(page.locator('.ai-review-page-shell')).toBeVisible();
  await expect(page.locator('.ai-review-workbench-modal')).toHaveCount(0);
  await expect(page.locator('.ai66-candidate-card .data412-box')).toHaveCount(2);
  await expect(page.locator('.ai66-candidate-card img').first()).toHaveJSProperty('naturalWidth',640);
  const before=await page.locator('.v424-modal-layer').count();
  await page.getByRole('button',{name:'编辑候选框'}).first().click();
  await expect(page.locator('.ai66-review.ai66-editing .ai66-edit')).toBeVisible();
  expect(await page.locator('.v424-modal-layer').count()).toBe(before);
  await expect(page.locator('#ai66EditQueue')).toContainText('scene-two.png');
  await page.locator('.ai66-edit-queue-item').nth(1).click();
  await expect(page.locator('#ai66EditFilename')).toContainText('scene-two.png');
  await expect(page.locator('#ai60EditImg')).toHaveJSProperty('naturalWidth',640);
  await expect(page.locator('#ai60EditStatus')).toContainText('候选草稿');
  await expect.poll(async()=>Number((await page.locator('#ai60EditZoom').textContent()).replace('%',''))).toBeLessThanOrEqual(200);
  for(const viewport of [{width:1920,height:1080},{width:1440,height:900},{width:1366,height:768}]){
    await page.setViewportSize(viewport);
    await page.screenshot({path:testInfo.outputPath(`ai-inline-review-${viewport.width}x${viewport.height}.png`),fullPage:false});
  }
  await page.getByRole('button',{name:'返回列表'}).click();
  await expect(page.locator('.ai66-review.ai66-editing')).toHaveCount(0);
  await expect(page.locator('.ai66-review-grid')).toBeVisible();
  for(const viewport of [{width:1920,height:1080},{width:1440,height:900},{width:1366,height:768}]){
    await page.setViewportSize(viewport);
    const geometry=await page.locator('.ai-review-page-shell').boundingBox();
    expect(geometry).not.toBeNull();
    expect(geometry.x+geometry.width).toBeLessThanOrEqual(viewport.width+1);
    await page.screenshot({path:testInfo.outputPath(`ai-review-${viewport.width}x${viewport.height}.png`),fullPage:false});
  }
  expect(new URL(page.url()).hash).toBe('#ai-review/ai-ux-fixture');
  await page.goBack();
  await expect(page.locator('.ai-review-page-shell')).toHaveCount(0);
  await page.goForward();
  await expect(page.locator('.ai-review-page-shell')).toBeVisible();
  await page.reload();
  await expect(page.locator('.ai-review-page-shell')).toBeVisible({timeout:20_000});
  await page.locator('.ai-review-page-nav').getByRole('button',{name:'返回任务列表'}).click();
  await expect(page.locator('.ai-review-page-shell')).toHaveCount(0);
  await expect(page.locator('#ai60TaskRows')).toBeVisible();
  expect(new URL(page.url()).hash).toBe('');
});

test('AI review timeout resolves the original operation receipt without a second decision POST', async ({page}) => {
  await ready(page);
  let posts=0,lookups=0;
  const taskId='ai-review-receipt-fixture';
  await page.route(`**/api/v60/projects/*/annotation-tasks/${taskId}/candidates**`, route=>route.fulfill({
    status:200,contentType:'application/json',body:JSON.stringify({
      total:1,items:[{image_id:'one',filename:'one.jpg',url:PIXEL,width:1,height:1,status:'empty',boxes:[]}],label_summary:[],
    }),
  }));
  await page.route(`**/api/v60/projects/*/annotation-tasks/${taskId}/decisions/by-request/*`, route=>{
    lookups++;
    const requestId=new URL(route.request().url()).pathname.split('/').at(-1);
    return route.fulfill({status:lookups===1?202:200,contentType:'application/json',body:JSON.stringify(lookups===1?
      {status:'pending',request_id:requestId}:{status:'completed',request_id:requestId,result:{
        ok:true,task:{id:taskId,status:'SUCCEEDED',accepted:false,total_count:1,completed_count:1},
        review:{accepted:0,rejected:1},applied_images:0,boxes_added:0,
      }}),
    });
  });
  await page.route(`**/api/v60/projects/*/annotation-tasks/${taskId}/decisions`, route=>{
    posts++;
    const body=route.request().postDataJSON();
    expect(body.request_id).toMatch(/^[A-Za-z0-9_-]{12,80}$/);
    return route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'审核提交回执暂时不可用'})});
  });
  await page.evaluate(id=>window.reviewAiLabel427(id),taskId);
  await page.getByRole('button',{name:'全部拒绝'}).click();
  await expect(page.locator('#ai60ReviewReceiptLookup')).toBeVisible();
  expect(posts).toBe(1);
  await page.locator('#ai60ReviewReceiptLookup').click();
  await expect(page.locator('.ai66-review')).toHaveCount(0);
  expect(lookups).toBe(2);
  expect(posts).toBe(1);
});

test('AI task list pages and searches the full durable history before cursor pagination', async ({page}) => {
  const requests=[];
  await page.route('**/api/v60/projects/*/annotation-tasks?**', route=>{
    const url=new URL(route.request().url()),status=url.searchParams.get('status')||'',search=url.searchParams.get('q')||'',second=url.searchParams.get('cursor')==='cursor-two';
    requests.push({cursor:url.searchParams.get('cursor')||'first',status,search});
    const item={id:search?'task-deep-history':second?'task-beta':'task-alpha',name:search?'历史命中任务':second?'Beta 标注':'Alpha 标注',status:second?'SUCCEEDED':'QUEUED',
      created_at:'2026-10-30T01:00:00Z',total_count:30,completed_count:second?30:0,model_config_name:'视觉模型',progress:second?100:0};
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:search==='missing'?[]:[item],next_cursor:second||status||search?null:'cursor-two'})});
  });
  await ready(page);
  await page.evaluate(()=>{state.page='自动标注及清洗';state.v427OpsTab='label';window.renderOps427()});
  await expect(page.locator('#ai60TaskRows')).toContainText('Alpha 标注');
  await page.locator('#ai60TaskSearch').fill('missing');
  await expect(page.locator('#ai60TaskRows')).toContainText('没有匹配结果');
  expect(requests).toContainEqual({cursor:'first',status:'',search:'missing'});
  await page.locator('#ai60TaskSearch').fill('历史关键字');
  await expect(page.locator('#ai60TaskRows')).toContainText('历史命中任务');
  expect(requests).toContainEqual({cursor:'first',status:'',search:'历史关键字'});
  await page.locator('#ai60TaskSearch').fill('');
  await expect(page.locator('#ai60TaskRows')).toContainText('Alpha 标注');
  await page.locator('#ai60TaskPager').getByRole('button',{name:'下一页'}).click();
  await expect(page.locator('#ai60TaskRows')).toContainText('Beta 标注');
  expect(requests).toContainEqual({cursor:'cursor-two',status:'',search:''});
  await page.locator('#ai60TaskStatus').selectOption('QUEUED');
  await expect(page.locator('#ai60TaskRows')).toContainText('Alpha 标注');
  expect(requests).toContainEqual({cursor:'first',status:'QUEUED',search:''});
  await expect(page.locator('#ai60TaskPager')).toContainText('第 1 页');
  await page.locator('#ai60TaskStatus').selectOption('');
  await expect(page.locator('#ai60TaskRows')).toContainText('Alpha 标注');
});

test('AI task search reports legacy indexing then shows only complete server results', async ({page}) => {
  let searchRequests=0;
  await page.route('**/api/v60/projects/*/annotation-tasks?**', route=>{
    const query=new URL(route.request().url()).searchParams.get('q')||'';
    if(query){
      searchRequests++;
      if(searchRequests===1)return route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({indexing:true,indexed:2,total:6,remaining:4,items:[],next_cursor:null})});
      return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:[{
        id:'archived-task',name:'完整历史搜索结果',status:'SUCCEEDED',created_at:'2026-10-30T01:00:00Z',total_count:2,
      }],next_cursor:null})});
    }
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:[],next_cursor:null})});
  });
  await ready(page);
  await page.evaluate(()=>{state.page='自动标注及清洗';state.v427OpsTab='label';window.renderOps427()});
  await page.locator('#ai60TaskSearch').fill('归档');
  await expect(page.locator('#ai60TaskRows')).toContainText('历史任务索引：2 / 6');
  await expect(page.locator('#ai60TaskRows')).toContainText('不显示不完整的搜索结果');
  await expect(page.locator('#ai60TaskRows')).toContainText('完整历史搜索结果',{timeout:5000});
  expect(searchRequests).toBeGreaterThanOrEqual(2);
});

test('rapid AI task status switching discards stale pages and errors', async ({page}) => {
  const paths=[];
  await page.route('**/api/v60/projects/*/annotation-tasks?**', async route=>{
    const status=new URL(route.request().url()).searchParams.get('status')||'';
    paths.push(status);
    if(status==='QUEUED')await new Promise(resolve=>setTimeout(resolve,1200));
    const item={id:`filtered-${status||'all'}`,name:`${status||'ALL'} 任务`,status:status||'RUNNING',created_at:'2026-10-30T01:00:00Z'};
    try{await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:[item],next_cursor:null})})}catch(_aborted){}
  });
  await ready(page);
  await page.evaluate(()=>{state.page='自动标注及清洗';state.v427OpsTab='label';window.renderOps427()});
  await expect(page.locator('#ai60TaskRows')).toContainText('ALL 任务');
  await page.locator('#ai60TaskStatus').selectOption('QUEUED');
  await page.locator('#ai60TaskStatus').selectOption('SUCCEEDED');
  await expect(page.locator('#ai60TaskRows')).toContainText('SUCCEEDED 任务');
  await page.waitForTimeout(1500);
  await expect(page.locator('#ai60TaskRows')).not.toContainText('QUEUED 任务');
  expect(paths).toContain('QUEUED');
  expect(paths).toContain('SUCCEEDED');
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
