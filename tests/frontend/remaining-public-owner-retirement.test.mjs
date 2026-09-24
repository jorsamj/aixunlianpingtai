import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app=await readFile(new URL('../../static/app.js',import.meta.url),'utf8');

test('remaining compatibility actions expose one public owner each',()=>{
  for(const name of [
    'fillTrain','applyAlg','showLog','assignVersion','saveAssign',
    'openExportModel','submitExportModel','openAuditConnect42',
    'openPolicy42','runPolicy42','renderIterationV42',
  ]){
    assert.equal((app.match(new RegExp('window\\.'+name+'\\s*=','g'))||[]).length,1,name);
  }
});

test('historical implementations are isolated instead of overwritten',()=>{
  for(const name of [
    'fillTrainLegacy','applyAlgLegacy','showLogLegacy','assignVersionLegacy',
    'saveAssignLegacy','openExportModelLegacy','submitExportModelLegacy',
    'openAuditConnectLegacy42','openPolicyLegacy42','runPolicyLegacy42','renderIterationLegacyV42',
  ]) assert.match(app,new RegExp('window\\.'+name+'\\s*='));
});
