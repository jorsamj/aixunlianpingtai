import {expect,test} from '@playwright/test';
import {resolve} from 'node:path';

test('清洗剔除先登记原删除计划，其余清洗确认只传排除项',async({page})=>{
  const project='clean-project',cleanId='clean-task',plan='delete-plan',image='needs-review';
  const writes=[];
  let deleted=false,confirmed=false;
  const clean=()=>({id:cleanId,name:'清洗隔离任务',status:confirmed?'done':'awaiting_confirmation',progress:100,
    processed_images:2,total_images:2,flagged_images:1});
  const deletion={id:plan,task_id:plan,project_id:project,operation:'DELETE_INDEX',status:'QUEUED',total:1};
  await page.route('**/app/**',route=>{
    const path=new URL(route.request().url()).pathname.slice('/app/'.length)||'index.html';
    return route.fulfill({path:resolve('../static/vue-app',path),
      contentType:path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('**/api/auth/session',route=>route.fulfill({json:{authenticated:true,provider:'local',user:{username:'reviewer'}}}));
  await page.route('**/api/projects',route=>route.fulfill({json:[{id:project,name:'测试项目'}]}));
  await page.route(`**/api/v47/projects/${project}/clean-tasks**`,route=>{
    const path=new URL(route.request().url()).pathname;
    if(path.endsWith('/result'))return route.fulfill({json:{task:clean(),result:{items:[
      {image_id:image,filename:'复核照片.jpg',status:'success',suggest_delete:true,issues:[{code:'quality',name:'质量异常'}]},
      {image_id:'kept',filename:'保留照片.jpg',status:'success',issues:[]}]}}});
    if(path.endsWith('/confirm')){
      expect(deleted).toBe(true);
      writes.push(['clean',route.request().postDataJSON()]);
      confirmed=true;
      return route.fulfill({json:{ok:true,processed_ids:['kept']}});
    }
    return route.fulfill({json:{items:[clean()]}});
  });
  await page.route(`**/api/v62/projects/${project}/material-batches**`,route=>{
    const path=new URL(route.request().url()).pathname;
    if(path.endsWith('/estimate')){
      writes.push(['preview',route.request().postDataJSON()]);
      return route.fulfill({json:{supported:true,count:1,selection_spec:{scope:'SELECTED',image_ids:[image],repository_revision:3},
        deletion_preview:{plan_id:plan,confirmation_credential:'fixture',gt_count:0,current_test_count:0,
          historical_reference_count:0,active_reference_count:0}}});
    }
    if(route.request().method()==='POST'){
      writes.push(['delete',route.request().postDataJSON()]);deleted=true;
      return route.fulfill({status:202,json:deletion});
    }
    return route.fulfill({json:deletion});
  });
  await page.goto(`/app/#/projects/${project}/ai/cleaning?task_id=${cleanId}`);
  await page.getByRole('button',{name:'预检删除已选 1 张'}).click();
  const dialog=page.getByRole('dialog',{name:'清洗素材删除'});
  await expect(dialog).toContainText('保留原图字节');
  expect(writes.map(([step])=>step)).toEqual(['preview']);
  await dialog.getByRole('button',{name:'确认删除',exact:true}).click();
  await expect(dialog).toContainText(plan);
  await dialog.getByRole('button',{name:'关闭',exact:true}).last().click();
  await page.getByRole('button',{name:'核对删除任务并确认其余素材'}).click();
  await expect(page.getByText(/已确认其余 1 张/)).toBeVisible();
  expect(writes).toEqual([
    ['preview',{operation:'DELETE_INDEX',selection_spec:{scope:'SELECTED',image_ids:[image]},options:{}}],
    ['delete',{operation:'DELETE_INDEX',selection_spec:{scope:'SELECTED',image_ids:[image],repository_revision:3},
      options:{deletion_plan_id:plan,confirmation_credential:'fixture'}}],
    ['clean',{delete_ids:[],skip_image_ids:[image]}],
  ]);
});
