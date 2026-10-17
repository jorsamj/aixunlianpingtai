import {test, expect} from '@playwright/test';
import path from 'node:path';

function diagnosticImage() {
  const width=100,height=80,stride=300,data=Buffer.alloc(54+stride*height,90);
  data.write('BM');data.writeUInt32LE(data.length,2);data.writeUInt32LE(54,10);
  data.writeUInt32LE(40,14);data.writeInt32LE(width,18);data.writeInt32LE(height,22);
  data.writeUInt16LE(1,26);data.writeUInt16LE(24,28);data.fill(0,30,54);
  return data;
}

test('frozen evaluation diagnoses zero-TP class and previews real GT/FP/FN layers', async ({page}) => {
  await page.route('**/evaluation/images/**', route => route.fulfill({
    status: 200, contentType: 'image/bmp', body: diagnosticImage()
  }));
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state?.uiReady && window.openVersionEvaluation429)), {timeout: 20000}).toBe(true);
  await page.evaluate(() => {
    state.algorithms = [{id: 'diagnostic-algo', name: '安全帽异常检测', versions: [{
      id: 'version-1', version_name: 'V1', evaluation: {
        status: 'succeeded', snapshot_id: 'a'.repeat(64), image_count: 283,
        protocol: {mode: 'blind_image_only_inference_then_hidden_ground_truth_scoring',
          operating_conf: 0.25, matching_iou: 0.5},
        error_sample_count: 205,
        metrics: {'metrics/mAP50(B)': 0.298, 'metrics/recall(B)': 0.272},
        per_class: [{class_id: 0, label: 'No_helmet', precision: 0, recall: 0, map50: 0.002,
          true_positive: 0, false_positive: 0, false_negative: 85, ground_truth_count: 85}],
        weak_labels: ['No_helmet'],
        error_samples: [
          {image: 'less-severe.jpg', fp_count: 1, fn_count: 0, fp_labels: ['helmet'], fn_labels: []},
          {image: 'highest-severity.jpg', fp_count: 1, fn_count: 85, fp_labels: ['helmet'], fn_labels: ['No_helmet'],
            image_width: 100, image_height: 80,
            gt_boxes: [{box: [10, 10, 40, 45], label: 'No_helmet', matched: false}],
            pred_boxes: [{box: [51, 10, 70, 30], label: 'helmet', matched: false, confidence: 0.8}]}
        ]
      },
      iteration_decision: {
        decision_id: 'b'.repeat(64), decision: 'review_required', requires_confirmation: true,
        critical_labels: ['No_helmet'], quality_gate: {metric: 'map50', stop_threshold: 0.9, metric_value: 0.298},
        reason_codes: ['critical_class_zero_true_positives'],
        recommended_actions: ['inspect_class_mapping', 'inspect_prediction_threshold', 'review_fp_fn_samples'],
        class_diagnostics: [{label: 'No_helmet', severity: 'critical',
          code: 'zero_true_positives', true_positive: 0, false_positive: 0, false_negative: 85, recall: 0,
          recommended_actions: ['inspect_class_mapping', 'inspect_prediction_threshold']}],
        signals: {false_positive: 88, false_negative: 249, error_sample_count: 205}
      }
    }]}];
    window.openVersionEvaluation429('diagnostic-algo', 'version-1');
  });
  const dialog = page.getByRole('dialog', {name: '独立评测'});
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('.evaluation429-diagnosis-grid')).toContainText('No_helmet');
  await expect(dialog.locator('.evaluation429-diagnosis-grid')).toContainText('关键类别未检出');
  await expect(dialog).toContainText('Conf ≥ 0.250');
  await expect(dialog).toContainText('IoU ≥ 0.500');
  await dialog.getByRole('tab', {name:'错误样本',exact:true}).click();
  await expect(dialog.locator('.evaluation429-gallery')).toContainText('共 205 张问题图片');
  await expect(dialog.locator('.evaluation429-image-card').first()).toContainText('highest-severity.jpg');
  await expect(dialog.locator('.evaluation429-thumb img')).toHaveCount(2);
  await expect(dialog.locator('.evaluation429-image-card').first())
    .toHaveAttribute('data-eval-url', /evaluation\/images\/highest-severity\.jpg$/);
  await expect(dialog.locator('.evaluation429-image-card').first().locator('.evaluation429-thumb img'))
    .toHaveAttribute('src', /^blob:/);
  await dialog.locator('.evaluation429-image-card').first().click();
  const preview = page.getByRole('dialog', {name: '问题图片核验'});
  await expect(preview).toBeVisible();
  await expect(preview.locator('.evaluation429-stage img')).toBeVisible();
  await expect(preview.locator('[data-layer="gt"]')).toHaveCount(1);
  await expect(preview.locator('[data-layer="pred"]')).toHaveCount(1);
  await preview.getByLabel('GT 真实框（红色漏检）').uncheck();
  await expect(preview.locator('[data-layer="gt"]')).toHaveCSS('display','none');
  await expect(preview.locator('[data-layer="pred"]')).not.toHaveCSS('display','none');
  await expect(preview).toContainText('不能直接加入训练集');
  await preview.getByRole('button', {name: '返回独立评测'}).click();
  await expect(page.getByRole('dialog', {name: '独立评测'})).toHaveCount(1);
  await expect(page.getByRole('dialog', {name: '问题图片核验'})).toHaveCount(0);
  await expect(page.getByRole('dialog', {name: '独立评测'})).toBeVisible();
  await page.getByRole('dialog', {name: '独立评测'}).getByLabel('问题图片排序').selectOption('fp');
  await expect(page.getByRole('dialog', {name: '独立评测'})).toHaveCount(1);
  await expect(page.getByRole('dialog', {name: '独立评测'}).locator('.evaluation429-image-card').first()).toContainText('highest-severity.jpg');
});

test('legacy error records never invent GT overlays or silently claim a preview exists', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state?.uiReady && window.openVersionEvaluation429)), {timeout: 20000}).toBe(true);
  await page.evaluate(() => {
    state.algorithms = [{id: 'legacy-a', name: '旧版模型', versions: [{
      id: 'legacy-v', version_name: '历史版本',
      evaluation: {status: 'succeeded', image_count: 2, error_samples: [{
        image: 'legacy-test.jpg', fp_count: 1, fn_count: 2
      }]}, iteration_decision: {}
    }]}];
    window.openVersionEvaluation429('legacy-a','legacy-v');
  });
  await expect(page.getByRole('dialog', {name: '独立评测'})).toContainText('Conf 未记录');
  await expect(page.getByRole('dialog', {name: '独立评测'})).toContainText('IoU 未记录');
  await page.getByRole('dialog', {name: '独立评测'}).getByRole('tab',{name:'错误样本',exact:true}).click();
  await page.getByRole('dialog', {name: '独立评测'}).locator('.evaluation429-image-card').first().click();
  const preview = page.getByRole('dialog', {name: '问题图片核验'});
  await expect(preview).toContainText('历史评测仅有 FP/FN 数量');
  await expect(preview.locator('.evaluation429-overlay')).toHaveCount(0);
  await preview.getByRole('button',{name:'返回独立评测'}).click();
  await page.getByRole('dialog',{name:'独立评测'}).getByRole('button',{name:'训练报告',exact:true}).click();
  const legacyReport=page.getByRole('dialog',{name:'版本训练报告'});
  await expect(legacyReport).toContainText('mAP50');
  await expect(legacyReport).not.toContainText('正确率');
  await expect(legacyReport).toContainText('未保存完整训练任务');
});


test('failed frozen-image preview hides stale GT and prediction overlays', async ({page}) => {
  await page.route('**/evaluation/images/**', route => route.fulfill({
    status: 409, contentType: 'text/plain', body: 'snapshot mismatch'
  }));
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state?.uiReady && window.openVersionEvaluation429)), {timeout: 20000}).toBe(true);
  await page.evaluate(() => {
    state.algorithms = [{id: 'guarded-algo', name: '安全帽', versions: [{
      id: 'guarded-version', evaluation: {status: 'succeeded', error_sample_count: 1,
        error_samples: [{image: 'drift.jpg', image_width: 100, image_height: 80,
          fp_count: 1, fn_count: 1,
          gt_boxes: [{box: [10, 10, 40, 40], label: 'No_helmet', matched: false}],
          pred_boxes: [{box: [60, 10, 90, 40], label: 'helmet', matched: false, confidence: 0.9}]}]},
      iteration_decision: {}
    }]}];
    window.openVersionEvaluation429('guarded-algo','guarded-version');
  });
  await page.getByRole('dialog', {name:'独立评测'}).getByRole('tab',{name:'错误样本',exact:true}).click();
  await page.getByRole('dialog', {name: '独立评测'}).locator('.evaluation429-image-card').first().click();
  const dialog = page.getByRole('dialog', {name: '问题图片核验'});
  await expect(dialog.locator('.evaluation429-image-error')).toBeVisible();
  await expect(dialog.locator('.evaluation429-overlay')).toBeHidden();
  await expect(dialog.locator('.evaluation429-media img')).toBeHidden();
});


test('gallery thumbnails share structured preview diagnostics and retry transient storage errors', async ({page}) => {
  let transientReads = 0;
  await page.route('**/evaluation/images/**', route => {
    if (route.request().url().includes('transient.webp')) {
      transientReads++;
      if (transientReads === 1) return route.fulfill({
        status: 503,
        contentType: 'application/json',
        body: JSON.stringify({detail: {
          code: 'STORAGE_UNAVAILABLE',
          message: 'storage unavailable',
          retryable: true,
          solution: '请稍后重试；持续失败时检查存储连接。',
        }}),
      });
      return route.fulfill({
        status: 200,
        contentType: 'image/bmp',
        headers: {
          'X-Evaluation-Image-Format': 'BMP',
          'X-Evaluation-Image-Width': '100',
          'X-Evaluation-Image-Height': '80',
          'X-Evaluation-Evidence-Source': 'bundle',
        },
        body: diagnosticImage(),
      });
    }
    return route.fulfill({
      status: 409,
      contentType: 'application/json',
      body: JSON.stringify({detail: {
        code: 'IMAGE_HASH_MISMATCH',
        message: 'hash mismatch',
        retryable: false,
        solution: '请恢复原始证据；无法恢复时需要重新评测。',
      }}),
    });
  });
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state?.uiReady && window.openVersionEvaluation429)), {timeout: 20000}).toBe(true);
  await page.evaluate(() => {
    const base = {
      image_width: 100, image_height: 80, fp_count: 1, fn_count: 2,
      fp_labels: ['helmet'], fn_labels: ['No_helmet'],
      gt_boxes: [{box: [10, 10, 40, 45], label: 'No_helmet', matched: false}],
      pred_boxes: [{box: [51, 10, 70, 30], label: 'helmet', matched: false, confidence: .8}],
    };
    state.algorithms = [{id: 'preview-diagnostics', name: '预览诊断', versions: [{
      id: 'v1', version_name: 'V1', iteration_decision: {}, evaluation: {
        status: 'succeeded', evaluation_id: 'd'.repeat(64), error_sample_count: 2,
        error_samples: [
          {...base, image: 'transient.webp', image_id: 'image-a'},
          {...base, image: 'drift.jpg', image_id: 'image-b'},
        ],
      },
    }]}];
    window.openVersionEvaluation429('preview-diagnostics', 'v1');
  });
  const dialog = page.getByRole('dialog', {name: '独立评测'});
  await dialog.getByRole('tab', {name: '错误样本', exact: true}).click();
  const transient = dialog.locator('.evaluation429-image-card').filter({hasText: 'transient.webp'});
  const permanent = dialog.locator('.evaluation429-image-card').filter({hasText: 'drift.jpg'});
  await expect(transient).toContainText('存储连接异常，可重试');
  await expect(transient.getByRole('button', {name: '重新加载'})).toBeVisible();
  await expect(permanent).toContainText('图片与评测时内容不一致');
  await expect(permanent.getByRole('button', {name: '重新加载'})).toBeHidden();
  await transient.getByRole('button', {name: '重新加载'}).click();
  await expect(transient.locator('img')).toBeVisible();
  await expect(transient.locator('[data-eval-thumb-status]')).toBeHidden();
  await expect(transient).toContainText('BMP · 100 × 80');
  await expect(transient).toContainText('GT No_helmet');
  await expect(transient).toContainText('预测 helmet');
  expect(transientReads).toBe(2);
});


test('hard sample action queues one canonical annotation task without pretending review succeeded', async ({page}) => {
  let posted = null;
  await page.route('**/hard-sample-mining/eligible?*', route => route.fulfill({
    status: 200, contentType: 'application/json',
    body: JSON.stringify({items:['train-eligible-a','train-eligible-b'],total:2,next_cursor:null})
  }));
  await page.route('**/hard-sample-mining', async route => {
    posted = route.request().postDataJSON();
    await route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({
      id:'hmtest-queued',status:'QUEUED',kind:'AI_ANNOTATION'
    })});
  });
  await page.goto('/');
  await expect.poll(() => page.evaluate(() => Boolean(state?.uiReady && window.openVersionEvaluation429)), {timeout:20000}).toBe(true);
  await page.evaluate(() => {
    state.algorithms=[{id:'a-mine',name:'人形检测',versions:[{id:'v-mine',version_name:'V2',
      evaluation:{status:'succeeded',metrics:{'metrics/mAP50(B)':0.5},error_samples:[]}}]}];
    window.openVersionEvaluation429('a-mine','v-mine');
  });
  await page.getByRole('dialog',{name:'独立评测'}).getByRole('button',{name:'挖掘已有未标注素材'}).click();
  await expect.poll(()=>Boolean(posted)).toBe(true);
  expect(posted).toEqual({image_ids:['train-eligible-a','train-eligible-b'],source:'existing'});
});

test('20k evaluation loads only 24 page previews and fences late images across versions', async ({page}) => {
  const requests=[];
  let releaseOld;
  const oldGate=new Promise(resolve=>{releaseOld=resolve;});
  await page.route('**/evaluation/images/**',async route=>{
    const url=route.request().url();requests.push(url);
    if(url.includes('/versions/old/'))await oldGate;
    await route.fulfill({status:200,contentType:'image/bmp',headers:{
      'X-Evaluation-Image-Format':url.includes('/versions/old/')?'OLD':'BMP',
      'X-Evaluation-Evidence-Source':'bundle',
    },body:diagnosticImage()}).catch(()=>{});
  });
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(state?.uiReady&&window.openVersionEvaluation429)),{timeout:20000}).toBe(true);
  await page.evaluate(()=>{
    const samples=Array.from({length:200},(_,i)=>({image:'same-'+i+'.bmp',image_id:'frozen-'+i,fp_count:1,fn_count:1,image_width:100,image_height:80}));
    state.algorithms=[{id:'page-fence',name:'隔离验收',versions:['old','new'].map(id=>({id,version_name:id,evaluation:{status:'succeeded',evaluation_id:id,image_count:20000,error_sample_count:20000,error_samples:samples}}))}];
    window.openVersionEvaluation429('page-fence','old');
  });
  expect(requests).toHaveLength(0);
  await page.getByRole('dialog',{name:'独立评测'}).getByRole('tab',{name:'错误样本',exact:true}).click();
  await expect.poll(()=>requests.length).toBe(24);
  await page.evaluate(async()=>{await closeModal();window.openVersionEvaluation429('page-fence','new');});
  const dialog=page.getByRole('dialog',{name:'独立评测'});
  await dialog.getByRole('tab',{name:'错误样本',exact:true}).click();
  await expect(dialog.locator('.evaluation429-thumb-ready')).toHaveCount(24);
  releaseOld();
  await expect.poll(()=>requests.length).toBe(48);
  await expect(dialog).not.toContainText('OLD');
  await expect(dialog.locator('.evaluation429-image-card').first()).toHaveAttribute('data-eval-url',/\/versions\/new\//);
  await expect(dialog).toContainText('共 20000 张问题图片');
  await expect(dialog.locator('[data-eval-preview-summary]')).toContainText('可预览 24');
});

test('quality workspaces preserve evidence, pagination, comparison and four responsive layouts', async ({page},testInfo) => {
  let comparisons=0;
  await page.route('**/evaluation/images/**',route=>route.fulfill({status:200,contentType:'image/bmp',body:diagnosticImage()}));
  await page.route('**/evaluation/compare/previous',route=>{
    comparisons++;
    return route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({comparison:{
      comparable:true,regressed_labels:['No_helmet'],
      metrics:{'metrics/mAP50(B)':{delta:.1},'metrics/recall(B)':{delta:0},'metrics/mAP50-95(B)':{delta:null}},
      classes:[{label:'No_helmet',metrics:{recall:{delta:-.1},map50:{delta:-.1},false_positive:{delta:2},false_negative:{delta:3}}}]
    }})});
  });
  await page.route('**/jobs/quality-visual/report',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
    job:{id:'quality-visual',task_status:'SUCCEEDED',completed_epochs:20,requested_epochs:100,
      completion_reason:'quality_target_reached',asset_algorithm_name:'本地验收 · 安全帽模型',auto_version_id:'current'},
    report:{generated_at:'2026-10-13T03:00:00Z',metrics:{'metrics/mAP50(B)':.75},
      history:Array.from({length:20},(_,i)=>({epoch:i+1,box_loss:1-i*.03,val_box_loss:.4+i*.01,map50:.4+i*.015})),
      quality_analysis:{best_observed_epoch:20},dataset_counts:{train:100,validation:25,test:26}}
  })}));
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>Boolean(state?.uiReady && window.openVersionEvaluation429)),{timeout:20000}).toBe(true);
  await page.evaluate(()=>{
    const error_samples=Array.from({length:26},(_,i)=>({image:'evidence-'+i+'.bmp',image_id:'frozen-'+i,image_content_sha256:'c'.repeat(64),
      fp_count:1,fn_count:1,fp_labels:['helmet'],fn_labels:['No_helmet'],image_width:100,image_height:80,
      gt_boxes:[{box:[10,10,40,45],label:'No_helmet',matched:false}],
      pred_boxes:[{box:[51,10,70,30],label:'helmet',matched:false,confidence:.8}]}));
    const evaluation={status:'succeeded',evaluation_id:'a'.repeat(64),image_count:26,error_sample_count:26,error_samples,
      protocol:{mode:'blind_image_only_inference_then_hidden_ground_truth_scoring',operating_conf:.25,matching_iou:.5},
      metrics:{'metrics/precision(B)':.5,'metrics/recall(B)':.4,'metrics/mAP50(B)':.75,'metrics/mAP50-95(B)':.5},
      per_class:[{class_id:0,label:'No_helmet',ground_truth_count:26,true_positive:0,false_positive:0,false_negative:26,precision:0,recall:0,map50:0},
        {class_id:1,label:'helmet',ground_truth_count:40,true_positive:32,false_positive:26,false_negative:8,precision:.55,recall:.8,map50:.8}],
      confusion_matrix:{protocol:'confidence_first_class_agnostic_iou_0.5',cells:[{actual:0,predicted:1,count:26,images:error_samples.map(s=>s.image)}]},
      confidence_curves:[{label:'helmet',points:Array.from({length:21},(_,i)=>({confidence:i/20,precision:i/20,recall:1-i/20,f1:2*(i/20)*(1-i/20)}))}]};
    state.algorithms=[{id:'quality-visual-a',name:'本地验收 · 安全帽模型',versions:[
      {id:'previous',version_name:'V1',evaluation},
      {id:'current',version_name:'V2',job_id:'quality-visual',evaluation}]}];
    window.openVersionEvaluation429('quality-visual-a','current');
    document.body.insertAdjacentHTML('beforeend','<div id="acceptance-fixture-badge" style="position:fixed;right:12px;bottom:12px;z-index:10000;padding:7px 11px;border-radius:8px;background:#7c2d12;color:white;font:700 12px system-ui">验收夹具 · 非生产数据</div>');
  });
  const dialog=page.getByRole('dialog',{name:'独立评测'});
  await dialog.getByRole('button',{name:'场景算法实测'}).click();
  await expect.poll(()=>page.evaluate(()=>({page:state.page,tab:state.qualityCenterTab411}))).toEqual({page:'质量中心',tab:'detect'});
  await expect(page.locator('.quality411-tabs').getByRole('button',{name:'场景算法实测'})).toBeVisible();
  await page.evaluate(()=>window.openVersionEvaluation429('quality-visual-a','current'));
  await dialog.getByRole('tab',{name:'错误样本',exact:true}).click();
  await expect(dialog.locator('.evaluation429-image-card')).toHaveCount(24);
  await dialog.getByRole('button',{name:'下一页',exact:true}).click();
  await expect(dialog.locator('.evaluation429-image-card')).toHaveCount(2);
  await dialog.getByLabel('错误类型').selectOption('fn');
  await expect(dialog.locator('.evaluation429-image-card')).toHaveCount(24);
  await dialog.getByRole('tab',{name:'类别与混淆'}).click();
  await dialog.locator('.quality-matrix').getByRole('button',{name:'26',exact:true}).click();
  await expect(dialog.getByRole('tab',{name:'错误样本',exact:true})).toHaveAttribute('aria-selected','true');
  await dialog.getByRole('tab',{name:'Confidence 分析'}).click();
  await expect(dialog.locator('.quality-chart')).toHaveCount(4);
  await dialog.getByRole('tab',{name:'版本对比'}).click();
  await expect.poll(()=>comparisons).toBe(1);
  await expect(dialog.locator('[data-eval-comparison]')).toContainText('存在退化类别');
  await expect(dialog.locator('[data-eval-comparison]')).toContainText('0.0 pp');
  await expect(dialog.locator('[data-eval-comparison]')).toContainText('未记录');
  await page.setViewportSize({width:1366,height:768});
  await page.screenshot({path:path.resolve(process.env.CODEX_VISUAL_EVIDENCE_DIR||testInfo.outputPath('visuals'),'comparison-1366.png')});
  await dialog.getByRole('button',{name:'并排核验同一图片'}).click();
  const pair=page.getByRole('dialog',{name:'问题图片核验'});
  await expect(pair.locator('.evaluation429-stage img')).toHaveCount(2);
  await expect(pair.locator('.evaluation429-stage img').first()).toBeVisible();
  await expect(pair.locator('.evaluation429-stage img').last()).toBeVisible();
  await expect(pair.getByRole('button',{name:'单独全屏'})).toHaveCount(2);
  await pair.getByRole('button',{name:'同步放大 / 适配'}).click();
  await expect.poll(()=>pair.locator('.evaluation429-media').evaluateAll(nodes=>nodes.map(node=>node.dataset.zoom))).toEqual(['2','2']);
  await pair.getByRole('button',{name:'恢复比例'}).click();
  await expect.poll(()=>pair.locator('.evaluation429-media').evaluateAll(nodes=>nodes.map(node=>node.dataset.zoom))).toEqual(['1','1']);
  await pair.getByRole('button',{name:'返回独立评测'}).click();
  for(const [width,height] of [[1920,1080],[1440,900],[1366,768],[375,812]]){
    await page.setViewportSize({width,height});
    await dialog.getByRole('tab',{name:'质量总览'}).click();
    await expect(dialog).toBeVisible();
    expect(await dialog.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
    const screenshotPath=path.resolve(process.env.CODEX_VISUAL_EVIDENCE_DIR||testInfo.outputPath('visuals'),'evaluation-'+width+'.png');
    await page.screenshot({path:screenshotPath});
    await dialog.getByRole('tab',{name:'错误样本',exact:true}).click();
    await expect(dialog.locator('.evaluation429-thumb-ready')).toHaveCount(24);
    await page.screenshot({path:path.resolve(path.dirname(screenshotPath),'gallery-'+width+'.png')});
    await dialog.locator('.evaluation429-image-card').first().click();
    const preview=page.getByRole('dialog',{name:'问题图片核验'});
    await expect(preview.locator('.evaluation429-stage img')).toBeVisible();
    const geometry=await preview.evaluate(el=>{
      const image=el.querySelector('.evaluation429-stage img').getBoundingClientRect();
      const rect=el.querySelector('svg rect');
      const box=rect.getBBox(),mapped=new DOMPoint(box.x,box.y).matrixTransform(rect.getScreenCTM());
      const scale=Math.min(image.width/100,image.height/80);
      return {x:mapped.x,y:mapped.y,expectedX:image.left+(image.width-100*scale)/2+10*scale,
        expectedY:image.top+(image.height-80*scale)/2+10*scale,overflow:el.scrollWidth>el.clientWidth+1};
    });
    expect(geometry.x).toBeCloseTo(geometry.expectedX,0);
    expect(geometry.y).toBeCloseTo(geometry.expectedY,0);
    expect(geometry.overflow,JSON.stringify(await preview.evaluate(el=>Array.from(el.querySelectorAll('*')).filter(node=>node.scrollWidth>node.clientWidth+1).map(node=>({tag:node.tagName,cls:node.className,width:node.clientWidth,scroll:node.scrollWidth}))))).toBe(false);
    await preview.locator('.modal-body').evaluate(el=>{el.scrollTop=0;});
    await expect(preview.getByRole('button',{name:'同步放大 / 适配'})).toBeInViewport();
    await page.screenshot({path:path.resolve(path.dirname(screenshotPath),'image-'+width+'.png')});
    await preview.getByRole('button',{name:'下一张',exact:true}).click();
    await expect(preview.locator('.evaluation429-stage img')).toBeVisible();
    await preview.getByRole('button',{name:'返回独立评测'}).click();
    await dialog.getByRole('button',{name:'训练报告',exact:true}).click();
    const report=page.getByRole('dialog',{name:'训练报告'});
    await expect(report.locator('.quality-chart')).toHaveCount(3);
    await expect(page.getByRole('dialog')).toHaveCount(1);
    expect(await report.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBe(true);
    await page.screenshot({path:path.resolve(path.dirname(screenshotPath),'report-'+width+'.png')});
    await report.getByRole('button',{name:'场景算法实测'}).click();
    await expect.poll(()=>page.evaluate(()=>({page:state.page,tab:state.qualityCenterTab411}))).toEqual({page:'质量中心',tab:'detect'});
    await expect(page.locator('.quality411-tabs').getByRole('button',{name:'场景算法实测'})).toBeVisible();
    await page.evaluate(()=>window.openVersionEvaluation429('quality-visual-a','current'));
    await page.getByRole('dialog',{name:'独立评测'}).getByRole('tab',{name:'质量总览'}).click();
  }
});
