import test from 'node:test';
import assert from 'node:assert/strict';
import * as reports from '../../static/modules/reports.js';

export function isolatedReport(label='person',imgsz=800,workers=8) {
  return {job:{id:'isolated-'+label,auto_version_id:'v-'+label},report:{
    identity:{job_id:'isolated-'+label,version_id:'v-'+label,algorithm_id:'a-'+label,algorithm_name:label+'隔离验收',project_id:'test-project'},
    framework:'ultralytics',model_architecture:'YOLOv11n',class_mapping:[{class_id:0,code:label,name:label}],
    requested_train_params:{epochs:300,imgsz,batch:32,workers,precision:'fp32',optimizer:'auto',lr0:.01},
    actual_train_params:{imgsz,batch:32,workers,effective_precision:'fp32',amp_runtime_enabled:false},
    history:[],metrics:{},evaluation:{status:'not_recorded'},
    conversions:[{target:'sophon',chip_code:'bm1688',sha256:'a'.repeat(64),metadata:{precision:'fp16',source_training_precision:'fp32',image_width:imgsz,image_height:imgsz,validation_status:'converted_unverified',hardware_verification:{status:'PASS',input_kind:'synthetic'}}}],
    evidence_fixture:true,
  }};
}
for(const [label,size,workers] of [['person',800,8],['Car',640,0]])test(`deterministic ${label} materials preserve unknown quality and real configuration`,()=>{
 const input=isolatedReport(label,size,workers);
 const text=reports.chatGPTAnalysisMaterial(input);
 assert.equal(text,reports.chatGPTAnalysisMaterial(structuredClone(input)));
 assert.match(text,/确定性|真实训练/);assert.match(text,/YOLOv11n/);assert.ok(text.includes(label));
 assert.ok(text.includes(String(size)));assert.match(text,/BM1688|bm1688/);
 assert.match(text,/FP32|fp32/);assert.match(text,/FP16|fp16/);
 assert.match(text,/未记录/);assert.match(text,/手动附上.*异常图片/);
 assert.doesNotMatch(text,/已达到业务要求|确定.*I\/O瓶颈|mAP50.*100%/);
 assert.match(text,/实际Optimizer[^\n]*未记录/);assert.match(text,/实际初始LR[^\n]*未记录/);
 assert.match(text,/合成.*不.*业务/);
});
test('supplements are optional unverified and secrets URLs private paths never exported',()=>{
 const input=isolatedReport();input.report.actual_train_params.token='secret-raw';input.report.history=[{epoch:1,map50:null,token:'hidden'}];
 const text=reports.chatGPTAnalysisMaterial(input,{scenario:'工厂 token=secret-value https://oss.example/a?signature=private C:\\private\\model.pt /data/private/secret.pt',target:'每小时误报小于1次'});
 assert.match(text,/用户提供的现场描述，尚未由训练系统独立验证/);assert.match(text,/每小时误报小于1次/);
 for(const secret of ['secret-raw','secret-value','signature=private','C:\\private','/data/private/secret.pt','oss.example'])assert.ok(!text.includes(secret),secret);
 assert.doesNotMatch(text,/https?:\/\//);
});
test('mismatched report identity fails rather than mixing versions or tasks',()=>{
 const input=isolatedReport();input.report.identity.job_id='another-job';
 assert.throws(()=>reports.chatGPTAnalysisMaterial(input),/身份|任务|不一致/);
 assert.throws(()=>reports.trainingReportHtml(input),/身份|任务|不一致/);
});
test('curves use only actual finite records and scoped Val/Test evidence',()=>{
 const input=isolatedReport();input.report.history=[{epoch:1,map50:.2,box_loss:1},{epoch:2,map50:null},{epoch:3,map50:.4,box_loss:.8}];
 input.report.metrics={precision:.5,recall:.8,map50:.4};input.report.evaluation={status:'not_requested'};
 const text=reports.chatGPTAnalysisMaterial(input);
 assert.match(text,/最佳已记录.*3/);assert.match(text,/Validation|Val/);assert.match(text,/独立Test|独立 Test/);
 assert.doesNotMatch(text,/Test mAP50[^\n]*0\.4/);
 assert.equal(reports.chatGPTAnalysisMaterial({...input,report:{...input.report,generated_at:'changed'}}),text);
});

test('interactive chart contract groups real metrics and preserves missing points',()=>{
 const groups=reports.trainingChartGroups([{epoch:1,map50:.5,precision:.6},{epoch:2,map50:null,precision:.7},{epoch:3,map50:.8,precision:.9}]);
 const accuracy=groups.find(group=>group.key==='accuracy');
 assert.equal(accuracy.options.tooltip.trigger,'axis');
 assert.equal(accuracy.options.xAxis.type,'category');
 assert.deepEqual(accuracy.options.series.find(s=>s.name==='mAP50').data,[.5,null,.8]);
 assert.equal(accuracy.options.series[0].connectNulls,false);
 assert.ok(accuracy.options.dataZoom.some(z=>z.type==='inside'));
 assert.ok(accuracy.options.toolbox.feature.restore);
 assert.equal(reports.trainingChartGroups([]).length,0);
 assert.equal(reports.trainingChartGroups([{epoch:1,map50:true}]).length,0);
});

test('report UI and copied facts share recorded job epochs when legacy report fields are absent',()=>{
 const input=isolatedReport();input.job.completed_epochs=46;input.job.requested_epochs=100;input.job.completion_reason='quality_target_reached';delete input.report.requested_train_params.epochs;
 const html=reports.trainingReportHtml(input),text=reports.chatGPTAnalysisMaterial(input);
 assert.match(html,/实际轮次[^]*46/);assert.match(text,/实际完成Epoch：46/);assert.match(text,/请求Epoch：100/);
 assert.match(html,/训练停止目标状态/);assert.match(html,/不代表.*业务|业务验收：未记录/);
});

test('user strings redact JSON token spellings and UNC paths',()=>{
 const text=reports.chatGPTAnalysisMaterial(isolatedReport(),{scenario:'{"access_token":"sensitive-json"} accessToken=sensitive-camel \\\\server\\share\\secret.pt'});
 for(const value of ['sensitive-json','sensitive-camel','server','secret.pt'])assert.ok(!text.includes(value),value);
});

test('actual batch workers precision and AMP come from known frozen facts without contradictory unknowns',()=>{
 const input=isolatedReport('Car',640,0);const text=reports.chatGPTAnalysisMaterial(input);
 assert.match(text,/实际Batch：32/);assert.match(text,/实际Workers：0/);
 assert.doesNotMatch(text,/实际训练精度：未记录/);assert.equal((text.match(/实际AMP：/g)||[]).length,1);
});

test('existing frozen distributions artifacts and verified model download remain available',()=>{
 const input=isolatedReport();input.report.artifact_verified=true;input.report.artifacts=['/private/best.pt'];input.report.frozen_data_quality={image_count:10,duplicate_count:0,classes:[{label:'person',image_count:8,box_count:12}]};
 const html=reports.trainingReportHtml(input);
 assert.match(html,/冻结数据质量/);assert.match(html,/核查正式素材与标注/);assert.match(html,/下载有效版本模型/);assert.match(html,/best.pt/);assert.doesNotMatch(html,/>\/private\/best.pt</);
 assert.match(html,/正样本图片/);assert.match(html,/>12<\/td>/);
});
