import {test,expect} from '@playwright/test';

async function setup(page,request){
  const created=await (await request.post('/api/projects',{data:{name:`综合报告隔离-${Date.now()}`,labels:[]}})).json();
  await page.route('**/api/v53/bootstrap/snapshot**',async route=>{
    const url=new URL(route.request().url());
    url.searchParams.set('preferred_project_id',created.id);
    await route.fallback({url:String(url)});
  });
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>state.project?.id),{timeout:20000}).toBe(created.id);
  await expect.poll(()=>page.evaluate(()=>typeof window.algorithmReport429==='function'&&Boolean(window.PlatformCore?.reports?.algorithmReportHtml))).toBe(true);
  return created.id;
}
function fixture(){
  const quality=Array.from({length:40},(_,i)=>({
    version_id:`v${i+1}`,version_name:`第${i+1}版`,val_map50:.3+i*.01,
    test_map50:.25+i*.01,test_status:'succeeded',test_snapshot_id:'a'.repeat(64),
    is_current:i===39,finished_at:'2026-11-12T12:00:00Z',
  }));
  const jobs=Array.from({length:20},(_,i)=>({
    job_id:`train_fake_${i}`,version:`第${i+1}版`,map50:.5,status:'SUCCEEDED',
    finished_at:'2026-11-12T12:00:00Z',
  }));
  return {
    ok:true,algorithm:{name:'隔离算法综合报告',industry:'视频分析',version_count:40},
    summary:{current_version:'第40版',latest_accuracy:.69,successful_count:20,attempt_count:24,
      duration_record_count:20,total_duration_seconds:3600,label_counts:{},label_counts_scope:'not_computed_fast'},
    best_map50:.69,best_version:'第40版',latest_vs_previous:{map50_delta:.01},
    version_quality:quality,version_quality_total:40,version_quality_truncated:false,
    current_quality:quality.at(-1),jobs,jobs_total:24,jobs_truncated:true,
  };
}
const dialog=page=>page.getByRole('dialog',{name:'算法综合训练报告',exact:true}).last();

test('algorithm overview stays stable while lazy tabs scroll on desktop and narrow screens',async({page,request})=>{
  await setup(page,request);
  let hits=0;
  await page.route('**/api/v49/projects/*/algorithms/alg-report-test/report?lightweight=true',route=>{
    hits++;return route.fulfill({json:fixture()});
  });
  for(const viewport of [{width:1366,height:768},{width:390,height:844}]){
    await page.setViewportSize(viewport);
    await page.evaluate(()=>{void window.algorithmReport429('alg-report-test')});
    await expect(dialog(page).locator('[data-algorithm-report]')).toBeVisible();
    await expect(dialog(page).getByText('69.0%').first()).toBeVisible();
    await expect(dialog(page).locator('[data-algorithm-report-pane="versions"]')).toBeHidden();
    const card=dialog(page).locator('.modal-card'),body=dialog(page).locator('.modal-body');
    const height=await card.evaluate(el=>el.getBoundingClientRect().height);
    for(const tab of ['versions','data','jobs','overview']){
      await dialog(page).locator(`[data-algorithm-report-tab="${tab}"]`).click();
      const current=await card.evaluate(el=>el.getBoundingClientRect().height);
      expect(Math.abs(height-current)).toBeLessThan(2);
      const bounds=await card.evaluate(el=>{const r=el.getBoundingClientRect();return{top:r.top,bottom:r.bottom}});
      expect(bounds.top).toBeGreaterThanOrEqual(-2);
      expect(bounds.bottom).toBeLessThanOrEqual(viewport.height+2);
    }
    await dialog(page).locator('[data-algorithm-report-tab="versions"]').click();
    await expect(dialog(page).locator('.alg-report-table tbody tr')).toHaveCount(40);
    await body.evaluate(node=>node.scrollTop=220);
    expect(await body.evaluate(node=>node.scrollTop)).toBeGreaterThan(0);
    await page.evaluate(()=>window.closeModalCore424());
    await expect(dialog(page)).toHaveCount(0);
  }
  expect(hits).toBe(2);
});

test('generic long dialogs retain an internal scroll area after re-opening',async({page,request})=>{
  await setup(page,request);
  for(let index=0;index<3;index++){
    await page.evaluate(()=>window.modal('滚动隔离测试','<section style="height:2300px">较长正文</section>',true));
    const d=page.getByRole('dialog',{name:'滚动隔离测试'}).last();
    await expect(d).toBeVisible();
    const body=d.locator('.modal-body');
    expect(await body.evaluate(node=>node.scrollHeight>node.clientHeight)).toBe(true);
    await body.evaluate(node=>node.scrollTop=300);
    expect(await body.evaluate(node=>node.scrollTop)).toBeGreaterThan(0);
    await page.evaluate(()=>window.closeModalCore424());
    await expect(d).toHaveCount(0);
  }
});

test('closed report ignores late response instead of reopening or replacing a different modal',async({page,request})=>{
  await setup(page,request);
  let release,started=false;
  const delayed=new Promise(resolve=>{release=resolve});
  await page.route('**/api/v49/projects/*/algorithms/alg-report-test/report?lightweight=true',async route=>{
    started=true;await delayed;await route.fulfill({json:fixture()});
  });
  await page.evaluate(()=>{void window.algorithmReport429('alg-report-test')});
  await expect.poll(()=>started).toBe(true);
  await expect(dialog(page).locator('[data-algorithm-report-loading]')).toBeVisible();
  await page.evaluate(()=>window.closeModalCore424());
  await page.evaluate(()=>window.modal('其他任务窗口','<p>保留当前窗口内容</p>',false));
  release();
  await expect(page.getByRole('dialog',{name:'其他任务窗口'})).toContainText('保留当前窗口内容');
  await expect(dialog(page)).toHaveCount(0);
  await expect(page.locator('[data-algorithm-report]')).toHaveCount(0);
});
