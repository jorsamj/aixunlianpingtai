import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app=await readFile(new URL('../../static/app.js',import.meta.url),'utf8');
const recovery=await readFile(new URL('../../static/modules/training-recovery-runtime.js',import.meta.url),'utf8');

test('remaining compatibility actions expose one public owner each',()=>{
  for(const name of [
    'fillTrain','applyAlg','assignVersion','saveAssign',
    'openExportModel','submitExportModel','openAuditConnect42',
    'openPolicy42','runPolicy42','renderIterationV42',
  ]){
    assert.equal((app.match(new RegExp('window\\.'+name+'\\s*=','g'))||[]).length,1,name);
  }
  assert.equal((app.match(/window\.showLog\s*=/g)||[]).length,0,'showLog');
  assert.match(recovery,/window\.showTrainLog423\s*=\s*taskId\s*=>\s*openDetail/);
});

test('retired training implementations stay removed instead of surviving as compatibility owners',()=>{
  for(const name of [
    'fillTrainLegacy','applyAlgLegacy','showLogLegacy',
  ]) assert.equal(app.includes('window.'+name+'='),false,name);
});

test('still-used historical implementations remain isolated instead of overwritten',()=>{
  for(const name of [
    'assignVersionLegacy','saveAssignLegacy','openExportModelLegacy','submitExportModelLegacy',
    'openAuditConnectLegacy42','openPolicyLegacy42','runPolicyLegacy42','renderIterationLegacyV42',
  ]) assert.match(app,new RegExp('window\\.'+name+'\\s*='));
});
