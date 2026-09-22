import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');

test('final deployment test uses persistent runtime worker API and exposes timing dimensions',()=>{
  const marker=source.lastIndexOf('Persistent deployment tests');
  assert.ok(marker>0);
  const finalLayer=source.slice(marker);
  assert.match(finalLayer,/api\/v61\/projects/);
  assert.doesNotMatch(finalLayer,/api\/v12\/projects/);
  assert.match(finalLayer,/preprocess_ms/);
  assert.match(finalLayer,/inference_ms/);
  assert.match(finalLayer,/postprocess_ms/);
});

test('final deployment test consumes unified durable queue and progress truth while active',()=>{
  const marker=source.lastIndexOf('Persistent deployment tests');
  assert.ok(marker>0);
  const finalLayer=source.slice(marker);
  assert.match(finalLayer,/PlatformCore\?\.deployment\?\.deploymentTaskView/);
  assert.match(finalLayer,/PlatformCore\.taskPoller\.waitForTaskTerminal/);
  assert.match(finalLayer,/registry:window\.PollRegistryRuntime/);
  assert.match(finalLayer,/\/api\/v62\/projects\/\$\{pid\(\)\}\/tasks\//);
  assert.match(finalLayer,/runtimeText/);
  assert.doesNotMatch(finalLayer,/\['QUEUED','RUNNING','CANCEL_REQUESTED'\]\.includes\(task\.status\)/);
});


test('rockchip conversion UI only permits RK3568 and RK3576',()=>{
  assert.doesNotMatch(source,/rk3588/i);
  assert.match(source,/瑞芯微转换仅支持 RK3568 或 RK3576/);
  assert.match(source,/rk3568/);
  assert.match(source,/rk3576/);
});


test('persistent deployment progress patches a stable compositor-friendly node',()=>{
  const marker=source.lastIndexOf('Persistent deployment tests');
  assert.ok(marker>0);
  const finalLayer=source.slice(marker);
  assert.match(finalLayer,/data-deployment-live-list/);
  assert.match(finalLayer,/data-deployment-live-id/);
  assert.match(finalLayer,/data-deployment-live-bar/);
  assert.match(finalLayer,/bar\.style\.transform='scaleX\('/);
  assert.doesNotMatch(finalLayer,/output\.innerHTML=\`<div class="loading">真实 Runtime 测试中/);
});

test('deployment pages paint cached low-frequency data before background refresh',()=>{
  assert.match(source,/const DEPLOY_CACHE_TTL_MS=10\*60\*1000/);
  assert.match(source,/function restoreDeployCacheV39\(\)/);
  assert.match(source,/function primeDeployRenderV39\(page,renderer,firstLoadText\)/);
  assert.match(source,/if\(!primeDeployRenderV39\('部署资源'/);
  assert.match(source,/if\(!primeDeployRenderV39\('部署转换'/);
  assert.match(source,/if\(!primeDeployRenderV39\('部署产物'/);
  assert.doesNotMatch(source,/正在读取部署资源\.\.\./);
  assert.doesNotMatch(source,/正在读取模型与部署资源\.\.\./);
  assert.doesNotMatch(source,/正在读取部署产物\.\.\./);
});


test('deployment plugin page restores only a sanitized persisted card snapshot',()=> {
  assert.match(source,/const DEPLOY_PLUGIN_CACHE_KEY='cl_deploy_plugins_v41_snapshot'/);
  assert.match(source,/function restoreDeployPluginCacheV41\(\)/);
  assert.match(source,/function persistDeployPluginCacheV41\(\)/);
  assert.match(source,/restoreDeployPluginCacheV41\(\);/);
  assert.match(source,/state\.deployPluginsLoadedAt>0\|\|\(state\.deployPlugins\|\|\[\]\)\.length>0/);
  const shapeStart=source.indexOf('const deployPluginCacheRowV41=');
  const shapeEnd=source.indexOf('function restoreDeployPluginCacheV41()',shapeStart);
  assert.ok(shapeStart>=0&&shapeEnd>shapeStart);
  const shape=source.slice(shapeStart,shapeEnd);
  assert.match(shape,/id:p\?\.id/);
  assert.match(shape,/configured_count/);
  assert.doesNotMatch(shape,/resources/);
  assert.doesNotMatch(shape,/api_key|secret|token/i);
});

test('deployment plugin cache is invalidated by deployment resource mutations',()=> {
  assert.match(source,/window\.invalidateDeployPluginCacheV41=\(\)=>/);
  assert.ok((source.match(/window\.invalidateDeployPluginCacheV41\?\.\(\)/g)||[]).length>=5);
});


test('deployment first-render revalidation is single-flight across canonical rerenders',()=> {
  assert.match(source,/let deployRenderRefreshPromise=null/);
  assert.match(source,/let deployRenderRefreshProjectId=''/);
  assert.match(source,/function refreshDeployForRenderV39\(page,renderer\)/);
  assert.match(source,/if\(!task\|\|deployRenderRefreshProjectId!==projectId\)/);
  assert.match(source,/task=Promise\.resolve\(loadDeployData\(true\)\)/);
  const primeStart=source.indexOf('function primeDeployRenderV39(page,renderer,firstLoadText)');
  const primeEnd=source.indexOf('async function loadDeployData(force=false)',primeStart);
  assert.ok(primeStart>=0&&primeEnd>primeStart);
  const prime=source.slice(primeStart,primeEnd);
  assert.ok((prime.match(/refreshDeployForRenderV39\(page,renderer\)/g)||[]).length>=2);
  assert.doesNotMatch(prime,/void loadDeployData\(true\)\.then/);
});
