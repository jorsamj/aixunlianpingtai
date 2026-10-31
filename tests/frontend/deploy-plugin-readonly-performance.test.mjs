import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const app=readFileSync(new URL('../../app.py',import.meta.url),'utf8');
const section=app.slice(app.indexOf("def v41_deploy_plugins():"),app.indexOf("class V41SdkInstallReq",app.indexOf("def v41_deploy_plugins():")));

test('plugin catalog GET observes recent capability without starting vendor detection',()=>{
  assert.match(section,/conversion_resource_detection import observe/);
  assert.match(section,/resources=\[_deploy_resource_public\(observe\(r\)\)/);
  assert.doesNotMatch(section,/v39_detect_deploy_resource\(/);
  assert.doesNotMatch(section,/_detect_local_deploy_resource\(/);
  assert.match(section,/\['status'\]='ready'/);
});
