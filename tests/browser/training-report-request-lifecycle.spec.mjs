import {test,expect} from '@playwright/test';

async function setup(page,request){
 const created=await (await request.post('/api/projects',{data:{name:`报告生命周期-${Date.now()}`,labels:[]}})).json();
 await page.route('**/api/v53/bootstrap/snapshot**',async route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',created.id);await route.fallback({url:String(url)})});
 await page.goto('/');
 await expect.poll(()=>page.evaluate(()=>typeof window.trainingReportCore425==='function'&&state.uiReady===true),{timeout:20000}).toBe(true);
 await expect.poll(()=>page.evaluate(()=>state.project?.id)).toBe(created.id);
 return created.id;
}
function report(project,version='version-a'){
 return {job:{id:'report-job',status:'done'},report:{identity:{project_id:project,job_id:'report-job',algorithm_id:'algorithm-a',version_id:version,algorithm_name:'隔离报告验收'},history:[{epoch:1,map50:.5,precision:.6},{epoch:2,map50:null,precision:.7},{epoch:3,map50:.8,precision:.9}],metrics:{},evaluation:{status:'not_recorded'},evidence_fixture:true}};
}
const open=page=>page.evaluate(()=>{void window.trainingReportCore425('report-job',{algorithmId:'algorithm-a',versionId:'version-a'})});
const dialog=page=>page.getByRole('dialog',{name:'训练报告',exact:true}).last();

test('report opens immediately, slow response keeps close usable and true historical evidence renders',async({page,request})=>{
 const project=await setup(page,request);let release,started=false;
 const gate=new Promise(resolve=>release=resolve);
 await page.route('**/api/v44/projects/*/jobs/report-job/report**',async route=>{started=true;await gate;await route.fulfill({json:report(project)})});
 await open(page);await expect.poll(()=>started).toBe(true);
 await expect(dialog(page)).toBeVisible();await expect(dialog(page).locator('.ui-skeleton')).toBeVisible();await expect(dialog(page).getByRole('button',{name:'关闭',exact:true})).toBeEnabled();
 release();await expect(dialog(page).locator('[data-report-job="report-job"]')).toBeVisible();
 await expect(dialog(page).locator('[data-training-report-loading]')).toHaveCount(0);
 await expect(dialog(page)).toContainText('未记录可信冻结数据分布');
 await dialog(page).locator('[data-report-tab="curves"]').click();
 const host=dialog(page).locator('[data-report-chart="accuracy"]');await expect(host.locator('canvas')).toHaveCount(1);
 const option=await host.evaluate(node=>window.echarts.getInstanceByDom(node).getOption());
 expect(option.series.find(row=>row.name==='mAP50').data).toEqual([.5,null,.8]);expect(option.dataZoom.length).toBeGreaterThan(0);expect(option.legend.length).toBeGreaterThan(0);expect(option.toolbox?.[0]?.feature?.restore).toBeUndefined();
 await expect(dialog(page).locator('[data-chart-reset]')).toHaveCount(0);await expect(dialog(page).getByText('恢复视图',{exact:true})).toHaveCount(0);
 await host.scrollIntoViewIfNeeded();
 const chartPoint=await host.evaluate(node=>{const chart=window.echarts.getInstanceByDom(node),point=chart.convertToPixel({seriesIndex:0},[0,.6]),rect=node.getBoundingClientRect();return{x:rect.x+point[0],y:rect.y+point[1]}});
 await page.mouse.move(chartPoint.x,chartPoint.y);await expect(host).toContainText('0.6');
 await page.evaluate(()=>{window.__reportChart=window.echarts.getInstanceByDom(document.querySelector('[data-report-chart="accuracy"]'));window.closeModalCore424()});
 await expect.poll(()=>page.evaluate(()=>window.__reportChart.isDisposed())).toBe(true);
});

test('report HTTP errors 404 409 500 502 504 show reason and retry succeeds within same modal',async({page,request})=>{
 const project=await setup(page,request);let status=404;
 await page.route('**/api/v44/projects/*/jobs/report-job/report**',route=>route.fulfill(status===200?{json:report(project)}:{status,json:{message:'隔离报告读取失败'}}));
 for(const code of [404,409,500,502,504]){
  status=code;await open(page);await expect(dialog(page).getByRole('alert')).toContainText(`HTTP_${code}`);await expect(dialog(page).getByRole('button',{name:'重新读取报告'})).toBeEnabled();await page.evaluate(()=>window.closeModalCore424());
 }
 await open(page);await expect(dialog(page).getByRole('alert')).toBeVisible();status=200;
 await dialog(page).getByRole('button',{name:'重新读取报告'}).click();await expect(dialog(page).locator('[data-report-job="report-job"]')).toBeVisible();
 await expect(page.getByRole('dialog',{name:'训练报告',exact:true})).toHaveCount(1);
});

test('permanently pending report expires after real deadline and stops loading with retry',async({page,request})=>{
 await setup(page,request);let started=false;
 await page.route('**/api/v44/projects/*/jobs/report-job/report**',route=>{started=true;return new Promise(()=>{})});
 await page.clock.install();await open(page);await expect.poll(()=>started).toBe(true);await expect(dialog(page).locator('.ui-skeleton')).toBeVisible();
 await page.clock.fastForward(3000);await expect(dialog(page)).toContainText('仍在读取');
 await page.clock.fastForward(7000);await expect(dialog(page)).toContainText('最长等待20秒');
 await page.clock.fastForward(10000);await expect(dialog(page).getByRole('alert')).toContainText('REPORT_TIMEOUT');await expect(dialog(page).locator('.ui-skeleton')).toHaveCount(0);await expect(dialog(page).getByRole('button',{name:'重新读取报告'})).toBeEnabled();
});

test('closing a pending report aborts it and a late result cannot replace another modal',async({page,request})=>{
 const project=await setup(page,request);let release,started=false;
 const gate=new Promise(resolve=>release=resolve);
 await page.route('**/api/v44/projects/*/jobs/report-job/report**',async route=>{started=true;await gate;await route.fulfill({json:report(project)}).catch(()=>{})});
 await open(page);await expect.poll(()=>started).toBe(true);await expect(dialog(page).locator('.ui-skeleton')).toBeVisible();
 await page.evaluate(()=>{window.closeModalCore424();window.modal('其他业务窗口','<p>保持当前业务窗口</p>')});release();
 await expect(page.getByRole('dialog',{name:'其他业务窗口',exact:true})).toContainText('保持当前业务窗口');await expect(page.locator('[data-report-job="report-job"]')).toHaveCount(0);
});

test('rapid report version changes fence the late response and bind charts to newest modal',async({page,request})=>{
 const project=await setup(page,request);let release,started=false;
 const gate=new Promise(resolve=>release=resolve);
 await page.route('**/api/v44/projects/*/jobs/report-job/report**',async route=>{const version=new URL(route.request().url()).searchParams.get('version_id');if(version==='version-a'){started=true;await gate}await route.fulfill({json:report(project,version)}).catch(()=>{})});
 await open(page);await expect.poll(()=>started).toBe(true);
 await page.evaluate(()=>{void window.trainingReportCore425('report-job',{algorithmId:'algorithm-a',versionId:'version-b'})});
 await expect(dialog(page).locator('[data-report-version="version-b"]')).toBeVisible();release();
 await expect(page.locator('[data-report-version="version-a"]')).toHaveCount(0);await expect(page.locator('[data-training-report-loading]')).not.toContainText('正在读取');
 await dialog(page).locator('[data-report-tab="curves"]').click();await expect(dialog(page).locator('[data-report-chart="accuracy"] canvas')).toHaveCount(1);
});
