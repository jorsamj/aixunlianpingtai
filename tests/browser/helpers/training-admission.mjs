import {expect} from '@playwright/test';

// Existing configuration-only fixtures intentionally include empty or synthetic
// selections. Acknowledge the required diagnostic as a user would; never disable
// admission or substitute successful backend truth to reach the configuration.
export async function returnToTrainingConfiguration(page){
  await expect.poll(()=>page.evaluate(()=>{
    const truth=window.TrainingMaterialSummaryRuntime?.compatibilityFor?.();
    return Boolean(truth&&(truth.ready||truth.error));
  })).toBe(true);
  await page.evaluate(()=>window.TrainingSubmitRuntime?.updateReadiness?.());
  const diagnostic=page.locator('[data-training-admission-dialog]');
  if(await diagnostic.count()){
    const draft=await page.evaluate(()=>window.TrainingDraftRuntime.current());
    await expect(diagnostic).toContainText('训练暂不可开始');
    await diagnostic.getByRole('button',{name:'返回训练配置',exact:true}).click();
    expect(await page.evaluate(()=>window.TrainingDraftRuntime.current())).toEqual(draft);
  }
}
