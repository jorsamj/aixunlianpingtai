import {test, expect} from '@playwright/test';

// Exercise the production submit owner against real DOM nodes and an isolated API
// ledger. The full-app training-label-selector suite covers the canonical Modal stack.
const taskId='train_aaaaaaaaaaaaaaaaaaaa';
async function mount(page, mode) {
  const ledger=new Map();
  let posts=0;
  await page.route('**/__training_submit_fixture',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><html><head><style>.hidden{display:none}</style></head><body><div id="fixture"></div></body></html>'}));
  await page.route('**/api/v12/projects/fixture-project/train/start',async route=>{
    posts++;
    const payload=route.request().postDataJSON();
    const task={task_id:payload.task_id,kind:'TRAINING',task_type:'TRAINING',status:'QUEUED',project_id:'fixture-project',algorithm_id:'alg-1'};
    if(mode==='reject') return route.fulfill({status:409,json:{message:'GT 核验失败'}});
    if(mode!=='unknown') ledger.set(task.task_id,task);
    if(['recover','unknown'].includes(mode)) return route.abort('failed');
    await expect.poll(()=>page.evaluate(()=>window.releasePost)).toBeTruthy();
    return route.fulfill({json:{ok:true,task}});
  });
  await page.route('**/api/v62/projects/fixture-project/tasks/*',route=>{
    const task=ledger.get(decodeURIComponent(new URL(route.request().url()).pathname.split('/').at(-1)));
    return route.fulfill({status:task?200:404,json:task?{task}:{detail:'not found'}});
  });
  await page.goto('/__training_submit_fixture');
  await page.evaluate(async ({mode,taskId})=>{
    const {installTrainingSubmitRuntime}=await import('/static/modules/training-submit.js');
    const {createTrainingDraft,trainingDraftToRequest}=await import('/static/modules/training-draft.js');
    window.openFixture=()=>{
      document.querySelector('#fixture').innerHTML=`<div id="modal" role="dialog"><div class="train429-create"><input id="tr429TaskId" value="${taskId}"><select id="tr429Target"><option value="local">local</option></select><select id="tr429Alg"><option value="detect">detect</option></select><div class="train428-footer"><button class="btn primary">创建训练任务</button></div></div></div>`;
    };
    window.openFixture();window.releasePost=false;window.closeCalls=0;window.accepted=[];window.notices=[];window.refreshStarted=false;window.refreshFinished=false;
    const draft=createTrainingDraft({algorithmId:'alg-1',materialIds:['m1','m2'],newLabelCodes:['person'],resource:{strategy:'manual',device:'cpu'},config:{model:'yolo11n.pt'}});
    const state={algorithms:[{id:'alg-1'}],targets:[{id:'local',type:'local',framework:'ultralytics',algorithms:[{key:'detect',base_model:'yolo11n.pt'}]}],trainingDevicesV3:{options:[{id:'cpu',available:true}]}};
    window.submitRuntime=installTrainingSubmitRuntime({getState:()=>state,projectId:()=> 'fixture-project',trainingDraftRuntime:{sync:()=>draft,current:()=>draft,base:()=>({blocked:false})},trainingDraftToRequest,
      closeModal:()=>{window.closeCalls++;document.getElementById('modal').classList.add('hidden');},
      trainingTaskRuntime:{acceptCreatedTask:task=>window.accepted.push(task)},notify:text=>window.notices.push(text),
      reloadRelated:async()=>{window.refreshStarted=true;if(mode==='refresh-error')throw new Error('isolated refresh unavailable');await new Promise(resolve=>{window.finishRefresh=resolve;});window.refreshFinished=true;},
    });
    document.querySelector('button').onclick=()=>{window.submitPromise=window.submitRuntime.submit();};
  },{mode,taskId});
  return {ledger,posts:()=>posts};
}

for(const mode of ['slow-refresh','refresh-error','reject','manual-close','replacement','recover','unknown']) {
  test(`training creation modal identity and durable outcome: ${mode}`,async({page})=>{
    const fixture=await mount(page,mode);
    await page.getByRole('button',{name:'创建训练任务'}).click();
    if(!['recover','unknown','reject'].includes(mode)) {
      await expect(page.getByRole('button',{name:'正在提交训练任务…'})).toBeDisabled();
      await expect(page.getByRole('button',{name:'正在提交训练任务…'})).toHaveAttribute('aria-busy','true');
      // Repeated calls while pending must not produce another POST.
      await page.evaluate(()=>window.submitRuntime.submit());
      if(mode==='manual-close')await page.evaluate(()=>document.getElementById('modal').classList.add('hidden'));
      if(mode==='replacement')await page.evaluate(()=>window.openFixture());
      await page.evaluate(()=>{window.releasePost=true;});
    }
    await page.evaluate(()=>window.submitPromise);
    expect(fixture.posts()).toBe(1);
    if(mode==='reject'||mode==='unknown') {
      await expect(page.getByRole('dialog')).toBeVisible();
      expect(await page.evaluate(()=>window.closeCalls)).toBe(0);
      expect(fixture.ledger.size).toBe(0);
      if(mode==='unknown') {
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
