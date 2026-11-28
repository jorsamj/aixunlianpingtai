function aiReviewBoxIou60(a,b){
  if(!a||!b)return 0;
  const ac=[a.x1,a.y1,a.x2,a.y2].map(Number),bc=[b.x1,b.y1,b.x2,b.y2].map(Number);
  if(![...ac,...bc].every(Number.isFinite))return 0;
  const aa=(ac[2]-ac[0])*(ac[3]-ac[1]),ba=(bc[2]-bc[0])*(bc[3]-bc[1]);
  if(aa<=0||ba<=0)return 0;
  const intersection=Math.max(0,Math.min(ac[2],bc[2])-Math.max(ac[0],bc[0]))
    *Math.max(0,Math.min(ac[3],bc[3])-Math.max(ac[1],bc[1]));
  return intersection>0?intersection/(aa+ba-intersection):0;
}
// Review-only resolution: no automatic label choice or unrelated box deletion.
function aiReviewOverlapGroups60(boxes,threshold=0.5,inclusive=false){
  if(!Array.isArray(boxes)||boxes.length>300)return [];
  const parent=boxes.map((_,i)=>i),touched=new Set();
  const root=i=>{while(parent[i]!==i){parent[i]=parent[parent[i]];i=parent[i]}return i};
  for(let i=0;i<boxes.length;i++)for(let j=i+1;j<boxes.length;j++){
    const left=boxes[i],right=boxes[j];
    if(!left||!right||String(left.label||'')===String(right.label||''))continue;
    const overlap=aiReviewBoxIou60(left,right);
    if(inclusive?overlap<threshold:overlap<=threshold)continue;
    parent[root(j)]=root(i);touched.add(i);touched.add(j);
  }
  const groups=new Map();
  for(const index of touched){const key=root(index);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(index)}
  return [...groups.values()];
}
export function aiPlanKeepAmbiguousLabel60(item,{mode,label,threshold}){
  if(!item||item.status!=='success'||item.review_state&&item.review_state!=='active'||!item.manual_review_required)
    return {reason:'不是可编辑的歧义候选'};
  if(item.accepted===true)return {reason:'此图已采用，请先单图核对'};
  const boxes=item.boxes||[],groups=aiReviewOverlapGroups60(boxes,threshold,true);
  if(!groups.length)return {reason:'没有达到所填 IoU 阈值的冲突框'};
  const removed=new Set(),chosen=[];let fallbackGroups=0;
  const confidence=index=>{
    const value=boxes[index]?.confidence;
    if(value==null||value==='')return null;
    const n=Number(value);return Number.isFinite(n)&&n>=0&&n<=1?n:null;
  };
  for(const indices of groups){
    if(indices.some((index,i)=>indices.slice(i+1).some(other=>aiReviewBoxIou60(boxes[index],boxes[other])<threshold)))
      return {reason:'链式重叠不是同一位置，请逐图人工审核'};
    let winners;
    if(mode==='manual'){
      winners=indices.filter(index=>String(boxes[index].label)===label);
      if(winners.length!==1)return {reason:'冲突组中没有唯一的指定标签，请逐图人工审核'};
    }else{
      winners=[...indices].sort((a,b)=>(confidence(b)??-1)-(confidence(a)??-1)||a-b);
    }
    const keep=winners.find(index=>indices.every(other=>other===index||aiReviewBoxIou60(boxes[index],boxes[other])>=threshold));
    if(keep==null)return {reason:'指定标签框不能完整覆盖同一位置冲突'};
    if(mode==='auto'&&confidence(keep)==null)fallbackGroups++;
    chosen.push(String(boxes[keep].label||''));
    for(const index of indices)if(index!==keep)removed.add(index);
  }
  const next=boxes.filter((_,index)=>!removed.has(index));
  if(!removed.size||aiReviewOverlapGroups60(next).length)
    return {reason:'仍有低于所填阈值的跨标签冲突，请调低阈值或单图处理'};
  return {boxes:next,removed:removed.size,removedBoxes:boxes.filter((_,index)=>removed.has(index)),groups:groups.length,chosen,fallbackGroups,revision:Number(item.draft_revision||0)};
}
