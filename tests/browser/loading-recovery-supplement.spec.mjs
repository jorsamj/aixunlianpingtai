import {test,expect} from '@playwright/test';

async function boot(page,request){
 const project=await (await request.post('/api/projects',{data:{name:`补充Loading验收-${Date.now()}`,labels:[]}})).json();
 await page.route('**/api/v53/bootstrap/snapshot**',async route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',project.id);await route.continue({url:url.toString()});});
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady===true)).toBe(true);
 return project.id;
}

for(const flow of ['clean','convert','publish','annotation'])for(const outcome of ['pending','rejected'])test(`${flow} ${outcome} mutation has recoverable feedback and safe retry`,async({page,request})=>{
 const project=await boot(page,request);let posts=0,reads=0,conversionRequestId='';const verifiedConversionIds=[];
 const path=flow==='clean'?`/api/v47/projects/${project}/clean-tasks`:flow==='convert'?`/api/v39/projects/${project}/deploy/jobs`:flow==='annotation'?`/api/projects/${project}/annotations/loading-image`:`/api/v64/external-publish/projects/${project}/algorithms/loading-a/versions/loading-v`;
 await page.route(`**${path}${flow==='publish'?'**':''}`,async route=>{
   if(route.request().method()==='POST'){posts++;if(flow==='convert')conversionRequestId=route.request().postDataJSON()?.request_id||'';if(outcome==='rejected')return route.fulfill({status:422,json:{message:'验收夹具参数错误'}});return;}
   reads++;
   const body=flow==='annotation'?{image:{id:'loading-image',content_sha256:'a'.repeat(64)},annotation:{version:1,boxes:[{id:'b',class_id:0,label:'car',x1:1,y1:1,x2:20,y2:20}]}}:flow==='publish'?{ok:true,algorithm:{id:'loading-a',external_product_id:'p'},version:{id:'loading-v'},publication:null,discovered:[{publish_mapping_status:'mapped',target:'original',file_name:'best.pt'}],mapped_artifact_count:1,blocked_artifact_count:0,transport_ready:true,identity_ready:true,publish_ready:true,conversion_active:false}: {items:[]};
   await route.fulfill({json:body});
 });
 if(flow==='convert'){
   await page.route('**/api/v39/deploy/resources?detect_missing=false',route=>route.fulfill({json:{items:[{id:'loading-resource',status:'ready',targets:['onnx']}]}}));
   await page.route('**/api/v42/projects/*/algorithms/loading-a/versions/loading-v/deployments*',route=>{reads++;return route.fulfill({json:{algorithm:{id:'loading-a'},version:{id:'loading-v'},items:[]}})});
   // Conversion reconciliation is addressed by its persisted idempotency key,
   // not by re-reading the collection URL used for POST creation.
   await page.route(`**${path}/by-request/*`,route=>{reads++;verifiedConversionIds.push(decodeURIComponent(new URL(route.request().url()).pathname.split('/').pop()));return route.fulfill({json:{found:false,pending:true}})});
 }
 await page.clock.install();
 await page.evaluate(({flow})=>{
   const id='supplement-loading-fixture';document.getElementById(id)?.remove();const host=document.createElement('div');host.id=id;host.style.cssText='position:fixed;top:200px;left:400px;z-index:999999;background:white;padding:24px';document.body.appendChild(host);
   state.page='算法列表';
   if(flow==='clean')host.innerHTML='<div class="clean427-create"><input type="radio" name="cl427Scope" value="all" checked><input type="radio" name="cl427Execution" value="local" checked><button id="cl427Start" class="btn">开始清洗</button></div>';
   if(flow==='convert'){
     host.innerHTML='<div class="convert428-create"><input type="radio" name="conv428Target" value="onnx" checked><select id="conv428Resource"><option value="loading-resource">资源</option></select><input id="conv428Chip" value=""><button data-convert-submit class="btn">开始转换</button></div>';
     state.conv428ResourcesCurrent=true;state.conv428Resources=[{id:'loading-resource',status:'ready',targets:['onnx']}];
   }
   if(flow==='publish')host.innerHTML='<div class="alg428-version-row"><button class="btn" data-external-publish-action="loading-a:loading-v">发布</button></div>';
   if(flow==='annotation'){
     host.innerHTML='<button id="ann414Save" class="btn">保存标注</button><span id="annSaveState"></span>';
     state.activeImage={id:'loading-image',content_sha256:'a'.repeat(64)};state.images=[state.activeImage];state.ann={version:1,boxes:[{id:'b',class_id:0,label:'car',x1:1,y1:1,x2:20,y2:20}]};state.annDirty=true;
   }
   const invoke=()=>flow==='clean'?window.submitClean427():flow==='convert'?window.submitConvert428('loading-a','loading-v'):flow==='publish'?window.ExternalAlgorithmPublishRuntime.publishVersion('loading-a','loading-v',host.querySelector('button')):window.saveAnnotationCore420(true);
   window.invokeSupplementLoading=invoke;host.querySelector('button').onclick=()=>{window.supplementLoadingPromise=invoke()};
 },{flow});
 const button=page.locator('#supplement-loading-fixture button').first();await button.click();
 await expect.poll(()=>posts).toBe(1);
 if(outcome==='rejected'){
   await expect(button).not.toHaveAttribute('aria-busy','true');
   await page.evaluate(()=>{window.supplementRetryPromise=window.invokeSupplementLoading()});
   await expect.poll(()=>posts).toBe(2);return;
 }
 await expect(button).toHaveAttribute('aria-busy','true');
 if(flow==='convert')await page.evaluate(()=>{const form=document.querySelector('.convert428-create');const next=form.cloneNode(true);delete next.dataset.submitting;next.querySelector('button').removeAttribute('aria-busy');next.querySelector('button').disabled=false;form.replaceWith(next);});
 await page.evaluate(()=>window.invokeSupplementLoading()); // survives a replacement conversion form
 await page.clock.fastForward(30001);
 await expect(button).not.toHaveAttribute('aria-busy','true');
 expect(posts).toBe(1);
 // Second click queries state only. Annotation validates the unchanged CAS version.
 await page.evaluate(()=>{window.supplementRetryPromise=window.invokeSupplementLoading()});
 if(flow==='convert'){
   await expect.poll(()=>verifiedConversionIds.length).toBeGreaterThan(0);
   expect(conversionRequestId).toMatch(/^conv_/);
   expect(verifiedConversionIds).toContain(conversionRequestId);
 }else await expect.poll(()=>reads).toBeGreaterThan(0);
 expect(posts).toBe(1);
 if(flow==='annotation')await expect(page.locator('#annSaveState')).toContainText('版本已核验');
});
