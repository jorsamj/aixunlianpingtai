import {test,expect} from '@playwright/test';
import {fixture} from './fixture';

test('real offline candidate editor keeps one mount across owner notifications and releases on image change',async({page})=>{
 const writes:string[]=[];
 await page.route('**/editor-fixture*',route=>route.fulfill({contentType:'text/html',body:fixture}));
 await page.route('**/api/**',route=>{if(new URL(route.request().url()).pathname==='/api/auth/session')return route.fulfill({json:{authenticated:true,user:{username:'隔离用户'}}});if(route.request().method()!=='GET')writes.push(route.request().method()+' '+route.request().url());return route.fulfill({json:{ok:true,items:[],total:0,page:1,page_size:10,revision:1,templates:[]}})});
 await page.route('**/isolated-editor-image-*.svg',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480"><rect width="640" height="480" fill="#e8eef5"/><rect x="200" y="160" width="140" height="160" fill="#7191a8"/><text x="20" y="450" font-size="20">ISOLATED TEST IMAGE — NOT PRODUCTION</text></svg>'}));
 await page.goto('/editor-fixture?vue_ai_tasks=1');await page.waitForFunction(()=>window.fixtureReady);
 await page.evaluate(async()=>{
  const {createAnnotoriousEditor}=await import('/static/modules/annotorious-editor.js');
  const host=document.getElementById('view')!;host.replaceChildren();host.style.height='90vh';host.style.padding='0';
  const listeners=new Set<(value:any)=>void>(),labels=[{code:'smoke',display_name:'烟雾',class_id:0}],owner={id:'one',boxes:[] as any[],pending:false,dirty:false,handle:null as any,mountCount:0,destroyCount:0,notifications:0};
  const signal=new AbortController();
  function editSnapshot(){return {imageId:owner.id,url:`/isolated-editor-image-${owner.id}.svg`,filename:`隔离候选-${owner.id}.svg`,width:640,height:480,boxes:owner.boxes.map(box=>({...box})),labels,activeBox:null,labelCode:'smoke',dirty:owner.dirty,saving:false,pending:owner.pending,view:owner.handle?.snapshot()}}
  function snapshot(){return {taskId:'isolated-task',projectId:'p',items:[],offset:0,limit:24,total:0,filter:'all',summary:{},loading:false,selection:{count:0},busy:false,labels,ambiguity:{mode:'manual',label:'',threshold:'0.9',scanning:false,saving:false},edit:editSnapshot()}}
  function publish(){owner.notifications++;for(const listener of listeners)listener(snapshot())}
  const noop=()=>{};
  const editor={async mount(elements:any){owner.mountCount++;owner.pending=true;publish();const handle=await createAnnotoriousEditor({...elements,signal:signal.signal,getBoxes:()=>owner.boxes,getLabels:()=>labels,getLabel:()=>labels[0],getSelectedId:()=>null,isActive:()=>true,onCommit:(boxes:any[])=>{owner.boxes=boxes.map(box=>({...box}));owner.dirty=true;publish()},onViewportChange:publish});owner.handle=handle;owner.pending=false;publish();return handle},release(handle:any){if(handle){handle.destroy();owner.destroyCount++;if(owner.handle===handle)owner.handle=null}},actions:{mode:(mode:string)=>{owner.handle?.setMode(mode);publish()},label:noop,select:noop,reclass:noop,remove:noop,undo:noop,redo:noop,visibility:noop,filter:noop,zoom:noop,fit:noop,resetZoom:noop,save:noop,reload:noop,cancel:noop}};
  const context={snapshot,subscribe(listener:(value:any)=>void){listeners.add(listener);listener(snapshot());return()=>listeners.delete(listener)},editor,actions:new Proxy({},{get:()=>noop})};
  window.editorTest={owner,publish,switchImage(){owner.id='two';owner.boxes=[];publish()},dispose:null as any};window.editorTest.dispose=await window.preview.mountAiReview(host,context);
 });
 const editor=page.getByRole('region',{name:'AI候选标注编辑'});
 await expect(page.locator('svg.a9s-annotationlayer')).toHaveCount(1);await expect(page.getByRole('button',{name:'画框',exact:true})).toBeEnabled();
 await page.evaluate(()=>{for(let i=0;i<8;i++){window.editorTest.owner.pending=i%2===0;window.editorTest.publish()}window.editorTest.owner.pending=false;window.editorTest.publish()});
 await expect(page.getByRole('button',{name:'画框',exact:true})).toBeEnabled();expect(await page.evaluate(()=>window.editorTest.owner.mountCount)).toBe(1);await expect(page.locator('svg.a9s-annotationlayer')).toHaveCount(1);
 await page.getByRole('button',{name:'画框',exact:true}).click();
 const img=page.locator('.editor-world img'),rect=await img.boundingBox(),size=await img.evaluate((element:HTMLImageElement)=>({width:element.naturalWidth,height:element.naturalHeight}));expect(size).toEqual({width:640,height:480});
 const point=(x:number,y:number)=>({x:rect!.x+rect!.width*x/size.width,y:rect!.y+rect!.height*y/size.height});const a=point(70,60),b=point(180,130);
 await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(b.x,b.y,{steps:8});await page.mouse.up();
 await expect.poll(()=>page.evaluate(()=>window.editorTest.owner.boxes.length)).toBe(1);await expect(page.locator('.a9s-annotation[data-id]')).toHaveCount(1);const box=await page.evaluate(()=>window.editorTest.owner.boxes[0]);expect(box.label).toBe('smoke');expect(box.x1).toBeCloseTo(70,0);expect(box.y1).toBeCloseTo(60,0);expect(box.x2).toBeCloseTo(180,0);expect(box.y2).toBeCloseTo(130,0);
 expect(await page.evaluate(()=>window.editorTest.owner.mountCount)).toBe(1);expect(await page.evaluate(()=>window.editorTest.owner.notifications)).toBeGreaterThan(8);
 await page.evaluate(()=>window.editorTest.switchImage());await expect(page.getByRole('heading',{name:'隔离候选-two.svg',exact:true})).toBeVisible();await expect(page.getByRole('button',{name:'画框',exact:true})).toBeEnabled();await expect(page.locator('svg.a9s-annotationlayer')).toHaveCount(1);expect(await page.evaluate(()=>window.editorTest.owner.mountCount)).toBe(2);expect(await page.evaluate(()=>window.editorTest.owner.destroyCount)).toBe(1);
 await expect(page.locator('link[data-annotorious-css]')).toHaveCount(1);await expect(page.locator('script[src*="/vendor/annotorious/annotorious.js"]')).toHaveCount(1);
 await page.evaluate(()=>window.editorTest.dispose());await expect(page.locator('svg.a9s-annotationlayer')).toHaveCount(0);expect(await page.evaluate(()=>window.editorTest.owner.destroyCount)).toBe(2);expect(writes).toEqual([]);
});
