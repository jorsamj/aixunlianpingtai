import {test, expect} from '@playwright/test';

async function waitForApp(page) {
  await expect.poll(async () => page.evaluate(() => Boolean(window.PlatformCore))).toBe(true);
}

test('training dialog uses canonical wrapper-free label lifecycle and sole submit path', async ({page}) => {
  const unique = Date.now().toString(36);
  const projectName = `e2e-training-label-${unique}`;
  const createResponse = await page.request.post('/api/projects', {data: {name: projectName}});
  expect(createResponse.ok()).toBeTruthy();
  const project = await createResponse.json();

  await page.addInitScript(projectId => {
    localStorage.setItem('mc_train_ui_state_v34', JSON.stringify({projectId, page: '算法列表'}));
  }, project.id);

  await page.goto('/');
  await waitForApp(page);
  await expect.poll(async () => page.evaluate(() => window.TrainingDraftRuntime?.build || null))
    .toBe('training-draft-runtime-422516');
  await expect.poll(async () => page.evaluate(() => window.TrainingLabelRuntime?.build || null))
    .toBe('module-422513');
  await expect.poll(async () => page.evaluate(() => window.TrainingSubmitRuntime?.build || null))
    .toBe('training-submit-422505');
  expect(await page.evaluate(() => ({
    draftOwnsNetwork: window.TrainingDraftRuntime.state().networkOwner,
    draftOwnsClassicWrapper: window.TrainingDraftRuntime.state().classicWrapperOwner,
    labelOwnsClassicWrapper: window.TrainingLabelRuntime.state().classicWrapperOwner,
    labelOwnsTimers: window.TrainingLabelRuntime.state().timerOwner,
    submitOwnsNetwork: window.TrainingSubmitRuntime.state().networkOwner,
  }))).toEqual({
    draftOwnsNetwork: false,
    draftOwnsClassicWrapper: false,
    labelOwnsClassicWrapper: false,
    labelOwnsTimers: false,
    submitOwnsNetwork: true,
  });

  await page.request.delete(`/api/projects/${project.id}`);
});
