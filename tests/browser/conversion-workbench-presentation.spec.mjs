import {test,expect} from '@playwright/test';

test('conversion history keeps server counts and filters while switching to same-layer details',async ({page})=>{
  await page.goto('about:blank');
  await page.setContent(`<!doctype html><html><body><div id="modal" role="dialog">
    <div class="modal-body"><div class="convert428-v2">
    <div class="convert428-top"><b>版本转换</b><small>v1 / best.pt</small></div>
    <div class="convert428-summary">
      <div><span>筛选结果总数</span><b>25</b></div>
      <div><span>本页进行中</span><b>1</b></div>
      <div><span>本页已产生产物</span><b>0</b></div>
    </div>
    <form class="convert428-history-filters">
      <select name="status" aria-label="状态"><option value="">全部</option><option value="running">执行中</option><option value="done">已完成</option><option value="failed">失败</option><option value="waiting_resource">等待资源</option></select>
      <button type="submit">查询</button>
    </form>
    <div class="convert428-job-list">
      <article class="convert428-job" data-conversion-job-id="c1" data-conversion-status="done">
        <header><div class="convert428-job-title"><b>算能 BMODEL</b></div></header>
        <div class="convert428-job-meta"><span>BM1688</span><span>FP16</span></div>
        <div class="convert428-actions"><button type="button" class="btn">下载产物</button><button type="button" class="btn danger">删除</button></div>
        <details class="convert428-job-details"><summary>完整配置</summary><div>产物 SHA256 · 实际 SDK 记录</div></details>
      </article>
      <article class="convert428-job" data-conversion-job-id="c2" data-conversion-status="running">
        <header><div class="convert428-job-title"><b>ONNX</b></div></header>
        <div class="convert428-job-meta"><span>640×640</span></div>
        <div class="convert428-actions"><button type="button" class="btn">停止</button></div>
        <details class="convert428-job-details"><summary>完整配置</summary><div>正在执行</div></details>
      </article>
    </div>
    </div></div></body></html>`);
  await page.evaluate(()=>{
    document.querySelector('form').addEventListener('submit',event=>{
      event.preventDefault();
      window.lastStatus=new FormData(event.target).get('status');
    });
  });
  await page.addStyleTag({path:'static/conversion-workbench.css'});
  await page.addScriptTag({path:'static/modules/conversion-workbench-ui.js'});
  await expect(page.locator('.conversion560-status-strip strong').first()).toHaveText('25');
  await expect(page.locator('.conversion560-job')).toHaveCount(2);
  await page.getByRole('button',{name:'执行中'}).click();
  await expect.poll(()=>page.evaluate(()=>window.lastStatus)).toBe('running');
  await expect(page.locator('select[name=status]')).toHaveValue('running');
  await expect(page.locator('.conversion560-status-strip strong').first()).toHaveText('25');
  await page.getByRole('button',{name:'查看详情'}).first().click();
  await expect(page.locator('.conversion560-history')).toHaveClass(/conversion-ui-inspecting/);
  await expect(page.locator('.conversion-ui-inspected .convert428-job-details')).toHaveAttribute('open','');
  await expect(page.locator('.conversion560-job').nth(1)).toBeHidden();
  await page.getByRole('button',{name:'返回转换记录'}).click();
  await expect(page.locator('.conversion560-job').nth(1)).toBeVisible();
  await page.locator('.conversion-ui-more summary').first().click();
  await expect(page.getByRole('button',{name:'删除'})).toBeVisible();
});

test('conversion editor keeps target-required fields visible outside advanced settings',async ({page})=>{
  await page.goto('about:blank');
  await page.setContent(`<!doctype html><html><body><form class="convert428-create">
    <section><b>源信息</b><div class="convert428-source"><strong>best.pt</strong></div></section>
    <section><b>格式</b><div class="convert428-targets"><label><input type="radio" name="conv428Target" value="onnx" checked><b>ONNX</b></label></div></section>
    <section><b>厂商</b></section>
    <section><b>转换配置</b>
      <div class="form"><input id="conv428Input" value="640"><select id="conv428Precision"><option value="fp16">FP16</option></select></div>
      <div id="conv428OnnxFields"><input id="conv428Opset" value="12"></div>
      <div id="conv428Calibration"><input value="校准素材"></div>
      <div id="conv428SophonFields">Sophon</div>
      <div id="conv428TensorRtFields">TensorRT</div>
      <div class="convert428-csc">CSC 适配参数</div>
    </section>
    <div class="row end"><button type="button" data-convert-submit onclick="submitConvert428('a','v')">开始转换</button></div>
    </form></body></html>`);
  await page.addStyleTag({path:'static/conversion-workbench.css'});
  await page.addScriptTag({path:'static/modules/conversion-workbench-ui.js'});
  await expect(page.locator('.conversion560-main')).toBeVisible();
  await expect(page.locator('.conversion560-aside')).toBeVisible();
  await expect(page.locator('#conversion560Target')).toHaveText('ONNX');
  await expect(page.locator('#conv428OnnxFields')).toBeVisible();
  await expect(page.locator('#conv428Calibration')).toBeVisible();
  await expect(page.locator('.conversion560-advanced #conv428Calibration')).toHaveCount(0);
  await expect(page.locator('.conversion560-advanced .convert428-csc')).toHaveCount(1);
});

test('unrelated DOM churn does not rescan conversion roots; async conversion DOM still decorates',async ({page})=>{
  await page.goto('about:blank');
  await page.setContent('<!doctype html><html><body><div id="unrelated"></div><div id="late"></div></body></html>');
  await page.evaluate(()=>{
    const original=document.querySelectorAll.bind(document);
    window.__conversionDocumentScans=0;
    document.querySelectorAll=selectors=>{
      if(String(selectors).startsWith('.convert428-v2:not('))window.__conversionDocumentScans++;
      return original(selectors);
    };
  });
  await page.addScriptTag({path:'static/modules/conversion-workbench-ui.js'});
  await page.evaluate(()=>new Promise(resolve=>setTimeout(resolve,0)));
  const before=await page.evaluate(()=>window.__conversionDocumentScans);
  await page.evaluate(async ()=>{
    const box=document.getElementById('unrelated');
    for(let i=0;i<30;i++){
      const node=document.createElement('span');node.textContent='material '+i;box.append(node);
      await new Promise(resolve=>setTimeout(resolve,0));
    }
  });
  const after=await page.evaluate(()=>window.__conversionDocumentScans);
  console.log('[13C-04F-02] unrelated DOM mutations=30, conversion global scans='+String(after-before));
  expect(after-before).toBe(0);
  await page.evaluate(()=>{
    document.getElementById('late').insertAdjacentHTML('beforeend',`<div class="convert428-v2">
      <div class="convert428-top">转换记录</div>
      <div class="convert428-summary"><div><span>筛选结果总数</span><b>1</b></div></div>
      <form class="convert428-history-filters"><select name="status"><option value="">全部</option><option value="done">已完成</option></select></form>
      <div class="convert428-job-list"><div class="convert428-job"><div class="convert428-job-title"><b>ONNX</b></div><div class="convert428-actions"><button>下载</button></div><details class="convert428-job-details"><summary>配置</summary></details></div></div>
    </div>`);
  });
  await expect(page.locator('.conversion560-history .conversion-ui-open')).toHaveCount(1);
  await page.evaluate(()=>{
    document.getElementById('late').insertAdjacentHTML('beforeend',`<form class="convert428-create">
      <section><b>源模型</b><div class="convert428-source"><strong>best.pt</strong></div></section>
      <section><b>格式</b><div class="convert428-targets"><label><input type="radio" name="conv428Target" value="onnx" checked><b>ONNX</b></label></div></section>
      <section><b>厂商</b></section><section><b>设置</b><div class="form"><input id="conv428Input" value="640"></div></section>
    </form>`);
  });
  await expect(page.locator('.convert428-create .conversion560-aside')).toHaveCount(1);
  await page.evaluate(()=>document.querySelector('.convert428-create').insertAdjacentHTML('afterbegin','<div id="conv428SourceLoad">正在读取模型源</div>'));
  await expect(page.locator('.convert428-create .conversion560-main #conv428SourceLoad')).toHaveCount(1);
});
