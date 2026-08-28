export function reportPresentation(report = {}) {
  if (report.report_type === 'algorithm') {
    return {title: '算法综合训练报告', scope: 'algorithm'};
  }
  return {title: '单版本训练报告', scope: 'version'};
}
