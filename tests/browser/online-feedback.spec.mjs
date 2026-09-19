import {test, expect} from '@playwright/test';

function bmp(width=96,height=72){
  const rowBytes=Math.ceil(width*3/4)*4;
  const buffer=Buffer.alloc(54+rowBytes*height);
  buffer.write('BM',0,'ascii');buffer.writeUInt32LE(buffer.length,2);buffer.writeUInt32LE(54,10);
  buffer.writeUInt32LE(40,14);buffer.writeInt32LE(width,18);buffer.writeInt32LE(height,22);
  buffer.writeUInt16LE(1,26);buffer.writeUInt16LE(24,28);buffer.writeUInt32LE(rowBytes*height,34);
  buffer.fill(100,54);return buffer;
}

test('formal version prediction enters reviewed online feedback without automatic retraining', async ({page,request})=>{
  const project=await (await request.post('/api/projects',{data:{
    name:`线上反馈浏览器-${Date.now()}`,labels:['smoke'],
  }})).json();
  const encoded=encodeURIComponent(project.id);
  const requests=[];
  page.on('request',req=>requests.push(req.url()));

  await page.route('**/api/v16/inference_envs',route=>route.fulfill({
    status:200,contentType:'application/json',
    body:JSON.stringify({items:[{
      id:'feedback-env',name:'抽检环境',framework:'ultralytics',status:'ready',
      python_path:'/opt/yolo/bin/python',
    }]}),
  }));
  await page.route(`**/api/v12/projects/${encoded}/test_models*`,route=>route.fulfill({
    status:200,contentType:'application/json',
    body:JSON.stringify({ok:true,items:[{
      label:'算法版本：烟雾识别 / 20260919130000（当前）',
      model_name:'best.pt',model_source:'algorithm_version',framework:'ultralytics',
      algorithm_id:'algo-feedback',version_id:'version-feedback',is_current_version:true,
      path:'/models/best.pt',
    }]}),
  }));
  await page.route(`**/api/v12/projects/${encoded}/predict`,async route=>{
    await route.fulfill({
      status:200,contentType:'application/json',
      body:JSON.stringify({
        ok:true,prediction_id:'prediction-feedback-1',feedback_eligible:true,
        algorithm_id:'algo-feedback',version_id:'version-feedback',
        model_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),
        detections:[{class_id:0,label:'smoke',confidence:.91,x1:10,y1:8,x2:60,y2:50}],
        image_url:`/data/projects/${project.id}/predictions/prediction-feedback-1_result.jpg`,
        elapsed_ms:12.3,engine:'ultralytics',python_path:'/opt/yolo/bin/python',
      }),
    });
  });

  let staged=null,confirmed=null,feedbackStatus='pending_review';
  await page.route(`**/api/v63/projects/${encoded}/online-feedback?*`,route=>route.fulfill({
    status:200,contentType:'application/json',
    body:JSON.stringify({ok:true,items:staged?[{
      ...staged,status:feedbackStatus,
      result:feedbackStatus==='confirmed'?{
        annotation_action:'manual_annotation_required',needs_manual_annotation:true,dataset_id:'default',
      }:{},
      source:{detection_count:1},
    }]:[]}),
  }));
  await page.route(`**/api/v63/projects/${encoded}/online-feedback`,async route=>{
    if(route.request().method()!=='POST')return route.continue();
    const body=route.request().postDataJSON();
    staged={
      schema_version:1,id:'feedback-1',prediction_id:body.prediction_id,
      status:'pending_review',feedback_type:body.feedback_type,
      algorithm_id:'algo-feedback',version_id:'version-feedback',
      model_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),material_id:'',
      created_at:'2026-09-19T05:00:00Z',confirmed_at:'',note:body.note||'',
    };
    await route.fulfill({status:201,contentType:'application/json',
      body:JSON.stringify({ok:true,idempotent:false,feedback:staged})});
  });
  await page.route(`**/api/v63/projects/${encoded}/online-feedback/feedback-1`,async route=>{
    if(route.request().method()!=='GET')return route.continue();
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      ok:true,feedback:{
        ...staged,
        source:{
          schema_version:1,prediction_id:'prediction-feedback-1',
          algorithm_id:'algo-feedback',version_id:'version-feedback',
          model_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),
          original_filename:'camera.jpg',width:96,height:72,confidence:.25,engine:'ultralytics',
          detections:[{index:0,class_id:0,label:'smoke',confidence:.91,x1:10,y1:8,x2:60,y2:50}],
        },
        input_image_url:`/data/projects/${project.id}/predictions/prediction-feedback-1_input.jpg`,
        result_image_url:`/data/projects/${project.id}/predictions/prediction-feedback-1_result.jpg`,
        result:{},
      },
    })});
  });
  await page.route(`**/api/v63/projects/${encoded}/online-feedback/feedback-1/confirm`,async route=>{
    confirmed=route.request().postDataJSON();
    feedbackStatus='confirmed';
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      ok:true,idempotent:false,feedback:{
        ...staged,status:'confirmed',material_id:'material-feedback-1',
        result:{annotation_action:'manual_annotation_required',needs_manual_annotation:true,dataset_id:'default'},
      },
    })});
  });

  await page.addInitScript(projectId=>{
    localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({projectId,page:'测试发布'}));
  },project.id);
  await page.goto('/');
  await page.evaluate(()=>window.setPage('测试发布'));

  await expect(page.getByText('线上抽检 / 反馈',{exact:true})).toBeVisible();
  await page.locator('#predFile').setInputFiles({name:'camera.bmp',mimeType:'image/bmp',buffer:bmp()});
  await page.getByRole('button',{name:'开始测试'}).click();
  await expect(page.getByText('正式算法版本可提交抽检反馈')).toBeVisible();
  await page.getByRole('button',{name:'提交抽检反馈'}).click();
  const create=page.getByRole('dialog',{name:'提交线上抽检反馈'});
  await create.locator('#feedbackType63').selectOption('needs_correction');
  await create.locator('#feedbackNote63').fill('画面里有烟，但模型漏检');
  await create.getByRole('button',{name:'提交到待复核'}).click();

  await expect.poll(()=>staged?.prediction_id).toBe('prediction-feedback-1');
  expect(staged.feedback_type).toBe('needs_correction');
  const review=page.getByRole('dialog',{name:'复核线上抽检反馈'});
  await expect(review).toContainText('漏检 / 框不对');
  await expect(review).toContainText('不会写成真值');
  await expect(review).toContainText('algo-feedback');
  await expect(review).toContainText('version-feedback');
  await review.getByRole('button',{name:'确认反馈'}).click();

  await expect.poll(()=>confirmed).not.toBeNull();
  expect(confirmed).toEqual({
    expected_feedback_type:'needs_correction',
    dataset_id:'default',
    confirm_all_labels_absent:false,
  });
  await expect.poll(async()=>page.evaluate(()=>state.page)).toBe('数据集');
  expect(requests.filter(url=>url.includes('/train/start'))).toEqual([]);
  expect(requests.filter(url=>/dataset.*revision/i.test(url))).toEqual([]);
  expect(requests.filter(url=>url.includes('/jobs/'))).toEqual([]);
});


test('false-positive feedback requires explicit all-label negative confirmation', async ({page,request})=>{
  const project=await (await request.post('/api/projects',{data:{
    name:`负样本抽检-${Date.now()}`,labels:['smoke'],
  }})).json();
  const encoded=encodeURIComponent(project.id);
  let confirmed=null;
  await page.route('**/api/v16/inference_envs',route=>route.fulfill({
    status:200,contentType:'application/json',
    body:JSON.stringify({items:[{id:'feedback-env',name:'抽检环境',framework:'ultralytics',status:'ready'}]}),
  }));
  await page.route(`**/api/v12/projects/${encoded}/test_models*`,route=>route.fulfill({
    status:200,contentType:'application/json',
    body:JSON.stringify({ok:true,items:[{
      label:'算法版本：烟雾识别 / 当前',model_source:'algorithm_version',framework:'ultralytics',
      algorithm_id:'algo-feedback',version_id:'version-feedback',path:'/models/best.pt',
    }]}),
  }));
  await page.route(`**/api/v12/projects/${encoded}/predict`,route=>route.fulfill({
    status:200,contentType:'application/json',
    body:JSON.stringify({
      ok:true,prediction_id:'prediction-negative-1',feedback_eligible:true,
      algorithm_id:'algo-feedback',version_id:'version-feedback',
      model_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),
      detections:[{class_id:0,label:'smoke',confidence:.8,x1:10,y1:10,x2:40,y2:40}],
      image_url:'/placeholder.jpg',elapsed_ms:5,engine:'ultralytics',
    }),
  }));
  await page.route(`**/api/v63/projects/${encoded}/online-feedback?*`,route=>route.fulfill({
    status:200,contentType:'application/json',body:JSON.stringify({ok:true,items:[]}),
  }));
  await page.route(`**/api/v63/projects/${encoded}/online-feedback`,route=>route.fulfill({
    status:201,contentType:'application/json',body:JSON.stringify({ok:true,feedback:{
      id:'feedback-negative',prediction_id:'prediction-negative-1',status:'pending_review',
      feedback_type:'false_positive',algorithm_id:'algo-feedback',version_id:'version-feedback',
      model_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),created_at:'now',source:{},
    }}),
  }));
  await page.route(`**/api/v63/projects/${encoded}/online-feedback/feedback-negative`,route=>route.fulfill({
    status:200,contentType:'application/json',body:JSON.stringify({ok:true,feedback:{
      id:'feedback-negative',prediction_id:'prediction-negative-1',status:'pending_review',
      feedback_type:'false_positive',algorithm_id:'algo-feedback',version_id:'version-feedback',
      model_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),created_at:'now',
      source:{detections:[{index:0,label:'smoke',confidence:.8,x1:10,y1:10,x2:40,y2:40}]},
      input_image_url:'/placeholder.jpg',result_image_url:'/placeholder.jpg',
    }}),
  }));
  await page.route(`**/api/v63/projects/${encoded}/online-feedback/feedback-negative/confirm`,async route=>{
    confirmed=route.request().postDataJSON();
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,feedback:{
      id:'feedback-negative',status:'confirmed',feedback_type:'false_positive',material_id:'material-negative',
      result:{annotation_action:'confirmed_empty',needs_manual_annotation:false},
    }})});
  });

  await page.addInitScript(projectId=>{
    localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({projectId,page:'测试发布'}));
  },project.id);
  await page.goto('/');await page.evaluate(()=>window.setPage('测试发布'));
  await page.locator('#predFile').setInputFiles({name:'negative.bmp',mimeType:'image/bmp',buffer:bmp()});
  await page.getByRole('button',{name:'开始测试'}).click();
  await page.getByRole('button',{name:'提交抽检反馈'}).click();
  const create=page.getByRole('dialog',{name:'提交线上抽检反馈'});
  await create.locator('#feedbackType63').selectOption('false_positive');
  await create.getByRole('button',{name:'提交到待复核'}).click();
  const review=page.getByRole('dialog',{name:'复核线上抽检反馈'});
  await expect(review.locator('#feedbackAllAbsent63')).not.toBeChecked();
  await review.locator('#feedbackAllAbsent63').check();
  await review.getByRole('button',{name:'确认反馈'}).click();
  await expect.poll(()=>confirmed).not.toBeNull();
  expect(confirmed.confirm_all_labels_absent).toBe(true);
});


test('pending reviewed feedback can be dismissed without promotion or training', async ({page,request})=>{
  const project=await (await request.post('/api/projects',{data:{
    name:'忽略抽检-'+Date.now(),labels:['smoke'],
  }})).json();
  const encoded=encodeURIComponent(project.id);
  const requested=[];
  page.on('request',req=>requested.push(req.url()));
  let staged=null;
  let dismissed=null;
  let feedbackStatus='pending_review';

  await page.route('**/api/v16/inference_envs',route=>route.fulfill({
    status:200,contentType:'application/json',
    body:JSON.stringify({items:[{id:'feedback-env',name:'抽检环境',framework:'ultralytics',status:'ready'}]}),
  }));
  await page.route('**/api/v12/projects/'+encoded+'/test_models*',route=>route.fulfill({
    status:200,contentType:'application/json',
    body:JSON.stringify({ok:true,items:[{
      label:'算法版本：烟雾识别 / 当前',model_source:'algorithm_version',framework:'ultralytics',
      algorithm_id:'algo-feedback',version_id:'version-feedback',path:'/models/best.pt',
    }]}),
  }));
  await page.route('**/api/v12/projects/'+encoded+'/predict',route=>route.fulfill({
    status:200,contentType:'application/json',
    body:JSON.stringify({
      ok:true,prediction_id:'prediction-dismiss-1',feedback_eligible:true,
      algorithm_id:'algo-feedback',version_id:'version-feedback',
      model_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),
      detections:[],image_url:'/placeholder.jpg',elapsed_ms:5,engine:'ultralytics',
    }),
  }));
  await page.route('**/api/v63/projects/'+encoded+'/online-feedback?*',route=>route.fulfill({
    status:200,contentType:'application/json',
    body:JSON.stringify({ok:true,items:staged?[{...staged,status:feedbackStatus,source:{detection_count:0},result:dismissed?{dismissed:true}:{}}]:[]}),
  }));
  await page.route('**/api/v63/projects/'+encoded+'/online-feedback',async route=>{
    if(route.request().method()!=='POST')return route.continue();
    const body=route.request().postDataJSON();
    staged={
      id:'feedback-dismiss',prediction_id:body.prediction_id,status:'pending_review',
      feedback_type:body.feedback_type,algorithm_id:'algo-feedback',version_id:'version-feedback',
      model_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),material_id:'',created_at:'now',note:'',
    };
    await route.fulfill({status:201,contentType:'application/json',body:JSON.stringify({ok:true,idempotent:false,feedback:staged})});
  });
  await page.route('**/api/v63/projects/'+encoded+'/online-feedback/feedback-dismiss',route=>route.fulfill({
    status:200,contentType:'application/json',body:JSON.stringify({ok:true,feedback:{
      ...staged,source:{detections:[]},input_image_url:'/placeholder.jpg',result_image_url:'',result:{},
    }}),
  }));
  await page.route('**/api/v63/projects/'+encoded+'/online-feedback/feedback-dismiss/dismiss',async route=>{
    dismissed=route.request().postDataJSON();
    feedbackStatus='dismissed';
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,idempotent:false,feedback:{
      ...staged,status:'dismissed',material_id:'',result:{dismissed:true,dismiss_reason:'人工复核忽略'},
    }})});
  });

  await page.addInitScript(projectId=>{
    localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({projectId,page:'测试发布'}));
  },project.id);
  await page.goto('/');
  await page.evaluate(()=>window.setPage('测试发布'));
  await page.locator('#predFile').setInputFiles({name:'dismiss.bmp',mimeType:'image/bmp',buffer:bmp()});
  await page.getByRole('button',{name:'开始测试'}).click();
  await page.getByRole('button',{name:'提交抽检反馈'}).click();
  const create=page.getByRole('dialog',{name:'提交线上抽检反馈'});
  await create.locator('#feedbackType63').selectOption('needs_correction');
  await create.getByRole('button',{name:'提交到待复核'}).click();
  const review=page.getByRole('dialog',{name:'复核线上抽检反馈'});
  await review.getByRole('button',{name:'忽略反馈'}).click();
  await expect.poll(()=>dismissed).not.toBeNull();
  expect(dismissed.expected_feedback_type).toBe('needs_correction');
  await expect(page.locator('#onlineFeedbackRows63')).toContainText('已忽略');
  expect(requested.filter(url=>url.includes('/train/start'))).toEqual([]);
  expect(requested.filter(url=>/dataset.*revision/i.test(url))).toEqual([]);
  expect(requested.filter(url=>url.includes('/jobs/'))).toEqual([]);
});


test('external feedback intake contract is exposed from reviewed feedback panel', async ({page,request})=>{
  const project=await (await request.post('/api/projects',{data:{name:'外部接入-'+Date.now(),labels:['smoke']}})).json();
  const encoded=encodeURIComponent(project.id);
  await page.route('**/api/v16/inference_envs',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({items:[]})}));
  await page.route('**/api/v12/projects/'+encoded+'/test_models*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,items:[]})}));
  await page.route('**/api/v63/projects/'+encoded+'/online-feedback?*',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({ok:true,items:[]})}));
  await page.addInitScript(projectId=>{localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({projectId,page:'测试发布'}));},project.id);
  await page.goto('/');
  await page.evaluate(()=>window.setPage('测试发布'));
  await page.getByRole('button',{name:'外部接入'}).click();
  const dialog=page.getByRole('dialog',{name:'外部抽检接入'});
  await expect(dialog).toContainText('/api/v63/projects/'+project.id+'/online-feedback/external-intake');
  await expect(dialog).toContainText('multipart/form-data');
  await expect(dialog).toContainText('不会自动修改素材、数据集、Dataset Revision 或训练任务');
  await expect(dialog).not.toContainText('/api/v42/');
});
