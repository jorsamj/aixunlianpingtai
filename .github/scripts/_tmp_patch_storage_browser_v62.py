from pathlib import Path

path = Path('tests/browser/navigation-stability.spec.mjs')
text = path.read_text(encoding='utf-8')

old_route = """  await page.route(/\\/api\\/v61\\/projects\\/[^/]+\\/storage-imports\\/storage-r20g$/, async route => {
    requests.push(`GET ${new URL(route.request().url()).pathname}`);
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      task_id: 'storage-r20g', status: 'SUCCEEDED', stage: 'DONE', result: {imported: 3, indexed: 3},
    })});
  });
"""
new_route = """  await page.route(/\\/api\\/v62\\/projects\\/[^/]+\\/tasks\\/storage-r20g$/, async route => {
    requests.push(`GET ${new URL(route.request().url()).pathname}`);
    await route.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify({
      task_id: 'storage-r20g', status: 'SUCCEEDED', persisted_status: 'SUCCEEDED',
      phase: 'DONE', progress_percent: 100, result: {imported: 3, indexed: 3},
    })});
  });
"""
assert old_route in text, 'legacy v61 storage-import GET fixture not found'
text = text.replace(old_route, new_route, 1)

old_expect = """  expect(requests.filter(row => row.includes('storage-r20g'))).toEqual([
    expect.stringMatching(/^POST \\/api\\/v61\\/projects\\/[^/]+\\/storage-imports\\/storage-r20g\\/confirm$/),
    expect.stringMatching(/^GET \\/api\\/v61\\/projects\\/[^/]+\\/storage-imports\\/storage-r20g$/),
  ]);
"""
new_expect = """  expect(requests.filter(row => row.includes('storage-r20g'))).toEqual([
    expect.stringMatching(/^POST \\/api\\/v61\\/projects\\/[^/]+\\/storage-imports\\/storage-r20g\\/confirm$/),
    expect.stringMatching(/^GET \\/api\\/v62\\/projects\\/[^/]+\\/tasks\\/storage-r20g$/),
  ]);
"""
assert old_expect in text, 'legacy v61 storage-import request expectation not found'
text = text.replace(old_expect, new_expect, 1)

path.write_text(text, encoding='utf-8')
