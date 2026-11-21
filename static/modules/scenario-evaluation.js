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
export function visibleEvidenceBoxes(rows=[],{label='',classId,confidence=0,prediction=false}={}) {
  return rows.filter(row=>{
    const b=row.box||[row.x1,row.y1,row.x2,row.y2];
    return b.length===4&&b.every(Number.isFinite)&&b[2]>b[0]&&b[3]>b[1]
      &&(classId==null||classIdentity(classId)!==null&&classIdentity(row.class_id)===classIdentity(classId))
      &&(!label||String(row.label)===String(label))
      &&(!prediction||(finite(row.confidence)!==null&&Number(row.confidence)>=Number(confidence)));
  });
}
// Evidence diagnostics are observations only; they never re-score formal metrics.
function classIdentity(value) {
  if(value==null||typeof value==='string'&&!value.trim())return null;
  const n=finite(value);return Number.isInteger(n)&&n>=0?n:null;
}
function sameEvidenceClass(a,b,boxes) {
  const hasA=a.class_id!=null,hasB=b.class_id!=null,ai=classIdentity(a.class_id),bi=classIdentity(b.class_id);
  if(hasA&&ai===null||hasB&&bi===null)return false;
  const ac=String(a.label||''),bc=String(b.label||'');
  // Reject explicit disagreements even where an identical name could mask them.
  if(hasA&&hasB&&(ai!==bi||ac&&bc&&ac!==bc))return false;
  for(const item of [a,b]){
    const id=classIdentity(item.class_id),code=String(item.label||'');
    if(id!==null&&code&&boxes.some(other=>classIdentity(other.class_id)===id&&other.label&&String(other.label)!==code))return false;
  }
  if(hasA&&hasB)return true;
  if(!/^[A-Za-z][A-Za-z0-9_-]*$/.test(ac)||ac!==bc)return false;
  const ids=new Set(boxes.filter(box=>String(box.label||'')===ac).map(box=>classIdentity(box.class_id)).filter(id=>id!==null));
  return ids.size<=1;
}
function rectangle(box) {
  const b=box?.box||[box?.x1,box?.y1,box?.x2,box?.y2];
  return Array.isArray(b)&&b.length===4&&b.every(n=>Number.isFinite(n)&&n>=0)&&b[2]>b[0]&&b[3]>b[1]?b:null;
}
function overlap(a,b) {
  const intersection=Math.max(0,Math.min(a[2],b[2])-Math.max(a[0],b[0]))*Math.max(0,Math.min(a[3],b[3])-Math.max(a[1],b[1]));
  return intersection/((a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-intersection);
}
export function sampleEvidenceDiagnostics(row={}, {evaluation,lowConfidenceThreshold=.5}={}) {
  const kinds=[],wrongClassCells=[],lowConfidencePredictionIndexes=[],truePositivePredictionIndexes=[],truePositiveGroundTruthIndexes=[],localizationCandidates=[];
  const truth=Array.isArray(row.gt_boxes)?row.gt_boxes:[],predictions=Array.isArray(row.pred_boxes)?row.pred_boxes:[];
  const formal=Array.isArray(row.gt_boxes),rawOnly=Array.isArray(row.detections)&&!formal;
  if(!rawOnly){
    if(Number(row.fp_count)>0)kinds.push('fp');
    if(Number(row.fn_count)>0)kinds.push('fn');
  }
  const matrix=evaluation?.confusion_matrix;
  if(!rawOnly&&row.image&&matrix?.protocol==='confidence_first_class_agnostic_iou_0.5'){
    for(const cell of Array.isArray(matrix.cells)?matrix.cells:[]){
      const actual=classIdentity(cell.actual),predicted=classIdentity(cell.predicted);
      if(actual!==null&&predicted!==null&&actual!==predicted&&Array.isArray(cell.images)&&cell.images.includes(row.image))wrongClassCells.push(cell);
    }
    if(wrongClassCells.length)kinds.push('wrong_class');
  }
  const requested=finite(lowConfidenceThreshold),threshold=requested!==null&&requested>=0&&requested<=1?requested:.5;
  predictions.forEach((box,index)=>{
    const score=finite(box.confidence);
    if(score!==null&&score>=0&&score<=1&&score<threshold)lowConfidencePredictionIndexes.push(index);
    if(formal&&truth.length&&box.matched===true)truePositivePredictionIndexes.push(index);
  });
  if(formal){
    truth.forEach((box,index)=>{if(box.matched===true)truePositiveGroundTruthIndexes.push(index)});
    const boxes=[...truth,...predictions];
    predictions.forEach((prediction,predictionIndex)=>{
      const a=rectangle(prediction);if(!a||prediction.matched!==false)return;
      truth.forEach((target,groundTruthIndex)=>{
        const b=rectangle(target);if(!b||target.matched!==false||!sameEvidenceClass(prediction,target,boxes))return;
        const iou=overlap(a,b);if(iou>0&&iou<.5)localizationCandidates.push({predictionIndex,groundTruthIndex,iou});
      });
    });
  }
  if(localizationCandidates.length)kinds.push('localization');
  if(lowConfidencePredictionIndexes.length)kinds.push('low_confidence');
  if(truePositivePredictionIndexes.length||truePositiveGroundTruthIndexes.length)kinds.push('tp');
  return {kinds,wrongClassCells,lowConfidencePredictionIndexes,truePositivePredictionIndexes,truePositiveGroundTruthIndexes,localizationCandidates,
    boxesTruncated:row.boxes_truncated===true,localizationLabel:'定位待复核（几何线索，非正式错误指标）'};
}
export function sampleIssueKinds(row={},options={}) {
  return sampleEvidenceDiagnostics(row,options).kinds;
}
export function sameFrozenSample(a,b) {
  if(!a||!b||!String(a.image_id??'').trim()||!String(b.image_id??'').trim()||!digest(a.image_content_sha256)||!digest(b.image_content_sha256))return false;
  const aw=finite(a.image_width),ah=finite(a.image_height),bw=finite(b.image_width),bh=finite(b.image_height);
  return [aw,ah,bw,bh].every(n=>Number.isInteger(n)&&n>0)&&String(a.image_id)===String(b.image_id)
    &&a.image_content_sha256.toLowerCase()===b.image_content_sha256.toLowerCase()&&aw===bw&&ah===bh;
}
