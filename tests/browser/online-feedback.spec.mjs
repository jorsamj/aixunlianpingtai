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

  await expect(page.getByRole('button',{name:'开始测试'})).toBeEnabled();
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
  await expect.poll(async()=>page.evaluate(projectId=>(state.projects||[]).some(row=>String(row.id)===String(projectId)),project.id)).toBe(true);
  await page.evaluate(projectId=>{
    const selected=(state.projects||[]).find(row=>String(row.id)===String(projectId));
    if(!selected)throw new Error('test project is missing from loaded project truth');
    state.project=selected;
    try{
      const saved=JSON.parse(localStorage.getItem('mc_train_ui_state_v34')||'{}');
      saved.projectId=projectId;saved.page='测试发布';
      localStorage.setItem('mc_train_ui_state_v34',JSON.stringify(saved));
    }catch(_){}
    window.setPage('测试发布');
  },project.id);
  await page.getByRole('button',{name:'外部接入'}).click();
  const dialog=page.getByRole('dialog',{name:'外部抽检接入'});
  await expect(dialog.locator('#feedbackExternalEndpoint63')).toHaveValue('/api/v63/projects/'+project.id+'/online-feedback/external-intake');
  await expect(dialog.locator('#feedbackExternalFormat63')).toHaveValue('multipart/form-data');
  await expect(dialog).toContainText('不会自动修改素材、数据集、Dataset Revision 或训练任务');
  await expect(dialog).not.toContainText('/api/v42/');
  await dialog.locator('.btn.primary').filter({hasText:'关闭'}).click();
  await page.evaluate(()=>window.openAuditConnect42());
  const legacy=page.getByRole('dialog',{name:'外部抽检接入'});
  await expect(legacy.locator('#feedbackExternalEndpoint63')).toHaveValue('/api/v63/projects/'+project.id+'/online-feedback/external-intake');
  await expect(legacy).not.toContainText('/api/v42/');
});


test('confirmed feedback candidates are frozen before dataset revision or training', async ({page,request})=>{
  const project=await (await request.post('/api/projects',{data:{
    name:`反馈补数据候选-${Date.now()}`,labels:['smoke'],
  }})).json();
  const encoded=encodeURIComponent(project.id);
  let freezePayload=null;
  let candidateListCalls=0;
  let persistedCandidateSet=null;
  const requested=[];
  page.on('request',req=>requested.push(req.url()));

  const persistedAction={
    schema_version:1,status:'confirmed',action:'supplement_data',action_id:'d'.repeat(64),
    source:{algorithm_id:'algo-supp',version_id:'ver-supp',decision_id:'e'.repeat(64),evaluation_id:'a'.repeat(64)},
    data_draft:{weak_labels:['smoke'],problem_samples:[],dataset_revision_id:'',snapshot_id:'snapshot-old'},
  };
  await page.route(`**/api/v12/projects/${encoded}/algorithms`,async route=>{
    if(route.request().method()!=='GET')return route.continue();
    await route.fulfill({
      status:200,contentType:'application/json',
      body:JSON.stringify({items:[{
        id:'algo-supp',name:'补数据算法',current_version_id:'ver-supp',
        versions:[{
          id:'ver-supp',version_name:'v-feedback',
          confirmed_iteration_action:persistedAction,
          ...(persistedCandidateSet?{supplement_data_candidate_set:persistedCandidateSet}:{}),
        }],
      }]}),
    });
  });

  await page.route(`**/api/v63/projects/${encoded}/algorithms/algo-supp/versions/ver-supp/supplement-data-candidates`,async route=>{
    if(route.request().method()!=='GET')return route.continue();
    candidateListCalls+=1;
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      ok:true,action_id:'d'.repeat(64),total:2,returned:2,truncated:false,eligible:1,annotation_required:1,candidate_set:null,
      items:[
        {
          schema_version:1,feedback_id:'feedback-ready',feedback_type:'correct',material_id:'material-ready',
          algorithm_id:'algo-supp',version_id:'ver-supp',model_sha256:'a'.repeat(64),input_sha256:'b'.repeat(64),
          confirmed_at:'2026-09-19T06:00:00Z',annotation_state:'annotated',annotation_hash:'c'.repeat(64),
          annotation_scope:['smoke'],labels:['smoke'],source_channel:'platform_prediction',
          external_source:'',external_sample_id:'',needs_manual_annotation:false,eligible:true,reason_codes:[],
          candidate_digest:'1'.repeat(64),
        },
        {
          schema_version:1,feedback_id:'feedback-review',feedback_type:'needs_correction',material_id:'material-review',
          algorithm_id:'algo-supp',version_id:'ver-supp',model_sha256:'a'.repeat(64),input_sha256:'e'.repeat(64),
          confirmed_at:'2026-09-19T06:01:00Z',annotation_state:'unannotated',annotation_hash:'',
          annotation_scope:[],labels:[],source_channel:'external_upload',external_source:'edge-01',
          external_sample_id:'sample-2',needs_manual_annotation:true,eligible:false,
          reason_codes:['ANNOTATION_REQUIRED'],candidate_digest:'2'.repeat(64),
        },
      ],
    })});
  });
  await page.route(`**/api/v63/projects/${encoded}/algorithms/algo-supp/versions/ver-supp/supplement-data-candidates/freeze`,async route=>{
    freezePayload=route.request().postDataJSON();
    persistedCandidateSet={
      schema_version:1,status:'confirmed',candidate_set_id:'f'.repeat(64),action_id:'d'.repeat(64),
      algorithm_id:'algo-supp',version_id:'ver-supp',feedback_ids:['feedback-ready'],
      material_ids:['material-ready'],candidates:[{feedback_id:'feedback-ready',material_id:'material-ready'}],
      frozen_at:'2026-09-19T06:02:00Z',automatic_execution:false,
    };
    await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({
      ok:true,idempotent:false,candidate_set:persistedCandidateSet,
    })});
  });

  await page.addInitScript(projectId=>{
    localStorage.setItem('mc_train_ui_state_v34',JSON.stringify({projectId,page:'算法列表'}));
  },project.id);
  await page.goto('/');
  await expect.poll(async()=>page.evaluate(projectId=>(state.projects||[]).some(row=>String(row.id)===String(projectId)),project.id)).toBe(true);
  await page.evaluate(async projectId=>{
    const selected=(state.projects||[]).find(row=>String(row.id)===String(projectId));
    if(!selected)throw new Error('test project is missing from loaded project truth');
    state.project=selected;
    try{
      const saved=JSON.parse(localStorage.getItem('mc_train_ui_state_v34')||'{}');
      saved.projectId=projectId;saved.page='算法列表';
      localStorage.setItem('mc_train_ui_state_v34',JSON.stringify(saved));
    }catch(_){}
    await window.AlgorithmListRuntime?.refresh?.({render:false});
    state.images=[{
      id:'material-ready',filename:'feedback-ready.jpg',annotated:true,processing_status:'processed',
      labels:['smoke'],size_bytes:100,created_at:'2026-09-19T06:00:00Z',url:'/static/placeholder.png',
    }];
    await window.resumeConfirmedIterationAction429('algo-supp','ver-supp');
  },project.id);

  const dialog=page.getByRole('dialog',{name:'补数据反馈候选'});
  await expect(dialog).toContainText('可直接加入 1 条');
  await expect(dialog).toContainText('待人工标注 1 条');
  await expect(dialog).toContainText('不会自动创建 Dataset Revision');
  await expect(dialog.locator('[data-feedback-candidate="feedback-ready"]')).toBeChecked();
  await expect(dialog.locator('[data-feedback-candidate="feedback-review"]')).toBeDisabled();
  await dialog.getByRole('button',{name:'冻结并进入数据集'}).click();

  await expect.poll(()=>freezePayload).toEqual({candidates:[{
    feedback_id:'feedback-ready',candidate_digest:'1'.repeat(64),
  }]});
  await expect(page.getByText('已冻结反馈候选 1 张')).toBeVisible();
  await expect(page.getByText('尚未生成 Dataset Revision、Snapshot 或训练任务。')).toBeVisible();
  expect(candidateListCalls).toBe(1);

  // Persisted Candidate Set resumes directly to Dataset truth after a fresh
  // transient UI state; it must not reopen/re-fetch the candidate review.
  await page.evaluate(async()=>{
    state.iterationDataDraft=null;
    state.iterationFeedbackCandidateIds63=new Set();
    state.iterationFeedbackOnly63=false;
    await window.resumeConfirmedIterationAction429('algo-supp','ver-supp');
  });
  await expect.poll(async()=>page.evaluate(()=>state.iterationDataDraft?.weak_labels||[]))
    .toEqual(['smoke']);
  await expect(page.locator('.iteration-feedback-candidates63')).toContainText('已冻结反馈候选 1 张');
  expect(candidateListCalls).toBe(1);
  expect(requested.some(url=>url.includes('/train/start'))).toBeFalsy();
  expect(requested.some(url=>url.includes('dataset_revisions'))).toBeFalsy();
});
