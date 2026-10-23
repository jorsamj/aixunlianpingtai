import {test, expect} from '@playwright/test';

test('advanced legacy compatibility keeps preview identity through retry and fences late responses',async({page},testInfo)=>{
  const errors=[],calls=[];let scanCount=0,applyCount=0,releaseScan,releasePreview,releaseApply;
  page.on('pageerror',error=>errors.push(error.message));
  page.on('dialog',dialog=>dialog.accept());
  await page.addInitScript(()=>localStorage.removeItem('cl_v427_advanced'));
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>typeof state !== 'undefined' && state.uiReady)).toBe(true);
  const pid=await page.evaluate(()=>state.project.id),fingerprint='f'.repeat(64);
  await page.route(`**/api/v62/projects/${encodeURIComponent(pid)}/legacy-material-compatibility/**`,async route=>{
    const request=route.request(),url=new URL(request.url());
    calls.push({method:request.method(),path:url.pathname,query:url.search,body:request.method()==='POST'?request.postDataJSON():null});
    if(url.pathname.endsWith('/scan')){
      scanCount++;
      await new Promise(resolve=>{releaseScan=resolve;});
      await route.fulfill({json:{items:scanCount===1?[
        {image_id:'already-normal',status:'normal',candidate:false,issues:[]},
        {image_id:'missing-metadata',status:'candidate',candidate:true,issues:['缺失索引']},
        {image_id:'unsupported-source',status:'unsupported',candidate:false,issues:['只读来源']},
        {image_id:'conflicting-source',status:'conflict',candidate:false,issues:['内容冲突']},
      ]:[{image_id:'LATE_RESPONSE_MUST_STAY_HIDDEN',status:'candidate',candidate:true}],next_cursor:null}});
    }else if(url.pathname.endsWith('/preview')){
      await new Promise(resolve=>{releasePreview=resolve;});
      await route.fulfill({json:{fingerprint,image_ids:['missing-metadata'],needs_migration:true}});
    }else if(url.pathname.endsWith('/apply')){
      applyCount++;
      if(applyCount===1){
        await new Promise(resolve=>{releaseApply=resolve;});
        await route.fulfill({status:503,json:{detail:'临时失败，可安全重试'}});
      }else await route.fulfill({json:{ok:true,status:'applied'}});
    }
  });
  await page.locator('#nav .nav-advanced427 button').click();
  await page.locator('#nav .nav-btn').filter({has:page.locator('b',{hasText:/^旧素材兼容迁移$/})}).click();
  const status=page.locator('[data-compat-status]'),scan=page.locator('[data-compat-scan]'),preview=page.locator('[data-compat-preview]'),apply=page.locator('[data-compat-apply]');
  await expect(page.locator('#view').getByRole('heading',{name:'旧素材兼容迁移',exact:true})).toBeVisible();
  await scan.click();
  await expect(status).toContainText('正在只读检查');
  await expect(scan).toBeDisabled();
  await scan.evaluate(node=>node.onclick());
  await expect.poll(()=>scanCount).toBe(1);
  releaseScan();
  await expect(status).toContainText('1 条需要预览');
  await expect(page.locator('[data-compat-results]')).toContainText('unsupported');
  await expect(page.locator('[data-compat-results]')).toContainText('conflict');
  expect(calls[0].method).toBe('GET');
  expect(calls[0].query).toContain('limit=50');
  await preview.click();
  await expect(status).toContainText('正在核对');
  await expect(preview).toBeDisabled();
  await expect.poll(()=>Boolean(releasePreview)).toBe(true);
  expect(calls.find(row=>row.path.endsWith('/preview')).body).toEqual({image_ids:['missing-metadata']});
  releasePreview();
  await expect(status).toContainText('影响预览已就绪');
  await apply.click();
  await expect(status).toContainText('正在备份并迁移');
  await expect(apply).toBeDisabled();
  await apply.evaluate(node=>node.onclick());
  await expect.poll(()=>applyCount).toBe(1);
  releaseApply();
  await expect(status).toContainText('临时失败');
  await apply.click();
  await expect(status).toContainText('本批元数据处理完成');
  const mutations=calls.filter(row=>row.path.endsWith('/apply'));
  expect(mutations).toHaveLength(2);
  expect(mutations[0].body).toEqual(mutations[1].body);
  expect(mutations[1].body).toMatchObject({image_ids:['missing-metadata'],expected_fingerprint:fingerprint,confirm:'migrate_legacy_material_metadata'});
  expect(mutations[1].body.task_id).toMatch(/^legacy-metadata-/);
  await expect(apply).toBeDisabled();
  await apply.evaluate(node=>node.onclick());
  expect(applyCount).toBe(2);
  await page.locator('#view .panel').screenshot({path:testInfo.outputPath('legacy-compatibility-applied.png')});
  await scan.click();
  await expect.poll(()=>scanCount).toBe(2);
  await expect(status).toContainText('正在只读检查');
  await page.locator('#nav .nav-btn').filter({has:page.locator('b',{hasText:/^训练任务$/})}).click();
  releaseScan();
  await expect(page.locator('.train428-page')).toBeVisible();
  await expect(page.locator('#view')).not.toContainText('LATE_RESPONSE_MUST_STAY_HIDDEN');
  await expect(page.locator('[data-compat-status]')).toHaveCount(0);
  expect(errors).toEqual([]);
});
