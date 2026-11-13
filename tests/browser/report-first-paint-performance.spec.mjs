import {test, expect} from '@playwright/test';

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
  for(let iteration=0;iteration<8;iteration++){
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
    if(iteration===7){
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
  await testInfo.attach('report-first-paint-fixture-measurements.json',{
    body:JSON.stringify(record,null,2),contentType:'application/json',
  });
  expect(record.p95PaintMs).toBeGreaterThanOrEqual(0);
});
