import {test,expect} from '@playwright/test';
import {readFileSync} from 'node:fs';
test('isolated existing model dialog verifies sample and requires human confirmation',async({page},info)=>{
 const source=readFileSync(new URL('../../static/app.js',import.meta.url),'utf8');
 const script=source.slice(source.indexOf('  window.personPromptM4='),source.indexOf('  window.testModelConfigM4='));
 await page.route('http://model-fixture.test/**',route=>route.fulfill({contentType:'text/html',body:'<!doctype html><meta charset="utf-8"><div id="modal"></div>'}));
 await page.goto('http://model-fixture.test/');
 await page.evaluate(()=>{
  window.esc=x=>String(x??'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');window.modal=(title,html)=>document.getElementById('modal').innerHTML=html;
  window.providerNames={local_openai:'本地兼容服务'};window.providerDefaults={local_openai:'http://fixture.invalid'};
  window.state={modelConfigs:[{id:'fixture',name:'隔离样本配置',provider_adapter:'local_openai',provider_type:'local_openai',model_name:'fixture',base_url:'http://fixture.invalid',coordinate_space:'normalized_1000',coordinate_order:'yxyx',annotation_prompt_template:'仅标注 person',api_protocol:'auto',structured_output:'auto'}]};
  window.changeVisionProviderM4=()=>{};window.toast=message=>{throw Error(message)};window.closeModal=()=>{};
  window.api=async(url)=>url.endsWith('confirm-coordinates')?{...state.modelConfigs[0],coordinate_validation:{status:'verified',reason:'已人工确认此真实样本的框位置'}}:{parsed_boxes:[{x1:20,y1:10,x2:80,y2:90,label:'person'}],image_width:100,image_height:100,input_image_url:'data:image/svg+xml,'+encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect width="100" height="100" fill="white"/></svg>'),raw_preview:'{"boxes":[{"x1":100,"y1":200,"x2":900,"y2":800}]}',coordinate_validation:{status:'unverified',reason:'样本解析通过，需人工检查',receipt:'fixture',config_revision:'fixture',sample_sha256:'fixture'}};
 });
 await page.addScriptTag({content:script});await page.evaluate(()=>openModelConfigM4('fixture'));
 await expect(page.locator('#mcCoordinateStatus')).toContainText('未验证');
 await page.locator('summary').click();await expect(page.locator('#mcCoordinateSpace')).toHaveValue('normalized_1000');await expect(page.locator('#mcCoordinateOrder')).toHaveValue('yxyx');
 await page.locator('#mcCoordinateImage').setInputFiles({name:'sample.png',mimeType:'image/png',buffer:Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jNuoAAAAASUVORK5CYII=','base64')});
 await page.locator('#mcCoordinateLabels').fill('person');await page.getByRole('button',{name:'验证坐标',exact:true}).click();
 await expect(page.locator('#mcCoordinateResult rect')).toHaveAttribute('x','20');await expect(page.locator('#mcCoordinateStatus')).toContainText('需人工检查');
 await page.getByRole('button',{name:'框位置正确，确认此配置'}).click();await expect(page.locator('#mcCoordinateStatus')).toContainText('已人工确认');
 await page.screenshot({path:info.outputPath('model-coordinate-isolated.png'),fullPage:true});
});
