import {test, expect} from '@playwright/test';

test('three overview tabs preserve production owner, render scoped facts and fail closed on telemetry', async ({page}) => {
  const pageErrors=[];
  page.on('pageerror',error=>pageErrors.push(error.message));
  await page.setViewportSize({width:1366,height:768});
  const algorithms=[
    {id:'overview-smoke',name:'消防烟雾',algorithm_type:'yolo_ultralytics',industry:'消防',versions:[{id:'v1'}]},
    {id:'overview-guard',name:'人员闯入',algorithm_type:'yolo_ultralytics',industry:'安防',versions:[]},
  ];
  const nodes=[
    {node_id:'center-1',display_name:'中央 GPU 节点',placement:'center',status:'ONLINE',online:true,
      resources:{cpu:{usage_percent:87},memory:{usage_percent:35,total_bytes:100,used_bytes:35},
        disk:{usage_percent:20,total_bytes:100,used_bytes:20},
        gpu:{gpus:[{index:0,uuid:'gpu-1',name:'NVIDIA A800',utilization_percent:8,
          memory_total_bytes:1000,memory_used_bytes:100}]}}},
    {node_id:'edge-1',display_name:'边缘离线节点',placement:'edge',status:'OFFLINE',online:false,
      resources:{cpu:{usage_percent:100},gpu:{gpus:[{uuid:'stale'}]}}},
  ];
  let failNodes=false;
  let algorithmGets=0;
  await page.route(/\/api\/v12\/projects\/[^/]+\/algorithms(?:\?.*)?$/,async route=>{
    algorithmGets++;
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,items:algorithms})});
  });
  await page.route(/\/api\/v42\/projects\/[^/]+\/quality-overview(?:\?.*)?$/,async route=>{
    await route.fulfill({status:200,contentType:'application/json',
      body:JSON.stringify({ok:true,algorithms:[{id:'overview-smoke',metrics:{precision:0.9,recall:0.8,map50:0.88}}],datasets:[]})});
  });
  await page.route(/\/api\/v63\/service-nodes(?:\?.*)?$/,async route=>{
    await route.fulfill({status:failNodes?503:200,contentType:'application/json',
      body:JSON.stringify(failNodes?{detail:'temporarily unavailable'}:{items:nodes,supported_capabilities:[]})});
  });
  await page.route(/\/api\/v62\/gpu-runtime(?:\?.*)?$/,async route=>{
    await route.fulfill({status:200,contentType:'application/json',
      body:JSON.stringify({gpus:[{node_id:'center-1',gpu_uuid:'gpu-1',metrics_fresh:true,
        telemetry_available:true,free_bytes:900}],telemetry:{fresh_gpu_count:1}})});
  });
  await page.route(/\/api\/v63\/service-nodes\/controller-snapshot$/,async route=>{
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({name:'控制端（本机）',sampled_at:new Date().toISOString(),resources:{cpu:{usage_percent:12},memory:{usage_percent:22},disk:{usage_percent:33},gpu:{gpus:[]}}})});
  });
  await page.route(/\/api\/v61\/storage-sources(?:\?.*)?$/,async route=>{
    await route.fulfill({status:200,contentType:'application/json',
      body:JSON.stringify({items:[{type:'local'},{type:'oss'}]})});
  });

  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(state.uiReady)),{timeout:20000}).toBe(true);
  await page.evaluate(()=>window.setPage('总览'));
  const tabs=page.locator('[data-overview-tabs]');
  await expect(tabs.getByRole('tab')).toHaveCount(2);
  await expect(tabs.getByRole('tab',{name:'算法一张图'})).toHaveAttribute('aria-selected','true');
  await expect(page.locator('#view')).toContainText('算法生产总览');
  await expect(page.getByRole('button',{name:'消防烟雾'}).first()).toBeVisible();
  await expect(page.locator('.ov348-stat').filter({hasText:'算法总数'})).toContainText('2');
  await expect(page.locator('.ov348-stat').filter({hasText:'有版本算法'})).toContainText('1');
  await expect(page.locator('.ov348-accuracy').first()).toContainText('88.0%');
  await expect(page.locator('#view')).toContainText('尚未接入生产推理调用次数');
  expect(algorithmGets).toBeGreaterThan(0);

  await tabs.getByRole('tab',{name:'算力一张图'}).click();
  await expect(page.locator('#view')).toContainText('控制端 · 本机资源');
  await expect(page.locator('.ov348-gpu')).toContainText('NVIDIA A800');
  await expect(page.locator('.ov348-stat').filter({hasText:'候选空闲 GPU'})).toContainText('—');
  await expect(page.locator('.ov348-node')).toHaveCount(2);
  await expect(page.locator('.ov348-node').last()).toContainText('非在线节点');
  await expect(page.locator('.ov348-panel').filter({hasText:'资源风险节点占比'})).toContainText('2 / 2');
  await page.locator('[data-overview-placement="edge"]').click();
  await expect(page.locator('.ov348-node')).toHaveCount(1);
  await expect(page.locator('.ov348-node')).toContainText('边缘离线节点');
  await page.locator('[data-overview-placement="all"]').click();
  await expect(page.locator('.ov348-node')).toHaveCount(2);

  await page.setViewportSize({width:1920,height:1080});
  await expect(tabs.getByRole('tab',{name:'算力一张图'})).toBeVisible();
  await page.setViewportSize({width:1366,height:768});
  await expect(tabs.getByRole('tab',{name:'算力一张图'})).toBeVisible();

  // Triple-click is a UI-only presentation mode; real telemetry is restored when exiting.
  await tabs.getByRole('tab',{name:'算力一张图'}).click();
  await tabs.getByRole('tab',{name:'算力一张图'}).click();
  await tabs.getByRole('tab',{name:'算力一张图'}).click();
  await expect(page.locator('[data-overview-demo="true"]')).toBeVisible();
  await expect(page.locator('.ov348-node')).toHaveCount(3);
  await expect(page.locator('#view')).toContainText('GPU 训练服务器 A');
  await page.locator('[data-overview-demo-exit]').click();
  await expect(page.locator('[data-overview-demo]')).toHaveCount(0);
  await expect(page.locator('.ov348-node')).toHaveCount(2);
  failNodes=true;
  await page.locator('[data-overview-refresh]').click();
  await expect(page.locator('.ov348-error')).toContainText('nodes: HTTP 503');
  await expect(page.locator('.ov348-node')).toHaveCount(0);
  await tabs.getByRole('tab',{name:'算法一张图'}).click();
  await expect(tabs.getByRole('tab',{name:'算法一张图'})).toHaveAttribute('aria-selected','true');
  await expect(page.locator('#view')).toContainText('算法生产总览');
  expect(pageErrors).toEqual([]);
});
