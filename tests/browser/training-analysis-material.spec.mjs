import {test,expect} from '@playwright/test';

function fixture(label='person',size=800,workers=8){
 const jobId='isolated-'+label,versionId='v-'+label;
 return {job:{id:jobId,status:'done',auto_version_id:versionId},report:{evidence_fixture:true,
 identity:{project_id:'',algorithm_id:'a-isolated',algorithm_name:label+'隔离验收',version_id:versionId,job_id:jobId},
 status:'done',version_name:versionId,framework:'ultralytics',model_architecture:'YOLOv11n',class_mapping:[{class_id:0,code:label,name:label}],
 requested_train_params:{epochs:300,imgsz:size,workers,batch:32,precision:'fp32',optimizer:'auto',lr0:.01},actual_train_params:{imgsz:size,workers,batch:32,effective_precision:'fp32'},metrics:{},history:[],evaluation:{status:'not_recorded'},
 representative_errors:{status:'unavailable',items:[],reason:'未记录可核验的冻结异常样本'},
 conversions:[{artifact_id:'test-bmodel',target:'sophon',chip_code:'bm1688',sha256:'a'.repeat(64),metadata:{precision:'fp16',source_training_precision:'fp32',image_width:size,image_height:size,validation_status:'converted_unverified'}}]}};
}
async function setup(page,request){
 const project=await(await request.post('/api/projects',{data:{name:'报告隔离验收-'+Date.now(),labels:[{code:'person',display_name:'Person'}]}})).json();
 const payloads={person:fixture(),Car:fixture('Car',640,0)};
 for(const data of Object.values(payloads))data.report.identity.project_id=project.id;
 await page.route('**/api/v53/bootstrap/snapshot**',async route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',project.id);await route.continue({url:url.toString()})});
 await page.route('**/api/v44/projects/*/jobs/*/report**',route=>{const id=new URL(route.request().url()).pathname.split('/').at(-2);const key=id==='isolated-Car'?'Car':'person';return route.fulfill({json:payloads[key]})});
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>typeof window.trainingReport425==='function'&&state.uiReady===true)).toBe(true);
 return {project,payloads};
}
for(const width of [1920,1440,1366,375])test(`report materials are truthful usable and responsive at ${width}px`,async({page,request,context})=>{
 await page.setViewportSize({width,height:1000});await context.grantPermissions(['clipboard-read','clipboard-write']);
 await setup(page,request);
 let aiWrites=0;page.on('request',r=>{if(r.method()==='POST'&&/chat\/completions|error-cause-analysis|api\/v\d+\/.*ai-analysis/.test(r.url()))aiWrites++});
 await page.evaluate(()=>window.trainingReport425('isolated-person'));
 let root=page.locator('.training-report-workspace');await expect(root).toBeVisible();
 await root.getByRole('button',{name:'复制 ChatGPT 分析材料',exact:true}).click();
 await expect(root.locator('[data-report-copy-status]')).toContainText('已复制');
 let copied=await page.evaluate(()=>navigator.clipboard.readText());expect(copied).toContain('YOLOv11n');expect(copied).toMatch(/BM1688|bm1688/);expect(copied).toContain('实际Optimizer：未记录');expect(copied).toContain('隔离测试数据');
 await root.locator('.report-supplements > summary').click();await root.locator('[data-report-supplement="scenario"]').fill('工厂摄像头 access_token=private-value');
 await root.getByRole('button',{name:'复制 ChatGPT 分析材料',exact:true}).click();copied=await page.evaluate(()=>navigator.clipboard.readText());expect(copied).toContain('工厂摄像头');expect(copied).not.toContain('private-value');expect(copied).toContain('尚未由训练系统独立验证');
 expect(await root.evaluate(node=>node.scrollWidth<=node.clientWidth+2)).toBe(true);
 await root.locator('[data-report-tab="errors"]').click();await expect(root.locator('[data-report-tab="errors"]')).toHaveAttribute('aria-selected','true');await expect(root.locator('[data-report-tab="overview"]')).toHaveAttribute('aria-selected','false');await expect(root.locator('[data-report-pane="errors"]')).toContainText('未记录可核验');
 await page.screenshot({path:test.info().outputPath(`training-report-${width}.png`),fullPage:true,animations:'disabled'});
 await page.evaluate(()=>window.closeModal());await page.evaluate(()=>window.trainingReport425('isolated-Car'));
 root=page.locator('.training-report-workspace');await root.getByRole('button',{name:'复制 ChatGPT 分析材料',exact:true}).click();await expect(root.locator('[data-report-copy-status]')).toContainText('已复制');
 copied=await page.evaluate(()=>navigator.clipboard.readText());expect(copied).toContain('Car');expect(copied).toContain('请求Workers：0');expect(copied).not.toContain('工厂摄像头');expect(copied).not.toContain('isolated-person');expect(aiWrites).toBe(0);
});

test('interactive report charts hover zoom persist and dispose without restore controls using local ECharts',async({page,request})=>{
 const {payloads}=await setup(page,request);
 // Explicit synthetic curve fixture for interaction QA; not the user's Person metrics.
 payloads.person.report.identity.algorithm_name='曲线交互隔离数据';payloads.person.report.history=[{epoch:1,map50:.2,precision:.3},{epoch:2,map50:null,precision:.4},{epoch:3,map50:.6,precision:.7},{epoch:4,map50:.8,precision:.9}];
 await page.evaluate(()=>window.trainingReport425('isolated-person'));const root=page.locator('.training-report-workspace');await root.locator('[data-report-tab="curves"]').click();
 const host=root.locator('[data-report-chart="accuracy"]');await expect(host.locator('canvas')).toBeVisible();
 await expect.poll(()=>host.evaluate(node=>!!window.echarts?.getInstanceByDom(node))).toBe(true);
 await host.scrollIntoViewIfNeeded();
 const point=await host.evaluate(node=>{const c=window.echarts.getInstanceByDom(node);window.__reportChart=c;const [x,y]=c.convertToPixel({xAxisIndex:0,yAxisIndex:0},[3,.6]);return {x,y}});
 const box=await host.boundingBox();await page.mouse.move(box.x+point.x-2,box.y+point.y);await expect(host).toContainText('mAP50');
 await page.mouse.wheel(0,-500);await expect.poll(()=>host.evaluate(node=>{const z=window.echarts.getInstanceByDom(node).getOption().dataZoom[0];return z.end-z.start<100})).toBe(true);
 const retainedZoom=await host.evaluate(node=>{const z=window.echarts.getInstanceByDom(node).getOption().dataZoom[0];return {start:z.start,end:z.end}});
 await root.locator('[data-report-tab="overview"]').click();await root.locator('[data-report-tab="curves"]').click();
 expect(await host.evaluate(node=>window.__reportChart===window.echarts.getInstanceByDom(node))).toBe(true);
 await expect(root.locator('[data-chart-reset]')).toHaveCount(0);expect(await host.evaluate(node=>!!window.echarts.getInstanceByDom(node).getOption().toolbox?.[0]?.feature?.restore)).toBe(false);await expect.poll(()=>host.evaluate(node=>{const z=window.echarts.getInstanceByDom(node).getOption().dataZoom[0];return {start:z.start,end:z.end}})).toEqual(retainedZoom);
 const gap=await host.evaluate(node=>window.echarts.getInstanceByDom(node).getOption().series.find(s=>s.name==='mAP50').data);expect(gap).toEqual([.2,null,.6,.8]);
 await page.screenshot({path:test.info().outputPath('training-report-interactive.png'),fullPage:true,animations:'disabled'});
 await page.evaluate(()=>window.closeModal());expect(await page.evaluate(()=>window.__reportChart.isDisposed())).toBe(true);
});


test('late report cannot replace selected task and denied clipboard keeps complete preview',async({page,request})=>{
 const {payloads}=await setup(page,request);let release,arrived;
 const waiting=new Promise(resolve=>arrived=resolve),gate=new Promise(resolve=>release=resolve);
 await page.route('**/jobs/isolated-person/report',async route=>{arrived();await gate;await route.fulfill({json:payloads.person})});
 await page.evaluate(()=>{void window.trainingReport425('isolated-person')});await waiting;
 await page.evaluate(()=>window.closeModal());await page.evaluate(()=>window.trainingReport425('isolated-Car'));
 release();await expect(page.locator('.training-report-workspace')).toHaveAttribute('data-report-job','isolated-Car');
 await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async()=>{window.__clipboardCalls=(window.__clipboardCalls||0)+1;throw new Error('permission denied')}}}));
 const root=page.locator('.training-report-workspace');await root.getByRole('button',{name:'复制 ChatGPT 分析材料',exact:true}).click();
 await expect(root.locator('[data-report-copy-status]')).toContainText('复制失败');await expect(root.locator('.report-analysis-text')).toHaveValue(/Car/);
 expect(await page.evaluate(()=>window.__clipboardCalls)).toBe(1);await expect(root.getByRole('button',{name:'复制 ChatGPT 分析材料',exact:true})).toBeEnabled();
 await root.locator('.report-supplements > summary').click();await root.locator('[data-report-supplement="scenario"]').fill('新增现场说明');
 await expect(root.locator('.report-analysis-text')).toHaveValue(/新增现场说明/);
});

test('frozen anomaly thumbnail binds exact report identity and failure does not show stale image',async({page,request})=>{
 const {payloads}=await setup(page,request),report=payloads.person.report;
 const sample={image:'frozen.jpg',image_id:'test-image',image_content_sha256:'c'.repeat(64),fp_count:1,fn_count:0,fp_labels:['person'],fn_labels:[],gt_boxes:[],pred_boxes:[{confidence:.8}],image_width:100,image_height:80};
 report.evaluation={status:'succeeded',evaluation_id:'b'.repeat(64)};report.representative_errors={status:'available',evaluation_id:'b'.repeat(64),items:[sample]};
 let reads=0;
 await page.route('**/evaluation/images/frozen.jpg?**',route=>{reads++;const u=new URL(route.request().url());expect(u.searchParams.get('expected_evaluation_id')).toBe('b'.repeat(64));expect(u.searchParams.get('expected_image_id')).toBe('test-image');expect(u.searchParams.get('expected_sha256')).toBe('c'.repeat(64));return route.fulfill({status:409,json:{detail:{code:'EVALUATION_IDENTITY_CHANGED',message:'报告冻结评测或图片身份已变化',retryable:false}}})});
 await page.evaluate(()=>window.trainingReport425('isolated-person'));const root=page.locator('.training-report-workspace');
 await root.locator('[data-report-tab="errors"]').click();await expect(root.locator('[data-eval-thumb-status]')).toContainText('身份已变化');
 await expect(root.locator('.evaluation429-thumb img')).toBeHidden();await root.locator('[data-report-tab="overview"]').click();await root.locator('[data-report-tab="errors"]').click();expect(reads).toBe(1);
});
