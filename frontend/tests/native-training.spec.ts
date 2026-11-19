import {test,expect} from '@playwright/test';
import {resolve} from 'node:path';
for (const frozen of [false, true]) test(frozen ? 'frozen training retries UUIDv4 and restores the reference after refresh' : 'native training creates from cross-page formal materials using canonical defaults and final confirmation',async({page})=>{
 const freezeIds:string[]=[];let summaries=0;
 let posts=0;const paths:string[]=[];const revision={repository_revision:1,annotation_revision:1,usage_revision:1,negative_pool_revision:1,negative_confirmation_revision:1};
 await page.route('**/app/**',route=>{const name=new URL(route.request().url()).pathname.slice(5)||'index.html';return route.fulfill({path:resolve('../static/vue-app',name),contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'text/html'})});
 page.on('request',r=>paths.push(new URL(r.url()).pathname));
 await page.route('**/api/**',async route=>{
  const r=route.request(),url=new URL(r.url()),path=url.pathname,data=r.postDataJSON?.();
  const asset={id:'a',name:'原生训练算法',algorithm_type:'yolo_ultralytics',source_type:'local',versions:[]};
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'测试'}}});
  if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'隔离项目'}]});
  if(path.endsWith('/algorithms'))return route.fulfill({json:{ok:true,project_id:'p',items:[asset],total:1,page:1,page_size:20}});
  if(path.endsWith('/algorithms/a'))return route.fulfill({json:{ok:true,algorithm:asset}});
  if(path.endsWith('/benchmark-reuse'))return route.fulfill({json:{available:false,reason:'首次训练无历史基准'}});
  if(path==='/api/training_options')return route.fulfill({json:{targets:[{id:'cpu',name:'隔离CPU',type:'local',status:'ready',framework:'ultralytics',algorithms:[{key:'yolo_detect',base_model:'yolo11n.pt',default_imgsz:640}],base_models:[{value:'yolo11n.pt',model_status:'FOUND'}]}]}});
  if(path==='/api/v62/training-devices')return route.fulfill({json:{recommended:'auto',options:[{id:'auto',label:'自动',available:true}]}});
  if(path==='/api/system/recommendation')return route.fulfill({json:{device:'cpu',batch:1,workers:0}});
  if(path.endsWith('/revision'))return route.fulfill({json:revision});
  if(path.endsWith('/page')){expect(r.method()).toBe('POST');expect(data.page_size).toBeLessThanOrEqual(50);const id=data.page===1?'one':'two';return route.fulfill({json:{...revision,items:[{id,filename:id+'.jpg',annotation_state:'annotated',box_count:1,selectable:true}],page:data.page,page_size:40,has_next:data.page===1,total:null,total_pages:null}})}
  if(path.endsWith('/selection-reference')){
   expect(data.request_id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
   freezeIds.push(data.request_id);
   if(freezeIds.length===1)return route.fulfill({status:503,json:{detail:'暂时无法冻结'}});
   return route.fulfill({json:{selection_ref:'isolated-ref',count:22015}});
  }
  if(path.endsWith('/selection-membership'))return route.fulfill({json:{items:['one']}});
  if(path.endsWith('/selection-summary')&&frozen){
   summaries++;
   expect(data.train_selection_ref).toBe('isolated-ref');
   expect(data.image_ids||[]).toEqual([]);
   return route.fulfill({json:{...revision,requested_count:22015,matched_count:22015,selection_reference:true,positive_label_codes:['smoke']}});
  }
  if(path.endsWith('/selection-summary'))return route.fulfill({json:{...revision,requested_count:2,matched_count:2,eligible_count:2,positive_label_codes:['smoke'],label_counts:{smoke:2},selection_validation:{...revision,requested_count:2,eligible_count:2,excluded_count:0,unknown_count:0}}});
  if(path.endsWith('/compatibility'))return route.fulfill({json:{compatible:true,issue_count:0,issue_counts:{},material_revision:1,annotation_revision:1}});
  if(path.endsWith('/train/start')){posts++;expect(data.epochs).toBe(150);expect(data.training_mode).toBe('full');expect(data.train_image_ids).toEqual(frozen?[]:['one','two']);if(frozen)expect(data.train_selection_ref).toBe('isolated-ref');expect(data.train_labels).toEqual(['smoke']);expect(data.validation_percent).toBe(20);expect(data.experiment_percent).toBe(20);expect(data.gpu_policy).toBe('exclusive');expect(data.expected_material_revision).toBe(1);return route.fulfill({json:{ok:true,task:{task_id:data.task_id,kind:'TRAINING',task_type:'TRAINING',status:'QUEUED',project_id:'p'}}})}
  throw new Error('Unexpected API '+path);
 });
 await page.goto('/app/#/projects/p/training/create?algorithm=a');await page.getByRole('button',{name:/选择训练素材/}).click();const picker=page.locator('.training-materials');if(frozen){
  const freeze=picker.getByRole('button',{name:'冻结全部筛选结果',exact:true});
  await freeze.click();await expect(picker).toContainText('暂时无法冻结');await freeze.click();
  await expect(picker).toContainText('服务器冻结 22015 张');expect(freezeIds).toHaveLength(2);expect(freezeIds[0]).toBe(freezeIds[1]);
  await picker.getByRole('button',{name:'读取正式标签并核验选择',exact:true}).click();
  await expect(page.getByRole('button',{name:/选择训练素材.*22015/})).toBeVisible();
  await page.reload();await page.getByRole('button',{name:/选择训练素材.*22015/}).click();
  await picker.getByRole('button',{name:'读取正式标签并核验选择',exact:true}).click();
  await expect.poll(()=>summaries).toBe(2);
  await page.locator('label.el-checkbox').filter({hasText:'允许后台正式资格核验'}).click();
 }else{
 await picker.getByRole('button',{name:'选择本页',exact:true}).click();await picker.getByRole('button',{name:'下一页',exact:true}).click();await expect(picker).toContainText('two.jpg');await picker.getByRole('button',{name:'选择本页',exact:true}).click();await expect(picker).toContainText('已选 2 张');await picker.getByRole('button',{name:'读取正式标签并核验选择',exact:true}).click(); }
 await page.locator('label.el-checkbox').filter({has:page.getByRole('checkbox',{name:'smoke',exact:true})}).click();await expect(page.getByRole('checkbox',{name:'smoke',exact:true})).toBeChecked();await page.getByRole('button',{name:'核验并创建训练',exact:true}).click();expect(posts).toBe(0);await page.getByRole('button',{name:'确认核验并创建',exact:true}).click();await expect.poll(()=>posts).toBe(1);await expect(page.getByRole('button',{name:'核验并创建训练',exact:true})).toBeDisabled();expect(paths).not.toContain('/static/app.js');expect(paths).not.toContain('/static/main.mjs');
});
