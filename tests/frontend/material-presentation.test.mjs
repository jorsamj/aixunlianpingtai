import test from 'node:test';import assert from 'node:assert/strict';
import {boxPercent,fitScale} from '../../static/modules/material-presentation.js';
test('shared image geometry scales x and y independently and rejects malformed boxes',()=>{assert.deepEqual(boxPercent({x1:66,y1:44,x2:330,y2:220},660,440),{left:10,top:10,width:40,height:40});assert.deepEqual(boxPercent({x1:128,y1:96,x2:640,y2:480},1280,960),{left:10,top:10,width:40,height:40});assert.equal(boxPercent({x1:20,y1:30,x2:0,y2:5},100,100),null);assert.equal(fitScale(200,100,1000,2000),0.05)});
