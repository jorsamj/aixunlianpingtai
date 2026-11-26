import {expect,test} from '@playwright/test';
import {resolve} from 'node:path';

test('native report preserves task origin, pages history, and reads frozen evaluation',async({page})=>{
  const version='/api/v12/projects/p/algorithms/a/versions/v/evaluation';
  const digest='a'.repeat(64);
  const image=version+'/images/frame.png?expected_evaluation_id=e&expected_image_id=i&expected_sha256='+digest;
  const paths:string[]=[];
  const reportBase={ok:true,project_id:'p',job_id:'t',algorithm_id:'a',version_id:'v',state:'AVAILABLE',
    val_metrics:{map50:0,map50_95:.4},test_metrics:{},test_status:'not_generated',
    configuration:{workers:4},actual_parameters:{workers:0},historical_parameters:{batch:16},
    result:{status:'FAILED',best_epoch:1,completed_epochs:2,completion_reason:'recorded_failure'}};
  await page.route('**/app/**',route=>{
    const path=new URL(route.request().url()).pathname.slice(5)||'index.html';
    return route.fulfill({path:resolve('../static/vue-app',path),contentType:path.endsWith('.js')?'text/javascript':path.endsWith('.css')?'text/css':'text/html'});
  });
  await page.route('**/api/**',route=>{
    const url=new URL(route.request().url()),path=url.pathname;
    paths.push(path);
    expect(route.request().method()).toBe('GET');
    if(path==='/api/auth/session')return route.fulfill({json:{authenticated:true}});
    if(path==='/api/projects')return route.fulfill({json:[{id:'p',name:'项目 P'}]});
    if(path==='/api/v12/projects/p/algorithms')return route.fulfill({json:{ok:true,project_id:'p',items:[{id:'a',name:'A'}],total:1,page:1,page_size:10}});
    if(path==='/api/v12/projects/p/algorithms/a')return route.fulfill({json:{ok:true,project_id:'p',algorithm_id:'a',
      algorithm:{id:'a',name:'A'},version:{id:'v',algorithm_id:'a',training_job_id:'t',has_evaluation:true},artifacts:{items:[]},
      items:[{id:'previous',algorithm_id:'a',version_name:'历史版本'}],total:21,page:Number(url.searchParams.get('page')||1),page_size:20}});
    if(path==='/api/v62/projects/p/tasks')return route.fulfill({json:{ok:true,project_id:'p',items:[{task_id:'t',project_id:'p',report_job_id:'t',kind:'TRAINING',status:'FAILED'}],filter_options:{status:['FAILED']}}});
    if(path.includes('/jobs/')&&path.endsWith('/report')){
      const offset=Number(url.searchParams.get('history_offset'));
      expect(url.searchParams.get('reader_view')).toBe('true');
      expect(url.searchParams.get('history_limit')).toBe('100');
      if(url.searchParams.has('version_id'))expect([url.searchParams.get('algorithm_id'),url.searchParams.get('version_id')]).toEqual(['a','v']);
      return route.fulfill({json:{...reportBase,job_id:path.includes('/wrong/')?'another':'t',history_offset:offset,history_total:101,history_has_next:offset===0,history:[{epoch:offset+1,map50:.5,box_loss:.2,val_box_loss:.3}]}});
    }
    const identity={ok:true,project_id:'p',algorithm_id:'a',version_id:'v',evaluation_id:'e',state:'AVAILABLE'};
    if(path===version+'/report')return route.fulfill({json:{...identity,evaluation:{evaluation_id:'e',status:'succeeded',metrics:{map50:.62},benchmark_scope:{scope_id:'scope-frozen'},per_class:[{class_id:0,label:'烟雾',false_negative:1}]}}});
    if(path===version+'/compare/previous')return route.fulfill({json:{...identity,comparison:{current_version_id:'v',source_version_id:'previous',
      comparable:false,reason_codes:['benchmark_scope_mismatch'],metrics:{map50:{delta:0.99}}}}});
    if(path===version+'/samples'){
      expect(url.searchParams.get('limit')).toBe('20');
      return route.fulfill({json:{...identity,filter_evidence_complete:url.searchParams.get('issue')!=='low_confidence',diagnostic_low_confidence_threshold:.5,items:[{image_id:'i',filename:'frame.png',image_content_sha256:digest,preview_url:image,image_width:1,image_height:1,gt_boxes:[{label:'烟雾',box:[0,0,1,1],matched:false}],pred_boxes:[{label:'烟雾',box:[0,0,.5,.5],matched:false,confidence:.23}]},
        {image_id:'bad',filename:'unsafe.png',image_content_sha256:digest,preview_url:'/api/materials/unsafe.png'}]}});
    }
    if(path===version+'/images/frame.png')return route.fulfill({contentType:'image/png',body:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+nmZcAAAAASUVORK5CYII=','base64')});
    return route.fulfill({status:404,json:{detail:'unexpected fixture route'}});
  });

  await page.goto('/app/#/projects/p/training/tasks?query=needle&status=FAILED');
  await page.getByRole('link',{name:'训练报告',exact:true}).click();
  await expect(page.getByRole('heading',{name:'报告已记录'})).toBeVisible();
  await expect(page.getByText('recorded_failure',{exact:true})).toBeVisible();
  await expect(page.getByRole('heading',{name:'独立 Test 指标'}).locator('..')).toContainText('未提供');
  for(const [label,value] of [['请求配置','4'],['实际执行参数','0'],['历史参数（来源未标注）','16']]){
    await expect(page.getByRole('heading',{name:label,exact:true}).locator('xpath=following-sibling::dl[1]').locator('dd')).toHaveText(value);
  }
  await page.getByRole('button',{name:'训练过程'}).click();
  await expect(page.getByRole('img',{name:'Val 指标（原记录数值）'}).locator('canvas')).toBeVisible();
  await page.getByRole('button',{name:'下一页 Epoch'}).click();
  await expect(page.getByText('偏移 100 / 101')).toBeVisible();
  await page.getByRole('button',{name:'独立评测',exact:true}).click();
  await expect(page.locator('.native-report-charts canvas')).toHaveCount(0);
  await expect(page.getByText('scope-frozen',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'TP / FP / FN 样本'}).click();
  await expect(page.getByRole('img',{name:'frame.png'})).toHaveAttribute('src',image);
  await expect(page.getByText('冻结图片未提供或读取失败',{exact:true})).toBeVisible();
  await page.getByRole('button',{name:'查看框级诊断'}).click();
  const diagnosis=page.getByRole('list',{name:'框级诊断'});
  await expect(diagnosis).toContainText('GT · 烟雾 · 漏检');
  await expect(diagnosis).toContainText('预测 · 烟雾 · 误检 · 23.0%');
  await page.getByRole('checkbox',{name:'正式 GT（实线）'}).uncheck();
  await expect(diagnosis).not.toContainText('GT · 烟雾 · 漏检');
  const diagnostics=page.waitForRequest(request=>request.url().includes('/samples?')&&new URL(request.url()).searchParams.get('issue')==='low_confidence');
  await page.getByLabel('样本类型').selectOption('low_confidence');
  await diagnostics;
  await expect(page.getByText('置信度阈值 0.5')).toBeVisible();
  expect(paths).not.toContain('/api/materials/unsafe.png');
  await expect(page.getByRole('button',{name:'困难样本与继续训练',exact:true})).toBeVisible();
  await expect(page.getByRole('link',{name:'原高级评测',exact:true})).toHaveAttribute('href',/algorithm_id=a&version_id=v&action=evaluation&expected_evaluation_id=e/);
  await page.getByRole('button',{name:'版本对比',exact:true}).click();
  await page.getByRole('combobox',{name:'对照版本'}).selectOption('previous');
  await page.getByRole('button',{name:'读取对比',exact:true}).click();
  await expect(page.getByText('原评测合同判定不可比',{exact:true})).toBeVisible();
  await expect(page.getByText('benchmark_scope_mismatch')).toBeVisible();
  await expect(page.getByText('0.99',{exact:true})).toHaveCount(0);
  await page.reload();
  await expect(page.getByText('scope-frozen',{exact:true})).toBeVisible();
  await page.getByRole('link',{name:'返回来源'}).click();
  await expect(page).toHaveURL(/training\/tasks\?query=needle&status=FAILED$/);
  await page.goto('/app/#/projects/p/training/reports/wrong');
  await expect(page.getByText('报告身份不一致',{exact:true})).toBeVisible();
  const source='/projects/p/algorithms?algorithm=a&version=v&version_page=2&query=smoke';
  await page.goto('/app/#/projects/p/algorithms/a/versions/v/report?back='+encodeURIComponent(source));
  await expect(page.getByRole('heading',{name:'报告已记录'})).toBeVisible();
  await page.getByRole('button',{name:'独立评测',exact:true}).click();
  await expect(page.getByText('scope-frozen',{exact:true})).toBeVisible();
  const href=await page.getByRole('link',{name:/继续训练.*LEGACY_BRIDGE/}).getAttribute('href');
  expect(new URL(href!,'https://app.example.test').searchParams.get('return_to')).toBe(source);
  await page.getByRole('link',{name:'返回来源'}).click();
  await expect(page).toHaveURL('/app/#'+source);
  await expect(page.getByRole('dialog',{name:'模型版本详情'})).toBeVisible();
});
