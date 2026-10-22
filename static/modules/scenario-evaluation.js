// Read-only projections of the existing version/evaluation contracts.
const digest=value=>typeof value==='string'&&/^[a-f0-9]{64}$/i.test(value);
const finite=value=>value!==null&&value!==''&&['number','string'].includes(typeof value)&&Number.isFinite(Number(value))?Number(value):null;
export function eligibleScenarioModels(rows=[]) {
  return rows.filter(row=>row?.scenario_eligible===true&&row.model_source==='algorithm_version'
    &&row.algorithm_id&&row.version_id&&row.training_task_id&&digest(row.model_sha256)&&Number(row.model_size)>0);
}
export function latestScenarioModel(rows,algorithmId) {
  return eligibleScenarioModels(rows).filter(row=>String(row.algorithm_id)===String(algorithmId))
    .sort((a,b)=>String(b.finished_at||b.created_at||'').localeCompare(String(a.finished_at||a.created_at||''))||String(b.version_id).localeCompare(String(a.version_id)))[0]||null;
}
export function evaluationTruth(evaluation,model) {
  const e=evaluation||{},scope=e.benchmark_scope||{};
  const trusted=e.status==='succeeded'&&digest(e.evaluation_id)&&digest(e.evaluation_protocol_id)&&Number(e.image_count)>0&&Number(e.image_count)===Number(scope.test_image_count)&&e.task_id===model?.training_task_id
    &&e.model_sha256===model?.model_sha256&&!!e.snapshot_id&&digest(e.dataset_revision_id)
    &&scope.binding_level==='bundle_verified'&&['scope_id','content_digest','ground_truth_digest','label_schema_digest','evaluation_input_digest'].every(key=>digest(scope[key]))&&!!scope.training_input_policy;
  return {trusted:!!trusted,evaluation:trusted?e:null,reason:trusted?'':'尚未进行独立评测，或历史报告缺少可验证的冻结身份'};
}
export function scenarioMetric(value,{covered=true}={}) {
  if(!covered)return '未覆盖';const n=finite(value);
  return n===null||n<0||n>1?'未记录':`${(n*100).toFixed(1)}%`;
}
export function visibleEvidenceBoxes(rows=[],{label='',confidence=0,prediction=false}={}) {
  return rows.filter(row=>{
    const b=row.box||[row.x1,row.y1,row.x2,row.y2];
    return b.length===4&&b.every(Number.isFinite)&&b[2]>b[0]&&b[3]>b[1]
      &&(!label||String(row.label)===String(label))
      &&(!prediction||(finite(row.confidence)!==null&&Number(row.confidence)>=Number(confidence)));
  });
}
export function sampleIssueKinds(row={}) {
  return [['fp','fp_count'],['fn','fn_count'],['wrong_class','classification_error_count'],['localization','localization_error_count'],['low_confidence','low_confidence_count']].filter(([,field])=>Number(row[field])>0).map(([key])=>key);
}
