import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app=await readFile(new URL('../../static/app.js',import.meta.url),'utf8');

test('resource and deployment public owners are unique',()=>{
  for(const name of ['detectUltra','testPaddle','detectPaddle','quickPaddleDetect','openModelConfigModalV35','testModelConfigV35','createDeployJob','refreshConvertResource428']){
    assert.equal((app.match(new RegExp('window\\.'+name+'\\s*=','g'))||[]).length,1,name);
  }
});

test('M4 contracts are private implementations activated once',()=>{
  assert.match(app,/window\.openModelConfigM4=function\(id=''\)/);
  assert.match(app,/window\.testModelConfigM4=async function\(id\)/);
  assert.match(app,/window\.createDeployJobM4=async function\(\)/);
  assert.match(app,/window\.__m4OpenModelConfig=window\.openModelConfigM4/);
  assert.match(app,/window\.__m4TestModelConfig=window\.testModelConfigM4/);
  assert.match(app,/window\.__m4CreateDeployJob=window\.createDeployJobM4/);
  assert.match(app,/window\.openModelConfigModalV35=window\.__m4OpenModelConfig/);
  assert.match(app,/window\.testModelConfigV35=window\.__m4TestModelConfig/);
  assert.match(app,/window\.createDeployJob=window\.__m4CreateDeployJob/);
});

test('latest resource discovery and conversion resource picker stay public',()=>{
  assert.match(app,/window\.detectPaddle=async function\(\)/);
  assert.match(app,/window\.quickPaddleDetect=async function\(\)/);
  assert.match(app,/window\.refreshConvertResource428=function\(\)/);
});
