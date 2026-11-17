import {test,expect,type Page} from '@playwright/test';
import {fixture} from './fixture';

async function setup(page:Page){
 const requests:{method:string;path:string;query:string}[]=[],assets:string[]=[];let wrongIdentity=false,holdSamples=false,release:()=>void=()=>{};
 page.on('response',response=>{if(response.url().includes('/static/vendor/echarts/'))assets.push(response.url())});
 await page.route('**/report-detail-fixture*',route=>route.fulfill({contentType:'text/html',body:fixture}));
 await page.route('**/api/**',async route=>{
  const request=route.request(),url=new URL(request.url()),path=url.pathname;requests.push({method:request.method(),path,query:url.search});
  if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'报告隔离用户'}}});
  if(request.method()!=='GET')return route.fulfill({status:405,json:{message:'Report acceptance forbids writes'}});
  const project=path.match(/\/projects\/([^/]+)/)?.[1]||'p';
  if(path.includes('/tasks')){
   const row={task_id:'saved-job',project_id:project,kind:'TRAINING',status:'SUCCEEDED',report_job_id:'saved-job',algorithm_id:'a',version_id:'v',phase:'finished',progress_percent:100};
   return route.fulfill({json:path.includes('/tasks/')?{ok:true,project_id:project,task:row}:{ok:true,project_id:project,items:[row],next_cursor:null,filter_options:{}}});
  }
  if(path.includes('/jobs/')&&path.endsWith('/report'))return route.fulfill({json:{ok:true,project_id:project,job_id:'saved-job',algorithm_id:'a',version_id:'v',state:'AVAILABLE',source:'DURABLE_FINALIZED',val_metrics:{precision:0,recall:null,map50:.4},test_metrics:{precision:.9,recall:.8,map50:.72},test_status:'succeeded',history:[{epoch:1,map50:0,box_loss:1},{epoch:2,map50:.4,box_loss:.5}],history_total:2,history_offset:0,history_limit:100,history_has_next:false}});
  if(path.endsWith('/evaluation/report')){
   const section=url.searchParams.get('section')||'summary',offset=Number(url.searchParams.get('offset')||0);
   const evaluation:any={evaluation_id:'e'.repeat(64),status:'succeeded',metrics:{precision:.9,recall:.8,map50:.72},per_class:[{class_id:0,label:'smoke',ground_truth_count:2,prediction_count:1,true_positive:0,false_positive:1,false_negative:2,precision:0,recall:null,map50:.72}],confidence_curve_protocol:'same_class_confidence_first_iou_0.5_grid_0.05'};
   if(section==='curves')evaluation.confidence_curves=[{class_id:0,points:[{confidence:.1,precision:0,recall:1,f1:0},{confidence:.5,precision:.8,recall:.6,f1:.68}],points_total:2,points_truncated:false}];
   if(section==='confusion')evaluation.confusion_matrix={protocol:'confidence_first_class_agnostic_iou_0.5',operating_conf:.5,cells:[{actual:0,predicted:0,count:0},{actual:0,predicted:null,count:2}],cells_total:2,cells_truncated:false};
   return route.fulfill({json:{ok:true,project_id:project,algorithm_id:'a',version_id:wrongIdentity?'wrong-version':'v',state:'AVAILABLE',evaluation_id:'e'.repeat(64),section,offset,limit:20,total:1,has_next:false,evaluation}});
  }
  if(path.endsWith('/evaluation/samples')){
   if(holdSamples)await new Promise<void>(resolve=>release=resolve);
   const offset=Number(url.searchParams.get('offset')||0),issue=url.searchParams.get('issue')||'fp';
   const imageId=`${issue}-image-${offset}`,name=`${imageId}.jpg`,preview=`/api/v12/projects/${project}/algorithms/a/versions/v/evaluation/images/${name}?expected_evaluation_id=${'e'.repeat(64)}&expected_image_id=${imageId}&expected_sha256=${'a'.repeat(64)}`;
   return route.fulfill({json:{ok:true,project_id:project,algorithm_id:'a',version_id:wrongIdentity?'wrong-version':'v',evaluation_id:'e'.repeat(64),total:21,offset,limit:20,has_next:offset===0,items:[{image_id:imageId,image:name,filename:name,width:640,height:480,image_content_sha256:'a'.repeat(64),preview_url:preview,fp_count:issue==='fp'?1:0,fn_count:issue==='fn'?1:0,gt_boxes:[{label:'smoke',box:[1,1,40,50],kind:'gt'}],pred_boxes:[],box_evidence_available:true,evidence_complete:true,gt_boxes_total:1,pred_boxes_total:0,gt_boxes_truncated:false,pred_boxes_truncated:false}]}});
  }
  if(path.includes('/evaluation/images/'))return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#ddd"/></svg>'});
  if(path.includes('/evaluation/compare/'))return route.fulfill({json:{ok:true,project_id:project,algorithm_id:'a',version_id:'v',comparison:{current_version_id:'v',source_version_id:'other',comparable:false,reason_codes:['benchmark_scope_mismatch'],metrics:{},classes:[],parameter_differences:{},offset:0,limit:20,total:0,has_next:false}}});
  if(path.endsWith('/algorithms/a'))return route.fulfill({json:{ok:true,project_id:project,algorithm:{id:'a'},items:[{id:'v',version_name:'当前版本'},{id:'other',version_name:'其他 Test 版本'}],total:2,page:1}});
  return route.fulfill({json:{ok:true,items:[],revision:1,templates:[]}});
 });
 await page.goto('/report-detail-fixture?vue_training_tasks=1&vue_training_report=1');await page.waitForFunction(()=>window.fixtureReady);
 // Same original report module as main; actual local ECharts, no chart mock.
 await page.evaluate(async()=>{const reports=await import('/static/modules/reports.js');window.PlatformCore={...window.PlatformCore,reports}});
 await page.evaluate(()=>window.setPage('训练任务只读中心'));await page.getByRole('button',{name:'报告',exact:true}).click();await expect(page.getByRole('heading',{name:'Val 指标',exact:true})).toBeVisible();
 return {requests,assets,wrong:()=>{wrongIdentity=true},hold:()=>{holdSamples=true},release:()=>release()};
}

test('summary separates Val/Test and loads original offline charts only on demand',async({page})=>{
 const errors:string[]=[];page.on('pageerror',error=>errors.push(error.message));const h=await setup(page);
 const val=page.locator('.report-metrics>section').first(),independent=page.locator('.report-metrics>section').nth(1);
 await expect(val.getByText('0',{exact:true})).toBeVisible();await expect(val.getByText('未提供',{exact:true})).toBeVisible();await expect(independent.getByText('0.72',{exact:true})).toBeVisible();
 expect(h.requests.filter(row=>row.path.includes('/evaluation/'))).toHaveLength(0);expect(h.assets).toHaveLength(0);
 await page.getByRole('button',{name:'训练过程',exact:true}).click();const history=page.getByRole('region',{name:'训练过程分页',exact:true});
 await expect(history.locator('[data-report-chart] canvas').first()).toBeVisible();expect(h.assets.some(url=>url.includes('/static/vendor/echarts/echarts.min.js'))).toBe(true);
 await page.getByRole('button',{name:'类别指标',exact:true}).click();const detail=page.getByRole('region',{name:'独立Test详细报告',exact:true});await expect(detail.getByText('smoke',{exact:true})).toBeVisible();await expect(detail.getByRole('columnheader',{name:'P / R / mAP / F1',exact:true})).toBeVisible();await expect(detail.locator('dt').filter({hasText:/^map50$/})).toBeVisible();await expect(detail.locator('dt').filter({hasText:/^map50$/}).locator('xpath=following-sibling::dd[1]')).toHaveText('0.72');
 await page.getByRole('button',{name:'PR 阈值曲线',exact:true}).click();await expect(detail.locator('[data-report-chart] canvas').first()).toBeVisible();await expect(detail).toContainText('不等同 AP');
 await page.getByRole('button',{name:'混淆矩阵',exact:true}).click();await expect(detail.locator('[data-report-chart] canvas').first()).toBeVisible();
 expect(h.requests.every(row=>row.method==='GET')).toBe(true);expect(errors).toEqual([]);
});

test('FP/FN uses bounded pages and exact frozen preview evidence; different Test has no ranking',async({page})=>{
 const h=await setup(page);await page.getByRole('button',{name:'FP / FN 样本',exact:true}).click();const detail=page.getByRole('region',{name:'独立Test详细报告',exact:true});
 const image=detail.getByRole('img',{name:'fp-image-0.jpg',exact:true});await expect(image).toBeVisible();await expect.poll(()=>image.evaluate((node:HTMLImageElement)=>node.naturalWidth)).toBe(640);
 const frozen=new URL((await image.getAttribute('src'))!,'http://fixture');expect(frozen.pathname).toContain('/projects/p/algorithms/a/versions/v/evaluation/images/');expect(frozen.searchParams.get('expected_evaluation_id')).toBe('e'.repeat(64));expect(frozen.searchParams.get('expected_image_id')).toBe('fp-image-0');expect(frozen.searchParams.get('expected_sha256')).toBe('a'.repeat(64));
 await page.getByRole('button',{name:'下一页报告明细',exact:true}).click();await expect(detail.getByRole('heading',{name:'fp-image-20.jpg',exact:true})).toBeVisible();
 await page.getByRole('combobox',{name:'样本错误类型',exact:true}).selectOption('fn');await expect(detail.getByRole('heading',{name:'fn-image-0.jpg',exact:true})).toBeVisible();
 const pages=h.requests.filter(row=>row.path.endsWith('/evaluation/samples')).map(row=>new URLSearchParams(row.query));expect(pages.map(query=>query.get('offset'))).toEqual(['0','20','0']);expect(pages.every(query=>query.get('limit')==='20')).toBe(true);
 await page.getByRole('button',{name:'版本对比',exact:true}).click();await page.getByRole('combobox',{name:'对照版本',exact:true}).selectOption('other');await page.getByRole('button',{name:'读取版本对比',exact:true}).click();const compare=page.getByRole('region',{name:'版本可比性',exact:true});await expect(compare).toContainText('原评测合同判定不可比');await expect(compare).toContainText('benchmark_scope_mismatch');await expect(compare.getByRole('heading',{name:'指标变化（原响应）',exact:true})).toHaveCount(0);
 await page.getByRole('button',{name:'返回来源列表',exact:true}).click();await expect(page.getByRole('button',{name:'查看任务saved-job',exact:true})).toBeVisible();expect(h.requests.every(row=>row.method==='GET')).toBe(true);
});

test('mismatched detail identity is rejected and late old-project responses cannot repaint',async({page})=>{
 const h=await setup(page);h.wrong();await page.getByRole('button',{name:'类别指标',exact:true}).click();await expect(page.getByRole('alert').filter({hasText:'独立评测身份不一致'})).toBeVisible();await expect(page.getByText('smoke',{exact:true})).toHaveCount(0);
 h.hold();await page.getByRole('button',{name:'FP / FN 样本',exact:true}).click();await expect.poll(()=>h.requests.filter(row=>row.path.endsWith('/evaluation/samples')).length).toBe(1);
 await page.evaluate(()=>{window.state.project={id:'q'};return window.setPage('训练任务只读中心')});h.release();await expect(page.getByRole('button',{name:'查看任务saved-job',exact:true})).toBeVisible();await expect(page.getByRole('region',{name:'独立Test详细报告',exact:true})).toHaveCount(0);expect(h.requests.every(row=>row.method==='GET')).toBe(true);
});
