import {test, expect} from '@playwright/test';

test('changlian data page never auto-loads and manual refresh shows remote products versions weights and download links', async ({page}) => {
  let providerReads = 0;
  await page.route('**/api/v63/external-algorithm-platform/provider/products*', async route => {
    providerReads += 1;
    const url = new URL(route.request().url());
    const status = url.searchParams.get('status');
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        ok: true,
        response: {code: 0, data: status === '1' ? [{
          productId: 'p-db-1',
          productName: '畅联云抽烟检测',
          productCode: 'SMOKE-001',
          categoryName: '行为分析',
          productType: 3,
          status: 1,
        }] : []},
      }),
    });
  });
  await page.route('**/api/v63/external-algorithm-platform/provider/versions/by-product/p-db-1', async route => {
    providerReads += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, response: {code: 0, data: [{
        algoVersionId: 'v-db-1',
        versionName: '20260924',
        versionNo: '1.0.0',
        analysisId: 'analysis-1',
        status: 1,
      }]}}),
    });
  });
  await page.route('**/api/v63/external-algorithm-platform/provider/weights/by-version/v-db-1', async route => {
    providerReads += 1;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ok: true, response: {code: 0, data: [{
        weightId: 'w-db-1',
        computePlatformId: 'rk3568',
        chipCode: 'rk3568',
        fileName: 'smoke-v1.rknn',
        filePath: 'https://download.example.test/smoke-v1.rknn',
      }]}}),
    });
  });

  await page.goto('/');
  await expect(page.locator('#title')).toBeVisible({timeout: 15_000});
  await expect(page.getByRole('button', {name: /展开高级功能|收起高级功能/})).toBeVisible();
  const advanced = page.getByRole('button', {name: '展开高级功能', exact: true});
  if (await advanced.count()) await advanced.click();
  await page.getByRole('button', {name: /畅联云数据/}).click();

  await expect(page.locator('[data-changlian-data-browser="1"]')).toBeVisible();
  await expect(page.getByText('页面不会自动读取远端数据库。')).toBeVisible();
  await page.waitForTimeout(250);
  expect(providerReads).toBe(0);

  await page.locator('[data-cldb-refresh]').click();
  await expect(page.getByText('畅联云抽烟检测', {exact: true})).toBeVisible();
  await page.getByText('畅联云抽烟检测', {exact: true}).click();
  await expect(page.getByText('20260924', {exact: true})).toBeVisible();
  await expect(page.getByText('smoke-v1.rknn', {exact: true})).toBeVisible();
  await expect(page.getByRole('link', {name: '下载 / 打开'})).toHaveAttribute('href', 'https://download.example.test/smoke-v1.rknn');
  expect(providerReads).toBe(4);
  expect(await page.locator('[data-changlian-data-browser="1"]').count()).toBe(1);
});


test('Weight detail shows all remote fields and paginated Tags without preloading or nested dialogs',async({page})=>{
  const productId='2102998777790074880',versionId='2109729657292197888',weightId='2112456166616469504',secondId='2112374852420767744',reads=[];
  const detail={weightId,productId,analysisId:'2000200697139826688',algoVersionId:versionId,versionName:'车辆检测版本',versionNo:'V1',computePlatformId:'2112437908475613184',computePlatformName:'算能 BM1684X',computePlatformCode:'sophon-bm1684x',chipCode:'BM1684X',fileName:'best_bm1684x_fp32.bmodel',filePath:'https://download.example.test/'+('long-path/'.repeat(20))+'model.bmodel',imageWidth:640,imageHeight:384,yoloVersion:'YOLOv11n',fileSize:1048576,fileSha256:'a'.repeat(64),remark:'<img src=x onerror="window.detailXss=1">',createBy:'admin',createTime:'2026-10-21 08:12:30',updateBy:'operator',updateTime:'2026-10-21 09:12:30',delFlag:0,futureField:{mode:'remote'}};
  await page.route('**/api/v63/external-algorithm-platform/provider/**',async route=>{
    const u=new URL(route.request().url());reads.push(u.pathname+u.search);let data;
    if(u.pathname.endsWith('/products'))data=u.searchParams.get('status')==='1'?[{productId,productName:'车辆检测'}]:[];
    else if(u.pathname.includes('/versions/by-product/'))data=[{algoVersionId:versionId,versionName:'车辆检测版本',versionNo:'V1'}];
    else if(u.pathname.includes('/weights/by-version/'))data=[detail,{weightId:secondId,fileName:'second.rknn'}];
    else if(u.pathname.endsWith('/weights/'+weightId))data=detail;
    else if(u.pathname.endsWith('/weights/'+secondId))data={...detail,weightId:secondId,fileName:'second.rknn',tags:[]};
    else if(u.pathname.endsWith('/weights/page')){expect(u.searchParams.get('withTags')).toBe('true');expect(u.searchParams.get('algoVersionId')).toBe(versionId);data=[{weightId,algoVersionId:versionId,productId,tags:['Car']}];}
    else throw new Error(u.pathname);
    await route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,response:{code:200,data,total:Array.isArray(data)?data.length:undefined}})});
  });
  await page.goto('/');await expect(page.locator('#title')).toBeVisible({timeout:15000});
  await expect(page.getByRole('button',{name:/展开高级功能|收起高级功能/})).toBeVisible();
  const advanced=page.getByRole('button',{name:'展开高级功能',exact:true});if(await advanced.count())await advanced.click();
  await page.getByRole('button',{name:/畅联云数据/}).click();expect(reads.length).toBe(0);
  await page.locator('[data-cldb-refresh]').click();await page.getByText('车辆检测',{exact:true}).click();
  expect(reads.filter(x=>/weights\/\d/.test(x)).length).toBe(0);
  await page.locator(`[data-cldb-weight="${weightId}"]`).click();const panel=page.locator('[data-cldb-detail]');
  await expect(panel.locator('[data-tags-state="returned"]')).toContainText('已从新畅联接口读取');
  await expect(panel.locator('.cldb-tags>span')).toHaveText(['Car']);
  await expect(panel.locator('[data-field]')).toHaveCount(24);
  for(const key of Object.keys(detail).filter(k=>k!=='futureField'))if(key!=='tags')await expect(panel.locator(`[data-field="${key}"] dd`)).toContainText(String(detail[key]));
  await expect(panel.locator('[data-field="fileSize"]')).toContainText('1 MB');
  await page.evaluate(()=>Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{window.copiedWeightDetail=value}}}));
  await panel.locator('[data-cldb-copy="fileSha256"]').click();expect(await page.evaluate(()=>window.copiedWeightDetail)).toBe('a'.repeat(64));
  await panel.locator('[data-cldb-copy="filePath"]').click();expect(await page.evaluate(()=>window.copiedWeightDetail)).toBe(detail.filePath);
  await expect(panel.locator('.cldb-dimensions')).toContainText('640 × 384');
  expect(await page.evaluate(()=>window.detailXss)).toBeUndefined();
  await panel.getByText('完整原始数据',{exact:true}).click();await expect(panel.locator('pre')).toContainText('futureField');
  for(const width of [1440,1366]){await page.setViewportSize({width,height:768});expect(await panel.evaluate(e=>e.scrollWidth<=e.clientWidth+1)).toBe(true);}
  await page.screenshot({path:'test-results/changlian-weight-details.png'});
  await panel.evaluate(e=>{for(let p=e.parentElement;p;p=p.parentElement)p.scrollTop=0});
  await page.screenshot({path:'test-results/changlian-weight-details-top.png'});
  await panel.locator('[data-cldb-close]').click();await expect(panel).toHaveCount(0);await expect(page.locator('.cldb-product[open]')).toHaveCount(1);
  await page.locator(`[data-cldb-weight="${weightId}"]`).click();await expect(panel.locator('.cldb-tags')).toContainText('Car');
  expect(reads.filter(x=>x.endsWith('/weights/'+weightId)).length).toBe(1);
  await page.locator(`[data-cldb-weight="${secondId}"]`).evaluate(e=>e.click());await expect(panel.locator('[data-tags-state="empty"]')).toBeVisible();await expect(panel).toHaveCount(1);
  await panel.locator('[data-cldb-close]').click();await page.locator('[data-cldb-refresh]').click();await expect(page.locator('[data-cldb-refresh]')).toBeEnabled();
  await page.getByText('车辆检测',{exact:true}).click();await page.locator(`[data-cldb-weight="${weightId}"]`).click();await expect(panel.locator('.cldb-tags')).toContainText('Car');
  expect(reads.filter(x=>x.endsWith('/weights/'+weightId)).length).toBe(2);
});


test('Weight detail keeps null missing failure and late results distinct through close and retry',async({page})=>{
  let delayed,failed=false;const ids=['101','102','103','104','105'];
  await page.route('**/api/v63/external-algorithm-platform/provider/**',async route=>{
    const u=new URL(route.request().url());let data;
    if(u.pathname.endsWith('/products'))data=u.searchParams.get('status')==='1'?[{productId:'11',productName:'详情状态验收'}]:[];
    else if(u.pathname.includes('/versions/by-product/'))data=[{algoVersionId:'22',versionName:'V1'}];
    else if(u.pathname.includes('/weights/by-version/'))data=ids.map(weightId=>({weightId,fileName:weightId+'.bmodel'}));
    else if(u.pathname.endsWith('/weights/page'))data=[{weightId:'102',algoVersionId:'22'}];
    else if(u.pathname.endsWith('/weights/101'))data={weightId:'101',algoVersionId:'22',tags:null};
    else if(u.pathname.endsWith('/weights/102'))data={weightId:'102',algoVersionId:'22'};
    else if(u.pathname.endsWith('/weights/103')){
      if(!failed){failed=true;await route.fulfill({status:502,contentType:'application/json',body:JSON.stringify({ok:false,message:'远端 Token expired'})});return}data=null;
    }else if(u.pathname.endsWith('/weights/104')){await new Promise(r=>delayed=r);data={weightId:'104',tags:['late']};}
    else data={weightId:'105',tags:['Car']};
    await route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,response:{code:200,data,total:Array.isArray(data)?data.length:undefined}})});
  });
  await page.goto('/');await expect(page.locator('#title')).toBeVisible({timeout:15000});
  await expect(page.getByRole('button',{name:/展开高级功能|收起高级功能/})).toBeVisible();
  const advanced=page.getByRole('button',{name:'展开高级功能',exact:true});if(await advanced.count())await advanced.click();await page.getByRole('button',{name:/畅联云数据/}).click();
  await page.locator('[data-cldb-refresh]').click();await page.getByText('详情状态验收',{exact:true}).click();const panel=page.locator('[data-cldb-detail]');
  await page.locator('[data-cldb-weight="101"]').click();await expect(panel.locator('[data-tags-state="null"]')).toBeVisible();await panel.locator('[data-cldb-close]').click();
  await page.locator('[data-cldb-weight="102"]').click();await expect(panel.locator('[data-tags-state="missing"]')).toBeVisible();await expect(panel).toContainText('本次接口未返回 Tags');await panel.locator('[data-cldb-close]').click();
  await page.locator('[data-cldb-weight="103"]').click();await expect(panel.locator('[role="alert"]')).toContainText('Token expired');await panel.locator('[data-cldb-retry]').click();await expect(panel).toContainText('data=null');await panel.locator('[data-cldb-close]').click();
  await page.locator('[data-cldb-weight="104"]').click();await expect(panel.locator('[role="status"]')).toBeVisible();await expect.poll(()=>typeof delayed).toBe('function');
  await panel.locator('[data-cldb-close]').click();await page.locator('[data-cldb-weight="105"]').click();await expect(panel.locator('.cldb-tags')).toContainText('Car');delayed();await expect(panel.locator('.cldb-tags')).toHaveText('Car');
  await panel.locator('[data-cldb-close]').click();await page.getByRole('button',{name:/部署资源/}).click();await expect(panel).toHaveCount(0);await page.getByRole('button',{name:/畅联云数据/}).click();await expect(page.locator('.cldb-product')).toBeVisible();
});
