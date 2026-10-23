import {test, expect} from '@playwright/test';

test('existing storage page shows scoped known and unavailable usage with force recovery and late isolation',async({page},testInfo)=>{
  await page.addInitScript(()=>localStorage.removeItem('cl_v427_advanced'));
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>typeof state!=='undefined' && state.uiReady && Boolean(window.StorageCacheRuntime))).toBe(true);
  const pid=await page.evaluate(()=>state.project.id);
  let count=0,finished=0,mode='slow',release;
  await page.route(`**/api/v62/projects/${pid}/storage/lifecycle-summary`,async route=>{
    count++;
    if(mode==='slow' || mode==='late')await new Promise(resolve=>{release=resolve;});
    if(mode==='failure'){await route.fulfill({status:503,json:{detail:'快照暂不可用'}});finished++;return;}
    await route.fulfill({json:{ok:true,project_id:pid,sampled_at:'2026-10-23T02:00:00Z',metrics:{
      original_index_logical_bytes:{value:mode==='late'?987654321:1024,scope:'项目当前素材索引逻辑量'},
      gt_index_logical_bytes:{value:0,scope:'GT索引文件逻辑量'},
      thumbnail_cache_logical_bytes:{value:null,scope:'当前节点上次缓存采样'},
      shared_cache_logical_bytes:{value:2048,scope:'当前节点全部素材缓存'},
      worker_workspace_logical_bytes:{value:null},reclaimable_logical_bytes:{value:null},cleanup_pending_tasks:{value:null},cleanup_failed_tasks:{value:null},
    }}});finished++;
  });
  await page.locator('#nav .nav-advanced427 button').click();
  const storageNav=()=>page.locator('#nav .nav-btn').filter({has:page.locator('b',{hasText:/^存储配置$/})});
  await storageNav().click();
  const card=page.locator('#storageLifecycleStatus61'),button=card.locator('[data-storage-lifecycle-refresh]');
  await expect(card).toContainText('正在读取可核验');
  await expect(button).toBeDisabled();
  await page.evaluate(()=>{void window.StorageCacheRuntime.refresh();});
  await expect.poll(()=>count).toBe(1);
  release();
  const metric=key=>card.locator(`[data-storage-lifecycle-metric="${key}"] .v`);
  await expect(metric('original_index_logical_bytes')).toHaveText('1.00 KB');
  await expect(metric('gt_index_logical_bytes')).toHaveText('0 B');
  await expect(metric('thumbnail_cache_logical_bytes')).toHaveText('未获取');
  await expect(metric('worker_workspace_logical_bytes')).toHaveText('未获取');
  await expect(metric('cleanup_failed_tasks')).toHaveText('未获取');
  await expect(card).toContainText('逻辑量不代表物理占用、独占空间或实际释放量');
  await page.evaluate(()=>window.StorageCacheRuntime.refresh());
  expect(count).toBe(1);
  mode='failure';await button.click();
  await expect(card).toContainText('快照暂不可用');
  await expect(card).toContainText('刷新失败，显示上次采样');
  await expect(metric('original_index_logical_bytes')).toHaveText('1.00 KB');
  await expect(button).toBeEnabled();
  mode='known';await button.click();
  await expect(metric('original_index_logical_bytes')).toHaveText('1.00 KB');
  expect(count).toBe(3);
  await card.screenshot({path:testInfo.outputPath('storage-lifecycle-known-unknown.png')});
  mode='late';await button.click();
  await expect.poll(()=>count).toBe(4);
  await page.locator('#nav .nav-btn').filter({has:page.locator('b',{hasText:/^训练任务$/})}).click();
  await expect(page.locator('.train428-page')).toBeVisible();
  await expect(page.locator('#storageLifecycleStatus61')).toHaveCount(0);
  await storageNav().click();
  await expect(button).toBeEnabled();
  await expect(card).not.toContainText('正在读取');
  await expect(metric('original_index_logical_bytes')).toHaveText('1.00 KB');
  expect(count).toBe(4);
  release();
  await expect.poll(()=>finished).toBe(4);
  await expect(metric('original_index_logical_bytes')).toHaveText('1.00 KB');
  await expect(button).toBeEnabled();
  expect(errors).toEqual([]);
});
