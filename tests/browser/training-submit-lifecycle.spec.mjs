import {test, expect} from '@playwright/test';

// Exercise the production submit owner against real DOM nodes and an isolated API
// ledger. The full-app training-label-selector suite covers the canonical Modal stack.
const taskId='train_aaaaaaaaaaaaaaaaaaaa';
async function mount(page, mode) {
  const ledger=new Map();
  let posts=0;
  await page.route('**/__training_submit_fixture',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><head><link rel="stylesheet" href="/static/styles.css"><style>.hidden{display:none}</style></head><body><div id="fixture"></div></body></html>'}));
  await page.route('**/api/v12/projects/fixture-project/train/start',async route=>{
    posts++;
    const payload=route.request().postDataJSON();
    const task={task_id:payload.task_id,kind:'TRAINING',task_type:'TRAINING',status:'QUEUED',project_id:'fixture-project',algorithm_id:'alg-1'};
    if(mode.startsWith('http-'))return route.fulfill({status:Number(mode.slice(5)),json:{code:'TRAIN_TEST_REJECTED',message:'isolated rejection'}});
    if(mode==='bad-json'){ledger.set(task.task_id,task);return route.fulfill({contentType:'application/json',body:'{broken'});}
    if(mode==='reject') return route.fulfill({status:409,json:{message:'GT 核验失败'}});
    if(!['unknown','pending-unknown'].includes(mode)) ledger.set(task.task_id,task);
    if(['recover','unknown','verify-pending'].includes(mode)) return route.abort('failed');
    if(mode.startsWith('pending-')) return;
    await expect.poll(()=>page.evaluate(()=>window.releasePost)).toBeTruthy();
    return route.fulfill({json:{ok:true,task}});
  });
  await page.route('**/api/v62/projects/fixture-project/tasks/*',route=>{
    if(mode==='verify-pending')return;
    const task=ledger.get(decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)));
    return route.fulfill({status:task?200:404,json:task?{task}:{detail:'not found'}});
  });
  await page.goto('/__training_submit_fixture');
  await page.evaluate(async ({mode,taskId})=>{
    const {installTrainingSubmitRuntime}=await import('/static/modules/training-submit.js');
    const {createTrainingDraft,trainingDraftToRequest}=await import('/static/modules/training-draft.js');
    window.openFixture=()=>{
      document.querySelector('#fixture').innerHTML=`<div id="modal" role="dialog"><div class="train429-create"><input id="tr429TaskId" value="${taskId}"><select id="tr429Target"><option value="local">local</option></select><select id="tr429Alg"><option value="detect">detect</option></select><div class="train-submit-feedback" data-training-submit-feedback hidden><div class="train-submit-visual"><i></i></div><b data-training-submit-title></b><span data-training-submit-detail></span><ol><li data-training-submit-step></li></ol></div><div class="train428-footer"><button class="btn primary">开始训练</button></div></div></div>`;
    };
    window.openFixture();window.releasePost=false;window.closeCalls=0;window.accepted=[];window.notices=[];window.refreshStarted=false;window.refreshFinished=false;
    const draft=createTrainingDraft({algorithmId:'alg-1',materialIds:['m1','m2'],newLabelCodes:['person'],resource:{strategy:'manual',device:'cpu'},config:{model:'yolo11n.pt'}});
    const state={algorithms:[{id:'alg-1'}],targets:[{id:'local',type:'local',framework:'ultralytics',algorithms:[{key:'detect',base_model:'yolo11n.pt'}]}],trainingDevicesV3:{options:[{id:'cpu',available:true}]}};
    window.fixtureState=state;window.failReadiness=false;window.submitRuntime=installTrainingSubmitRuntime({getState:()=>{if(window.failReadiness)throw new Error('isolated readiness failure');return state;},projectId:()=> 'fixture-project',trainingDraftRuntime:{sync:()=>draft,current:()=>draft,base:()=>({blocked:false})},trainingDraftToRequest,
      closeModal:()=>{window.closeCalls++;document.getElementById('modal').classList.add('hidden');},
      trainingTaskRuntime:{acceptCreatedTask:task=>window.accepted.push(task)},notify:text=>window.notices.push(text),
      reloadRelated:async()=>{window.refreshStarted=true;if(mode==='refresh-error')throw new Error('isolated refresh unavailable');await new Promise(resolve=>{window.finishRefresh=resolve;});window.refreshFinished=true;},
    });
    document.querySelector('button').onclick=()=>{window.submitPromise=window.submitRuntime.submit();};
  },{mode,taskId});
  return {ledger,posts:()=>posts,setMode:value=>{mode=value;}};
}

for(const mode of ['slow-refresh','refresh-error','reject','manual-close','replacement','recover','unknown','pending-recover','pending-unknown']) {
  test(`training creation modal identity and durable outcome: ${mode}`,async({page})=>{
    const fixture=await mount(page,mode);
    if(mode.startsWith('pending-')) await page.clock.install();
    await page.getByRole('button',{name:'开始训练'}).click();
    if(mode.startsWith('pending-')) {
      await expect.poll(()=>fixture.posts()).toBe(1);
      await page.clock.fastForward(30001);
    } else if(!['recover','unknown','reject'].includes(mode)) {
      await expect(page.getByRole('button',{name:'正在创建训练任务…'})).toBeDisabled();
      await expect(page.getByRole('button',{name:'正在创建训练任务…'})).toHaveAttribute('aria-busy','true');
      // Repeated calls while pending must not produce another POST.
      await page.evaluate(()=>window.submitRuntime.submit());
      if(mode==='manual-close')await page.evaluate(()=>document.getElementById('modal').classList.add('hidden'));
      if(mode==='replacement')await page.evaluate(()=>window.openFixture());
      await page.evaluate(()=>{window.releasePost=true;});
    }
    await page.evaluate(()=>window.submitPromise);
    expect(fixture.posts()).toBe(1);
    if(['reject','unknown','pending-unknown'].includes(mode)) {
      await expect(page.getByRole('dialog')).toBeVisible();
      expect(await page.evaluate(()=>window.closeCalls)).toBe(0);
      expect(fixture.ledger.size).toBe(0);
      if(['unknown','pending-unknown'].includes(mode)) {
        await page.evaluate(()=>window.submitRuntime.submit());
        expect(fixture.posts()).toBe(1);
        expect(await page.evaluate(()=>window.notices.join(' '))).toContain('不要重复创建');
      }
    } else {
      expect(fixture.ledger.get(taskId)?.status).toBe('QUEUED');
      expect(await page.evaluate(()=>window.accepted[0]?.task_id)).toBe(taskId);
      if(mode==='replacement') {
        await expect(page.getByRole('dialog')).toBeVisible();
        expect(await page.evaluate(()=>window.closeCalls)).toBe(0);
      } else {
        await expect(page.getByRole('dialog')).not.toBeVisible();
        expect(await page.evaluate(()=>window.closeCalls)).toBe(mode==='manual-close'?0:1);
      }
      expect(await page.evaluate(()=>window.refreshFinished)).toBe(false);
      if(mode==='refresh-error')await expect.poll(()=>page.evaluate(()=>window.notices.join(' '))).toContain('列表刷新失败');
      // A new modal opened after success must survive all background work.
      await page.evaluate(()=>{window.openFixture();window.finishRefresh?.();});
      await expect(page.getByRole('dialog')).toBeVisible();
      expect(await page.evaluate(()=>window.closeCalls)).toBe(['replacement','manual-close'].includes(mode)?0:1);
    }
    await page.evaluate(()=>window.submitRuntime.destroy());
  });
}

for (const fault of ['initial-render', 'finally-render']) {
  test(`training submit recovers actual DOM after ${fault} exception`, async ({page}) => {
    const errors=[];page.on('pageerror',error=>errors.push(error.message));
    const fixture=await mount(page,'reject');
    await page.evaluate(fault=>{
      if(fault==='initial-render')window.failReadiness=true;
      else {
        const fetch=window.fetch;
        window.fetch=async(...args)=>{const result=await fetch(...args);window.failReadiness=true;return result;};
      }
    },fault);
    await page.getByRole('button',{name:'开始训练'}).click();
    await expect.poll(()=>page.evaluate(()=>window.submitRuntime.isSubmitting())).toBe(false);
    const button=page.locator('.train428-footer .btn.primary');
    await expect(button).toBeEnabled();
    await expect(button).toHaveAttribute('aria-busy','false');
    expect(await page.evaluate(()=>window.notices.join(' '))).toContain(fault==='initial-render'?'failure':'GT 核验失败');
    expect(errors).toEqual([]);
    expect(fixture.posts()).toBe(fault==='initial-render'?0:1);
  });
}

for(const status of [400,409,422,500]){
  test(`HTTP ${status} stops spinner and preserves config without duplicate POST`,async({page})=>{
    const fixture=await mount(page,`http-${status}`);
    await page.getByRole('button',{name:'开始训练'}).click();
    await page.evaluate(()=>window.submitPromise);
    await expect(page.locator('.train428-footer .btn.primary')).toHaveAttribute('aria-busy','false');
    await expect(page.locator('[data-training-submit-feedback]')).toHaveAttribute('aria-busy','false');
    await expect(page.locator('[data-training-submit-detail]')).toContainText('isolated rejection');
    expect(await page.locator('#tr429TaskId').inputValue()).toBe(taskId);
    expect(fixture.posts()).toBe(1);
    if(status<500)await expect(page.locator('.train428-footer .btn.primary')).toBeEnabled();
    else await expect(page.locator('[data-training-query-result]')).toBeVisible();
  });
}

test('unknown result exposes stable manual query and recovers original durable task without another POST',async({page})=>{
  const fixture=await mount(page,'unknown');
  await page.getByRole('button',{name:'开始训练'}).click();await page.evaluate(()=>window.submitPromise);
  await expect(page.locator('[data-training-submit-title]')).toHaveText('创建结果暂未确认');
  await expect(page.locator('.training-submit-active')).toHaveCount(0);
  fixture.ledger.set(taskId,{task_id:taskId,kind:'TRAINING',status:'QUEUED',project_id:'fixture-project',algorithm_id:'alg-1'});
  await page.getByRole('button',{name:'查询任务状态'}).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();expect(fixture.posts()).toBe(1);
});

test('successful creation with malformed response JSON verifies persisted identity',async({page})=>{
  const fixture=await mount(page,'bad-json');
  await page.getByRole('button',{name:'开始训练'}).click();await page.evaluate(()=>window.submitPromise);
  await expect(page.getByRole('dialog')).not.toBeVisible();expect(fixture.posts()).toBe(1);
});


test('verification timeout becomes a stable unknown state with query action',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const fixture=await mount(page,'verify-pending');await page.clock.install();
  await page.getByRole('button',{name:'开始训练'}).click();
  await expect(page.locator('[data-training-submit-title]')).toHaveText('正在确认创建结果');
  await page.clock.fastForward(30001);await page.evaluate(()=>window.submitPromise);
  await expect(page.locator('[data-training-submit-title]')).toHaveText('创建结果暂未确认');
  await expect(page.locator('[data-training-submit-feedback]')).toHaveAttribute('aria-busy','false');
  await expect(page.getByRole('button',{name:'查询任务状态'})).toBeVisible();
  expect(fixture.posts()).toBe(1);expect(errors).toEqual([]);
});

for(const failure of ['http','timeout']){
  test(`first-open preparation ${failure} stops loading and retry opens real form`,async({page})=>{
    await mount(page,'reject');
    await page.clock.install();
    await page.evaluate(async failure=>{
      const {installTrainingCreateHydrationRuntime}=await import('/static/modules/training-create-hydration.js');
      window.preparationFail=true;window.realFormOpened=0;
      window.modal=(title,body)=>{document.getElementById('fixture').innerHTML=body;};
      window.closeModal=()=>{document.getElementById('fixture').innerHTML='';};
      const state={targets:[],rec:null};
      window.hydration=installTrainingCreateHydrationRuntime({getState:()=>state,projectId:()=> 'p',openTrainingForm:()=>{window.realFormOpened++;},
        request:async url=>{
          if(window.preparationFail){if(failure==='timeout')return new Promise(()=>{});throw new Error('HTTP 500');}
          return url.includes('training_options')?{targets:[{id:'cpu',status:'ready',algorithms:[{key:'detect'}],base_models:[]}]}:{device:'cpu'};
        }});
      window.preparationPromise=window.hydration.start('a');
    },failure);
    if(failure==='timeout')await page.clock.fastForward(30001);
    await page.evaluate(()=>window.preparationPromise);
    await expect(page.locator('[data-training-create-shell]')).toHaveAttribute('aria-busy','false');
    await expect(page.locator('[data-training-create-status]')).toContainText(failure==='timeout'?'超时':'HTTP 500');
    await expect(page.getByRole('button',{name:'重试',exact:true})).toBeEnabled();
    await page.evaluate(()=>{window.preparationFail=false;});
    await page.getByRole('button',{name:'重试',exact:true}).click();
    await expect.poll(()=>page.evaluate(()=>window.realFormOpened)).toBe(1);
  });
}


test('explicit rejection preserves config and a corrected retry creates one durable task',async({page})=>{
  const fixture=await mount(page,'http-422');
  await page.getByRole('button',{name:'开始训练'}).click();await page.evaluate(()=>window.submitPromise);
  await expect(page.locator('[data-training-submit-step][data-status="active"]')).toHaveCount(0);
  fixture.setMode('slow-refresh');await page.evaluate(()=>{window.releasePost=true;});
  await page.locator('.train428-footer .btn.primary').click();await page.evaluate(()=>window.submitPromise);
  await expect(page.getByRole('dialog')).not.toBeVisible();expect(fixture.posts()).toBe(2);expect(fixture.ledger.size).toBe(1);
});

test('completion callback failure cannot turn persisted creation into failure or leave loading',async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const fixture=await mount(page,'slow-refresh');
  await page.evaluate(()=>{window.accepted.push=()=>{throw new Error('isolated completion callback');};window.releasePost=true;});
  await page.getByRole('button',{name:'开始训练'}).click();await page.evaluate(()=>window.submitPromise);
  await expect(page.getByRole('dialog')).not.toBeVisible();
  expect(await page.evaluate(()=>window.submitRuntime.isSubmitting())).toBe(false);
  expect(fixture.ledger.size).toBe(1);expect(fixture.posts()).toBe(1);expect(errors).toEqual([]);
});


test('unknown creation cannot be bypassed by reopening with a new task ID',async({page})=>{
  const fixture=await mount(page,'unknown');await page.getByRole('button',{name:'开始训练'}).click();await page.evaluate(()=>window.submitPromise);
  await page.evaluate(()=>{window.openFixture();document.getElementById('tr429TaskId').value='train_bbbbbbbbbbbbbbbbbbbb';window.submitRuntime.updateReadiness();});
  await page.evaluate(()=>window.submitRuntime.submit());
  expect(fixture.posts()).toBe(1);expect(await page.evaluate(()=>window.notices.at(-1))).toContain(taskId);
  await expect(page.locator('.train428-footer .btn.primary')).toHaveAttribute('aria-busy','false');
});


test('manual query failure shows its actual reason and stays query-only',async({page})=>{
  const fixture=await mount(page,'unknown');await page.getByRole('button',{name:'开始训练'}).click();await page.evaluate(()=>window.submitPromise);
  await page.getByRole('button',{name:'查询任务状态'}).click();
  await expect(page.locator('[data-training-submit-detail]')).toContainText('HTTP 404');
  await expect(page.locator('[data-training-submit-feedback]')).toHaveAttribute('aria-busy','false');
  expect(fixture.posts()).toBe(1);
});
