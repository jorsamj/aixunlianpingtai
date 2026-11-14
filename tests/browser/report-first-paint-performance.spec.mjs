import {test, expect} from '@playwright/test';
import {writeFile} from 'node:fs/promises';

const quantile=(values,ratio)=>{
  const ordered=[...values].sort((a,b)=>a-b);
  return ordered[Math.max(0,Math.ceil(ordered.length*ratio)-1)];
};

test('single-version report defers hidden evidence and measures Chrome fixture P50/P95',async({page,request},testInfo)=>{
  test.setTimeout(120000);
  const created=await request.post('/api/projects',{data:{name:'report-paint-fixture-'+Date.now(),labels:[]}});
  expect(created.ok()).toBeTruthy();
  const project=(await created.json()).id;
  await page.route('**/api/v53/bootstrap/snapshot**',route=>{
    const url=new URL(route.request().url());
    url.searchParams.set('preferred_project_id',project);
    return route.fallback({url:url.toString()});
  });
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>state.uiReady&&state.project?.id),{timeout:20000}).toBe(project);
  const report={
    job:{id:'paint-job',status:'done'},
    report:{
      identity:{project_id:project,algorithm_id:'paint-algorithm',version_id:'paint-version',job_id:'paint-job'},
      metrics:{map50:.78,precision:.8,recall:.75},
      history:Array.from({length:500},(_,i)=>({epoch:i+1,map50:Math.min(.9,.3+i*.001),
        precision:Math.min(.94,.5+i*.0008),recall:Math.min(.9,.4+i*.0007),
        box_loss:1/(i+1),cls_loss:.5/(i+1),val_box_loss:.3/(i+1)})),
      inspection_marker:'TECHNICAL_EVIDENCE_ON_OPEN_ONLY',
      evaluation:{status:'not_requested'},
    },
  };
  await page.route('**/api/v44/projects/*/jobs/paint-job/report**',route=>route.fulfill({json:report}));
  const measurements=[];
  for(let iteration=0;iteration<20;iteration++){
    const row=await page.evaluate(async()=>{
      const started=performance.now();
      await window.trainingReportCore425('paint-job',{algorithmId:'paint-algorithm',versionId:'paint-version'});
      const committed=performance.now();
      const root=document.querySelector('[data-report-job="paint-job"]');
      if(!root)throw Error('report did not render');
      const lazyCurves=root.querySelector('[data-report-pane="curves"]');
      const technical=root.querySelector('[data-report-technical]');
      const resource=performance.getEntriesByType('resource').filter(item=>item.name.includes('/jobs/paint-job/report')).at(-1);
      await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
      return {domMs:committed-started,paintMs:performance.now()-started,
        httpMs:resource?.duration??null,responseToDomMs:resource?Math.max(0,committed-resource.responseEnd):null,
        deferredCharts:!!lazyCurves&&!lazyCurves.hasChildNodes(),
        deferredTechnical:!!technical&&technical.textContent==='',
      };
    });
    expect(row.deferredCharts).toBe(true);
    expect(row.deferredTechnical).toBe(true);
    measurements.push(row);
    if(iteration===19){
      await page.locator('[data-report-tab="curves"]').click();
      await expect(page.locator('[data-report-chart="accuracy"] canvas')).toHaveCount(1);
      await page.locator('[data-report-tab="provenance"]').click();
      const evidence=page.locator('[data-report-technical-details]');
      await evidence.locator('summary').click();
      await expect(evidence.locator('[data-report-technical]')).toContainText('TECHNICAL_EVIDENCE_ON_OPEN_ONLY');
    }
    await page.evaluate(()=>window.closeModalCore424());
    await expect(page.getByRole('dialog',{name:'训练报告',exact:true})).toHaveCount(0);
  }
  const record={scope:'isolated-Chrome-fixture-not-production-P95',epochs:500,samples:measurements.length,
    p50DomMs:quantile(measurements.map(row=>row.domMs),.50),
    p95DomMs:quantile(measurements.map(row=>row.domMs),.95),
    p50PaintMs:quantile(measurements.map(row=>row.paintMs),.50),
    p95PaintMs:quantile(measurements.map(row=>row.paintMs),.95),
    measurements,
  };
  const artifact=testInfo.outputPath('report-first-paint-fixture-measurements.json');
  await writeFile(artifact,JSON.stringify(record,null,2));
  await testInfo.attach('report-first-paint-fixture-measurements',{path:artifact,contentType:'application/json'});
  console.log('[version-report-fixture-P95]',JSON.stringify({
    scope:record.scope,samples:record.samples,p50DomMs:record.p50DomMs,
    p95DomMs:record.p95DomMs,p50PaintMs:record.p50PaintMs,p95PaintMs:record.p95PaintMs,
    p95HttpMs:quantile(measurements.map(row=>row.httpMs).filter(Number.isFinite),.95),
    p95PostHttpDomMs:quantile(measurements.map(row=>row.responseToDomMs).filter(Number.isFinite),.95),
  }));
  expect(record.p95PaintMs).toBeGreaterThanOrEqual(0);
});

test('algorithm report records isolated 40-version Chrome P50/P95 with deferred rows',async({page,request},testInfo)=>{
 test.setTimeout(120000);
 const project=(await (await request.post('/api/projects',{data:{name:'algorithm-report-paint-'+Date.now(),labels:[]}})).json()).id;
 await page.route('**/api/v53/bootstrap/snapshot**',route=>{const url=new URL(route.request().url());url.searchParams.set('preferred_project_id',project);return route.fallback({url:url.toString()})});
 await page.goto('/');await expect.poll(()=>page.evaluate(()=>state.uiReady&&state.project?.id),{timeout:20000}).toBe(project);
 const version_quality=Array.from({length:40},(_,i)=>({version_id:'v'+i,version_name:'第'+(i+1)+'版',
   val_map50:.4+i*.01,test_map50:.3+i*.01,test_status:'succeeded',is_current:i===39,
   finished_at:'2026-11-13T00:00:00Z'}));
 const payload={report_type:'algorithm',algorithm:{name:'综合报告隔离样本',version_count:40},
   summary:{current_version:'第40版',latest_accuracy:.79,successful_count:20,attempt_count:40,
     duration_record_count:40,total_duration_seconds:12000,label_counts_scope:'not_computed_fast'},
   best_map50:.79,best_version:'第40版',latest_vs_previous:{map50_delta:.01},
   version_quality,version_quality_total:40,current_quality:version_quality.at(-1),
   jobs:Array.from({length:20},(_,i)=>({job_id:'task-'+i,status:'SUCCEEDED',map50:.5,version:'v'+i})),
   jobs_total:40,jobs_truncated:true};
 await page.route('**/api/v49/projects/*/algorithms/paint-algorithm/report?lightweight=true',route=>route.fulfill({json:payload}));
 const measurements=[];
 for(let i=0;i<20;i++){
  const row=await page.evaluate(async()=>{
   const start=performance.now();await window.algorithmReport429('paint-algorithm');
   const dom=performance.now();const root=document.querySelector('[data-algorithm-report]');
   if(!root)throw new Error('algorithm report failed to mount');
   const pane=root.querySelector('[data-algorithm-report-pane="versions"]');
   const resource=performance.getEntriesByType('resource').filter(row=>row.name.includes('/algorithms/paint-algorithm/report')).at(-1);
   await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
   return {domMs:dom-start,paintMs:performance.now()-start,httpMs:resource?.duration??null,
     postHttpDomMs:resource?Math.max(0,dom-resource.responseEnd):null,
     deferredVersionRows:!!pane&&!pane.hasChildNodes()};
  });
  expect(row.deferredVersionRows).toBe(true);measurements.push(row);
  if(i===19){await page.locator('[data-algorithm-report-tab="versions"]').click();await expect(page.locator('.alg-report-table tbody tr')).toHaveCount(40)}
  await page.evaluate(()=>window.closeModalCore424());
  await expect(page.getByRole('dialog',{name:'算法综合训练报告',exact:true})).toHaveCount(0);
 }
 const record={scope:'40-version-isolated-browser-fixture-not-production',samples:measurements.length,
  p50DomMs:quantile(measurements.map(row=>row.domMs),.5),
  p95DomMs:quantile(measurements.map(row=>row.domMs),.95),
  p50PaintMs:quantile(measurements.map(row=>row.paintMs),.5),
  p95PaintMs:quantile(measurements.map(row=>row.paintMs),.95),
  measurements};
 const artifact=testInfo.outputPath('algorithm-report-paint-fixture-measurements.json');
 await writeFile(artifact,JSON.stringify(record,null,2));
 await testInfo.attach('algorithm-report-paint-fixture-measurements',{path:artifact,contentType:'application/json'});
 console.log('[algorithm-report-fixture-P95]',JSON.stringify({
  scope:record.scope,samples:record.samples,p50DomMs:record.p50DomMs,
  p95DomMs:record.p95DomMs,p50PaintMs:record.p50PaintMs,p95PaintMs:record.p95PaintMs,
  p95HttpMs:quantile(measurements.map(row=>row.httpMs).filter(Number.isFinite),.95),
  p95PostHttpDomMs:quantile(measurements.map(row=>row.postHttpDomMs).filter(Number.isFinite),.95),
 }));
});
