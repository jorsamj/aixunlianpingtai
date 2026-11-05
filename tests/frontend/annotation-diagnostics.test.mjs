import test from 'node:test';
import assert from 'node:assert/strict';
import {diagnosticBoxes,renderAnnotationDiagnostics} from '../../static/modules/annotation-diagnostics.js';
const box={label:'person',x1:100,y1:200,x2:300,y2:600};
const d={contract:{coordinate_space:'normalized_1000'},geometry:{original_width:1920,original_height:1080},raw_candidates:[box],converted_boxes:[{...box,x1:192,y1:216,x2:576,y2:648}]};
test('diagnostic comparison respects declared ranges and original dimensions',()=>{
 assert.deepEqual(diagnosticBoxes(d,'raw'),[{label:'person',left:10,top:20,width:20,height:40}]);
 assert.deepEqual(diagnosticBoxes(d,'converted'),diagnosticBoxes(d,'raw'));
 assert.deepEqual(diagnosticBoxes({...d,contract:{coordinate_space:'normalized_1000',coordinate_order:'yxyx'},raw_candidates:[{...box,x1:200,y1:100,x2:600,y2:300}]},'raw'),diagnosticBoxes(d,'raw'));
 assert.deepEqual(diagnosticBoxes({...d,raw_candidates:[{...box,x1:null}]},'raw'),[]);
 assert.deepEqual(diagnosticBoxes({...d,contract:{}},'raw'),[]);
 assert.deepEqual(diagnosticBoxes(d,'final',[]),[]);
});
test('diagnostics bound structured data, escape text and never expose arbitrary response fields',()=>{
 const html=renderAnnotationDiagnostics({...d,model_name:'<script>',raw_response:'secret',token:'secret',raw_candidates:Array(120).fill(box)});
 assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('secret'));
 assert.equal((html.match(/<tr><td>person/g)||[]).length,100);
 assert.ok(html.includes('需人工核查'));assert.ok(html.includes('准确率'));
});
