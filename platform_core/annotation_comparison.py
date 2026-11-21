"""Session-only comparison; no repository or persistence dependencies."""
import math
from .auto_label import _iou


def compare_boxes(baseline, predictions, *, complete=False, threshold=.5, image_width=None):
    if not math.isfinite(threshold) or not 0 < threshold <= 1:
        raise ValueError('IoU threshold must be in (0, 1]')
    if len(baseline)>500 or len(predictions)>500:
        raise ValueError('Comparison supports at most 500 boxes per side')
    for box in [*baseline,*predictions]:
        v=[box.get(k) for k in ('x1','y1','x2','y2')]
        if not all(isinstance(n,(int,float)) and math.isfinite(n) for n in v) or v[0]<0 or v[1]<0 or v[2]<=v[0] or v[3]<=v[1] or not str(box.get('label') or '').strip():
            raise ValueError('Invalid comparison rectangle')
    used_b,used_p=set(),set()
    matches=[]
    edges=sorted(((_iou(b,p),i,j) for i,b in enumerate(baseline) for j,p in enumerate(predictions) if b['label']==p['label']),key=lambda e:(-e[0],e[1],e[2]))
    for overlap,i,j in edges:
        if overlap<threshold: break
        if i in used_b or j in used_p: continue
        used_b.add(i);used_p.add(j)
        b,p=baseline[i],predictions[j]
        bw,bh=b['x2']-b['x1'],b['y2']-b['y1']
        pw,ph=p['x2']-p['x1'],p['y2']-p['y1']
        matches.append(dict(baseline=i,prediction=j,label=b['label'],iou=overlap,
            dx=(p['x1']+p['x2']-b['x1']-b['x2'])/2,dy=(p['y1']+p['y2']-b['y1']-b['y2'])/2,
            width_delta=pw-bw,height_delta=ph-bh,area_ratio=pw*ph/(bw*bh)))
    matches.sort(key=lambda m:m['baseline'])
    missed=[i for i in range(len(baseline)) if i not in used_b]
    extra=[j for j in range(len(predictions)) if j not in used_p]
    conflicts=[dict(baseline=i,prediction=j,iou=_iou(baseline[i],predictions[j])) for i in missed for j in extra if baseline[i]['label']!=predictions[j]['label'] and _iou(baseline[i],predictions[j])>=threshold]
    duplicates=[j for j in extra if any(predictions[j]['label']==predictions[k]['label'] and _iou(predictions[j],predictions[k])>=threshold for k in used_p)]
    tp,fp,fn=len(matches),len(extra),len(missed)
    precision=tp/(tp+fp) if tp+fp else 0
    recall=tp/(tp+fn) if tp+fn else 0
    metrics=dict(precision=precision,recall=recall,f1=2*precision*recall/(precision+recall) if precision+recall else 0,mean_iou=sum(m['iou'] for m in matches)/tp if tp else None) if complete else None
    per_label = {}
    for label in sorted({b['label'] for b in [*baseline,*predictions]}):
        label_tp=sum(m['label']==label for m in matches)
        per_label[label] = dict(tp=label_tp,fp=sum(predictions[j]['label']==label for j in extra),fn=sum(baseline[i]['label']==label for i in missed))
    spatial = {"cause": "not_determined", "evidence_count": len(matches)}
    if image_width and image_width > 0 and len(matches) >= 2:
        points=[((baseline[m['baseline']]['x1']+baseline[m['baseline']]['x2'])/2-image_width/2,m['dx']) for m in matches]
        left=[dx for x,dx in points if x<0];right=[dx for x,dx in points if x>0]
        spatial['both_sides_outward'] = bool(left and right and all(dx<0 for dx in left) and all(dx>0 for dx in right))
        spatial['all_downward'] = all(m['dy']>0 for m in matches)
        mx=sum(x for x,dx in points)/len(points);my=sum(dx for x,dx in points)/len(points)
        variance=sum((x-mx)**2 for x,dx in points)
        spatial['horizontal_error_slope'] = sum((x-mx)*(dx-my) for x,dx in points)/variance if variance else None
        spatial['mean_vertical_offset'] = sum(m['dy'] for m in matches)/len(matches)
    diagnosis = {"summary": f"同类匹配{tp}，疑似多检{fp}，疑似漏检{fn}，标签冲突{len(conflicts)}，重复候选{len(duplicates)}",
        "spatial":spatial,"baseline_complete":complete,
        "next_check":"逐级对照原始框、原图像素转换框、前端显示框与人工基准；仅偏移趋势不能区分模型定位和平台变换",
        "candidate_advice":"可进入候选审核，不能直接写入正式GT" if complete else "先补全人工基准，再判断预标注效果"}
    return dict(tp=tp,fp=fp,fn=fn,matches=matches,missed=missed,extra=extra,label_conflicts=conflicts,duplicates=duplicates,metrics=metrics,per_label=per_label,diagnosis=diagnosis,
        conclusion='仅代表本张图；基准未确认完整时不提供精度指标。偏移原因须结合原始框、转换框与显示几何核查，不能仅凭方向断言。')
