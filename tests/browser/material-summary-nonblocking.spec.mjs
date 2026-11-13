import {test,expect} from '@playwright/test';

test('material pages and filtered search complete while 200k-scope status summary is pending',async({page,request})=>{
  test.setTimeout(60000);
  const added=await request.post('/api/projects',{data:{name:'slow-material-summary-'+Date.now(),labels:[]}});
  expect(added.ok()).toBeTruthy();
  const project=(await added.json()).id;
  let releaseCounts;
  const summaryGate=new Promise(resolve=>{releaseCounts=resolve});
  let countsRequests=0;
  const pageRequests=[];
  await page.route('**/api/v53/bootstrap/snapshot**',route=>{
    const url=new URL(route.request().url());
    url.searchParams.set('preferred_project_id',project);
    return route.fallback({url:String(url)});
  });
  await page.route('**/api/v61/projects/*/materials**',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname.endsWith('/status-counts')){
      countsRequests++;
      await summaryGate;
      return route.fulfill({json:{total:200000,processed:160000,unprocessed:40000,annotated:100000,boxes:120000,revision:4}});
    }
    if(url.pathname.endsWith('/materials')){
      const number=Number(url.searchParams.get('page')||1);
      const term=url.searchParams.get('query')||'';
      pageRequests.push({number,term});
      const imageId=term?'needle-match':number===2?'page-two':'page-one';
      return route.fulfill({json:{
        items:[{id:imageId,filename:imageId+'.jpg',processing_status:'processed',
          storage_source_id:'default_local',created_at:'2026-11-13T00:00:00Z',labels:[],annotated:false,box_count:0}],
        page:number,page_size:48,total:term?1:200000,total_pages:term?1:4167,
        has_previous:number>1,has_next:!term,next_cursor:null,
      }});
    }
    return route.fallback();
  });
  try{
    await page.goto('/');
    await expect.poll(()=>page.evaluate(()=>state.uiReady&&state.project?.id),{timeout:20000}).toBe(project);
    await page.evaluate(()=>{
      state.data412Tab='processed';state.materialQuery61='';state.materialAnnotated61='all';
      window.setPage('数据集');
    });
    await expect(page.locator('#data412Grid')).toContainText('page-one.jpg');
    await expect.poll(()=>countsRequests).toBeGreaterThan(0);
    // Old code did not settle this state until the pending global count finished.
    await expect.poll(()=>page.evaluate(()=>window.MaterialPaginationRuntime61.state().pageReadPending),{timeout:3500}).toBe(false);
    await page.evaluate(()=>window.materialNext61());
    await expect(page.locator('#data412Grid')).toContainText('page-two.jpg');
    await expect.poll(()=>page.evaluate(()=>window.MaterialPaginationRuntime61.state().pageReadPending),{timeout:3500}).toBe(false);
    await page.locator('#data412Q').fill('needle');
    await expect(page.locator('#data412Grid')).toContainText('needle-match.jpg');
    await expect.poll(()=>page.evaluate(()=>window.MaterialPaginationRuntime61.state().pageReadPending),{timeout:3500}).toBe(false);
    expect(pageRequests.some(row=>row.number===2)).toBe(true);
    expect(pageRequests.some(row=>row.term==='needle')).toBe(true);
    expect(await page.locator('.data412-card').count()).toBeLessThanOrEqual(48);
  }finally{
    releaseCounts();
  }
  await expect.poll(()=>page.evaluate(()=>state.materialPage61.statusCountsAvailable),{timeout:10000}).toBe(true);
  expect(await page.evaluate(()=>state.materialPage61.processedTotal)).toBe(160000);
  expect(await page.evaluate(()=>state.materialPage61.unprocessedTotal)).toBe(40000);
});
