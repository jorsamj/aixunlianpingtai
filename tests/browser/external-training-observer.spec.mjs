import {test, expect} from '@playwright/test';

test('external training warning stays singular under real DOM MutationObserver callbacks', async ({page}) => {
  await page.goto('/');
  await expect.poll(() => page.evaluate(() =>
    typeof state !== 'undefined' && !!state.uiReady && !!window.PlatformCore?.runtime?.externalAlgorithmPlatformRuntime
  ), {timeout: 20_000}).toBe(true);

  await page.evaluate(() => {
    state.algorithms = [
      ...(state.algorithms || []).filter(row => row.id !== 'observer-external'),
      {id: 'observer-external', source_type: 'EXTERNAL', provider_type: 'CHANG_LIAN', external_active: false,
        external_master_data_digest: 'observer-digest',
        external_analyses: [{analysis_id: 'visual-1', analysis_type: '1', status: '1'}]},
    ];
    state.trainingDraft = {...state.trainingDraft, algorithmId: 'observer-external'};
    window.__observerReadinessCalls = 0;
    window.TrainingSubmitRuntime = {updateReadiness() { window.__observerReadinessCalls++; }};
    const form = document.createElement('div');
    form.className = 'train429-create';
    form.id = 'observer-training-fixture';
    document.body.appendChild(form);
  });

  const form = page.locator('#observer-training-fixture');
  await expect(form.locator('[data-external-training-blocked]')).toHaveCount(1);
  await page.evaluate(() => {
    const form = document.querySelector('#observer-training-fixture');
    for (let i = 0; i < 60; i++) form.appendChild(document.createElement('span'));
  });
  await expect(form.locator('[data-external-training-blocked]')).toHaveCount(1);
  expect(await page.evaluate(() => window.__observerReadinessCalls)).toBe(1);

  await page.evaluate(() => {
    state.trainingDraft.algorithmId = 'local-observer';
    document.querySelector('#observer-training-fixture').appendChild(document.createElement('span'));
  });
  await expect(form.locator('[data-external-training-blocked]')).toHaveCount(0);
  expect(await page.evaluate(() => window.__observerReadinessCalls)).toBe(2);
});
