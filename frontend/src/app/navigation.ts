// Names/order follow the formal legacy menu; only algorithms are native in M1.
export const menus=[
  {name:'总览',pages:[['总览','总览'],['质量中心','质量中心']]},
  {name:'算法生成',pages:[['算法库','算法列表'],['训练任务','训练任务']]},
  {name:'数据中心',pages:[['素材库','数据集'],['视频切帧','视频切帧'],['自动标注及清洗','自动标注及清洗'],['标签管理','标签管理']]},
  {name:'高级功能',pages:[['算力与节点','服务节点'],['模型转换环境','部署资源'],['AI 辅助配置','模型配置'],['存储管理','存储配置']]},
  {name:'系统与对接',pages:[['平台对接','平台对接'],['畅联云数据','畅联云数据']]},
];
export function legacyUrl(projectId:string,page:string,algorithmId='',versionId='',action=''){
  return '/?'+new URLSearchParams({spa_handoff:'1',project_id:projectId,page,algorithm_id:algorithmId,version_id:versionId,action});
}
