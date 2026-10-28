import {test,expect} from '@playwright/test';
import {mkdir} from 'node:fs/promises';
import path from 'node:path';
function bitmap(index){const w=16,h=16,b=Buffer.alloc(54+w*h*3,index+30);b.fill(0,0,54);b.write('BM');b.writeUInt32LE(b.length,2);b.writeUInt32LE(54,10);b.writeUInt32LE(40,14);b.writeInt32LE(w,18);b.writeInt32LE(h,22);b.writeUInt16LE(1,26);b.writeUInt16LE(24,28);return b;}
async function seed(request,count=4){
 const project=await(await request.post('/api/projects',{data:{name:`负样本-${Date.now()}-${Math.random()}`,labels:[{code:'cigarette'},{code:'person'}]}})).json();
 const algorithm=(await(await request.post(`/api/v12/projects/${project.id}/algorithms`,{data:{name:'目标负样本隔离算法',algorithm_type:'yolo_ultralytics'}})).json()).algorithm;
 const images=[];
 for(let i=0;i<count;i++){
  const response=await request.post(`/api/projects/${project.id}/images`,{multipart:{files:{name:`negative-${i}.bmp`,mimeType:'image/bmp',buffer:bitmap(i)}}});expect(response.ok()).toBeTruthy();const image=(await response.json()).uploaded[0];images.push(image);
  if(i){const ann=(await(await request.get(`/api/projects/${project.id}/annotations/${image.id}`)).json()).annotation;
   const box={id:`b-${i}`,label:i===1?'person':'cigarette',class_id:i===1?1:0,x1:1,y1:1,x2:8,y2:8};
   const boxes=i===3?[box,{...box,id:'person',label:'person',class_id:1}]:[box];
   const saved=await request.post(`/api/projects/${project.id}/annotations/${image.id}`,{data:{boxes,annotation_state:'annotated',expected_version:ann.version,source_content_sha256:image.content_sha256,reviewed_label_codes:boxes.map(b=>b.label)}});expect(saved.ok()).toBeTruthy();
  }
 }
 expect((await request.post(`/api/v52/projects/${project.id}/images/mark-ready`,{data:{image_ids:images.map(i=>i.id)}})).ok()).toBeTruthy();
 return {project,algorithm,images};
}
async function open(page,f,pageName='算法列表'){
 await page.route('**/api/v53/bootstrap/snapshot**',route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',f.project.id);return route.continue({url:String(url)})});
 await page.route('**/api/training_options**',route=>route.fulfill({json:{targets:[{id:'negative-cpu',name:'隔离CPU',type:'local',framework:'ultralytics',status:'ready',algorithms:[{key:'yolo_detect',base_model:'yolo11n.pt',default_imgsz:640}],base_models:[{value:'yolo11n.pt',model_status:'FOUND'}]}]}}));
 await page.route('**/api/system/recommendation',route=>route.fulfill({json:{device:'cpu',batch:1,workers:0}}));
 await page.route('**/api/v62/training-devices',route=>route.fulfill({json:{recommended:'cpu',options:[{id:'cpu',available:true}]}}));
 await page.addInitScript(pageName=>localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({page:pageName})),pageName);
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady&&window.NegativePoolRuntime))).toBe(true);
}
async function shot(page,name){const directory=path.resolve('docs/images/negative-samples-20261028');await mkdir(directory,{recursive:true});await page.screenshot({path:path.join(directory,name),fullPage:false});}
test('target negative confirmation happens only on final creation, preserves GT and is reused',async({page,request})=>{
 const f=await seed(request),before=await Promise.all(f.images.map(async i=>(await(await request.get(`/api/projects/${f.project.id}/annotations/${i.id}`)).json()).annotation));
 let creates=0,confirms=0,previews=0;page.on('request',r=>{if(r.url().endsWith('/confirm-negatives'))confirms++;if(r.url().endsWith('/negative-preview'))previews++});
 await page.route('**/train/start',route=>{creates++;expect(route.request().postDataJSON().train_labels).toEqual(['cigarette']);return route.fulfill({status:422,json:{detail:'隔离测试不启动训练'}})});
 await open(page,f);await page.locator('[data-algorithm-card]',{hasText:f.algorithm.name}).getByRole('button',{name:'训练',exact:true}).click();const dialog=page.getByRole('dialog',{name:'创建训练任务',exact:true});
 await page.evaluate(({id,ids})=>window.TrainingDraftRuntime.update({algorithmId:id,materialIds:ids,newLabelCodes:['cigarette']}),{id:f.algorithm.id,ids:f.images.map(i=>i.id)});
 await expect(dialog.locator('[data-training-sample-roles]')).toContainText('待确认负样本 2');expect(previews).toBe(0);expect(confirms).toBe(0);
 await expect.poll(()=>page.evaluate(()=>state.trainingCreationLoading.resources.status)).toBe('ready');await dialog.locator('button[data-training-step="3"]').click();await dialog.locator('.train-ui-submit').click();
 const confirmation=page.getByRole('dialog',{name:'本次训练包含待确认负样本',exact:true});await expect(confirmation).toBeVisible();expect(creates).toBe(0);await expect.poll(()=>confirmation.locator('img').evaluateAll(nodes=>nodes.every(n=>n.complete&&n.naturalWidth>0))).toBe(true);await shot(page,'target-confirmation.png');
 await confirmation.getByRole('button',{name:'返回检查',exact:true}).click();await expect(confirmation).toHaveCount(0);expect(confirms).toBe(0);expect(creates).toBe(0);
 await dialog.locator('.train-ui-submit').click();await expect(confirmation).toBeVisible();await confirmation.getByRole('button',{name:'确认并创建训练任务',exact:true}).click();
 await expect.poll(()=>creates).toBe(1);expect(confirms).toBe(1);await expect(confirmation).toHaveCount(0);
 await expect.poll(()=>page.evaluate(()=>window.TrainingSubmitRuntime.isSubmitting())).toBe(false);
 await page.getByRole('dialog',{name:'训练暂不可开始',exact:true}).getByRole('button',{name:'返回训练配置',exact:true}).click();await dialog.locator('button[data-training-step="3"]').click();await dialog.locator('.train-ui-submit').click();await expect.poll(()=>creates).toBe(2);expect(confirms).toBe(1);await expect(confirmation).toHaveCount(0);
 const after=await Promise.all(f.images.map(async i=>(await(await request.get(`/api/projects/${f.project.id}/annotations/${i.id}`)).json()).annotation));expect(after).toEqual(before);
 for(let i=0;i<f.images.length;i++)expect(await(await request.get(`/api/v61/projects/${f.project.id}/materials/${f.images[i].id}/content`)).body()).toEqual(bitmap(i));
 await page.getByRole('dialog',{name:'训练暂不可开始',exact:true}).getByRole('button',{name:'返回训练配置',exact:true}).click();await dialog.locator('button[data-training-step="2"]').click();await dialog.getByRole('button',{name:'预览颜色变化',exact:true}).click();const csc=page.getByRole('dialog',{name:'跨设备颜色增强预览',exact:true});await expect(csc.getByAltText('增强后')).toBeVisible();await expect.poll(()=>csc.locator('img').evaluateAll(nodes=>nodes.length===2&&nodes.every(n=>n.complete&&n.naturalWidth>0))).toBe(true);await shot(page,'negative-csc-preview.png');
});
test('pool and category tabs reuse images, filter across pages and add to original training draft',async({page,request})=>{
 const f=await seed(request,50),base=`/api/v61/projects/${f.project.id}/negative-pool`;
 const category=(await(await request.post(base+'/categories',{data:{name:'拿手机'}})).json());
 expect((await request.post(base+'/members',{data:{image_ids:f.images.map(i=>i.id),action:'add',category_ids:[category.id]}})).ok()).toBeTruthy();
 await open(page,f,'数据集');const tabs=page.locator('.negative-pool-tabs');await tabs.getByRole('button',{name:'负样本池',exact:true}).click();
 await expect(page.locator('.negative-pool-card')).toHaveCount(48);await page.getByRole('button',{name:'全选当前筛选结果',exact:true}).click();await expect(page.locator('#negativePoolSelection')).toContainText('已选 50 张');
 await page.getByRole('button',{name:'下一页',exact:true}).click();await expect(page.locator('.negative-pool-card')).toHaveCount(2);await expect(page.locator('.negative-pool-card input:checked')).toHaveCount(2);
 await page.locator('.negative-pool-card input').first().uncheck();await expect(page.locator('#negativePoolSelection')).toContainText('已选 49 张');await expect.poll(()=>page.locator('.negative-pool-card img').evaluateAll(nodes=>nodes.length===2&&nodes.every(n=>n.complete&&n.naturalWidth>0))).toBe(true);await shot(page,'negative-pool.png');
 await page.getByRole('button',{name:'加入训练草稿',exact:true}).click();const choose=page.getByRole('dialog',{name:'选择训练算法',exact:true});await expect(choose).toBeVisible();await choose.getByRole('button',{name:'进入训练配置',exact:true}).click();
 await expect(page.getByRole('dialog',{name:'创建训练任务',exact:true})).toBeVisible();await expect.poll(()=>page.evaluate(()=>window.TrainingDraftRuntime.current().materialIds.length)).toBe(49);
 await page.getByRole('dialog',{name:'创建训练任务',exact:true}).locator('.train-ui-cancel').click();
 await page.evaluate(()=>setPage('标签管理'));await page.locator('.negative-pool-tabs').getByRole('button',{name:'负样本分类',exact:true}).click();await expect(page.locator('.negative-pool-category-list')).toContainText('拿手机');
 await page.getByRole('button',{name:'新建分类',exact:true}).click();const create=page.getByRole('dialog',{name:'新建负样本分类',exact:true});await create.locator('[name=name]').fill('逆光');await create.getByRole('button',{name:'确认',exact:true}).click();await expect(page.locator('.negative-pool-category-list')).toContainText('逆光');
 const project=await(await request.get(`/api/v12/projects/${f.project.id}/labels`)).json();expect(project.items.map(v=>typeof v==='string'?v:v.code)).toEqual(['cigarette','person']);
 expect((await(await request.get(base+'/ids')).json()).items).toHaveLength(50);
});
