import {expect} from '@playwright/test';

// Configuration-only fixtures must remain quiet. Opening configuration is not
// authorization to run formal admission or dismiss a diagnostic on the user's behalf.
export async function returnToTrainingConfiguration(page){
  const draft=await page.evaluate(()=>window.TrainingDraftRuntime.current());
  await page.evaluate(()=>window.TrainingSubmitRuntime?.updateReadiness?.());
  await expect(page.locator('[data-training-admission-dialog]')).toHaveCount(0);
  await expect(page.locator('[data-training-admission-open]:visible')).toHaveCount(0);
  expect(await page.evaluate(()=>window.TrainingDraftRuntime.current())).toEqual(draft);
}
