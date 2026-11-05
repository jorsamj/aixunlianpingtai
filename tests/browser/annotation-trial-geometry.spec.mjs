import {test,expect} from '@playwright/test';

test('trial original pixel overlays survive aspect ratio, container resize and zoom',async({page})=>{
  await page.goto('/');
  for(const [width,height] of [[1280,960],[1080,1920],[640,640],[2560,720]]){
    await page.evaluate(async({width,height})=>{
      window.disposeTrial?.();document.body.innerHTML='<div id="trial" style="width:900px"></div>';
      const {mountTrial}=await import('/static/modules/annotation-trial.js?v=20261105a');
      const boxes=[[0,0,.1,.1],[.9,.9,1,1],[.4,.4,.6,.6]].map(([a,b,c,d],i)=>({id:String(i),label:'person',x1:a*width,y1:b*height,x2:c*width,y2:d*height}));
      const url='data:image/svg+xml,'+encodeURIComponent(`<svg xmlns="http://www.w3.org/2000/svg" width="${width}" height="${height}"><rect width="100%" height="100%" fill="silver"/></svg>`);
      window.disposeTrial=await mountTrial(document.getElementById('trial'),{image:{id:'synthetic',width,height,url},boxes,baseline:{boxes}},{labels:[{code:'person'}],compareUrl:'/unused',active:()=>true,signal:new AbortController().signal});
    },{width,height});
    await expect(page.locator('.a9s-annotation[data-id]')).toHaveCount(3);
    for(const containerWidth of [900,460]){
      await page.locator('#trial').evaluate((el,w)=>el.style.width=w+'px',containerWidth);
      await page.locator('[data-trial-action=fit]').click();
      const check=async()=>page.evaluate(()=>{
        const image=document.querySelector('[data-image]').getBoundingClientRect();
        return [...document.querySelectorAll('.a9s-annotation[data-id]')].map(el=>{const r=el.getBoundingClientRect();return [(r.left-image.left)/image.width,(r.top-image.top)/image.height,r.width/image.width,r.height/image.height]});
      });
      for(const zoom of [false,true]){
        if(zoom)await page.locator('[data-trial-action=zoom]').click();
        const rows=await check();
        for(const expected of [[0,0,.1,.1],[.9,.9,.1,.1],[.4,.4,.2,.2]]){
          expect(rows.some(row=>row.every((value,i)=>Math.abs(value-expected[i])<.015))).toBe(true);
        }
      }
    }
  }
});
