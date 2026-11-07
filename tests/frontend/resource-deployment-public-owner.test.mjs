import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app=await readFile(new URL('../../static/app.js',import.meta.url),'utf8');

test('resource and canonical conversion public owners are unique',()=>{
  for(const name of ['detectUltra','testPaddle','detectPaddle','quickPaddleDetect','openModelConfigModalV35','testModelConfigV35','refreshConvertResource428','submitConvert428']){
    assert.equal((app.match(new RegExp('window\\.'+name+'\\s*=','g'))||[]).length,1,name);
  }
});

test('M4 model contracts are private implementations activated once',()=>{
  assert.match(app,/window\.openModelConfigM4=function\(id=''\)/);
  assert.match(app,/window\.testModelConfigM4=async function\(id\)/);
  assert.match(app,/window\.__m4OpenModelConfig=window\.openModelConfigM4/);
  assert.match(app,/window\.__m4TestModelConfig=window\.testModelConfigM4/);
  assert.match(app,/window\.openModelConfigModalV35=window\.__m4OpenModelConfig/);
  assert.match(app,/window\.testModelConfigV35=window\.__m4TestModelConfig/);
});

test('retired deployment-page creation owners stay removed',()=>{
  assert.equal(app.includes('window.createDeployJobM4='),false);
  assert.equal(app.includes('window.__m4CreateDeployJob'),false);
  assert.equal(app.includes('window.createDeployJob='),false);
  assert.equal(app.includes('window.createDeployJobLegacyV39='),false);
  assert.equal((app.match(/window\.submitConvert428=/g)||[]).length,1);
});

test('latest resource discovery and conversion resource picker stay public',()=>{
  assert.match(app,/window\.detectPaddle=async function\(\)/);
  assert.match(app,/window\.quickPaddleDetect=async function\(\)/);
  assert.match(app,/window\.refreshConvertResource428=function\(\)/);
});
