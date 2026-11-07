import {test, expect} from '@playwright/test';

// An isolated same-origin page loads the actual pinned offline UMD/CSS. It has
// no app entry point, backend data, fake Annotorious or access to private state.
async function openPoc(page) {
  await page.route('**/__annotorious_poc__', route => route.fulfill({contentType:'text/html',body:`<!doctype html>
    <link rel="stylesheet" href="/static/vendor/annotorious/annotorious.css">
    <style>body{margin:0}#viewport{position:absolute;left:40px;top:40px;width:900px;height:650px;overflow:hidden}
    #world{transform-origin:0 0;width:max-content}#image{width:640px;height:480px}</style>
    <div id="viewport"><div id="world"><img id="image" width="640" height="480"></div></div>
    <script src="/static/vendor/annotorious/annotorious.js"></script>`}));
  await page.goto('/__annotorious_poc__');
  await page.evaluate(async () => {
    const image = document.querySelector('#image');
    image.src = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480"><rect width="640" height="480" fill="#e3e8ee"/></svg>');
    await image.decode();
    const adapter = await import('/static/modules/annotation-geometry-adapter.js');
    const component = Annotorious.createImageAnnotator(image, {drawingMode:'drag',autoSave:true,disableUndoRedoKeys:true});
    component.setDrawingTool('rectangle');
    const events = [];
    for (const name of ['createAnnotation','updateAnnotation','deleteAnnotation','selectionChanged'])
      component.on(name, (...args) => events.push({name,args}));
    window.poc = {component,adapter,events};
  });
  await expect(page.locator('svg.a9s-annotationlayer')).toBeVisible();
}

async function dragPixels(page, from, to) {
  const image = await page.locator('#image').boundingBox();
  const point = ([x,y]) => ({x:image.x+x*image.width/640,y:image.y+y*image.height/480});
  const start = point(from), end = point(to);
  await page.mouse.move(start.x,start.y);
  await page.mouse.down();
  await page.mouse.move(end.x,end.y,{steps:8});
  await page.mouse.up();
}

async function geometry(page) {
  return page.evaluate(() => poc.component.getAnnotations()[0]?.target.selector.geometry);
}

test('official offline Annotorious draws, selects, moves, resizes and preserves original pixels after viewport transforms', async ({page}) => {
  await openPoc(page);
  await dragPixels(page,[50,60],[150,140]);
  await expect.poll(async () => (await geometry(page))?.w).toBeCloseTo(100,3);
  // The public auto-save event is debounced. Observe the first creation before
  // switching tools/selection, so later updates cannot coalesce that evidence.
  await expect.poll(() => page.evaluate(() => poc.events.filter(e => e.name === 'createAnnotation').length)).toBe(1);
  const id = await page.evaluate(() => poc.component.getAnnotations()[0].id);
  expect(id).toBeTruthy();
  await page.evaluate(id => {poc.component.setDrawingEnabled(false);poc.component.setSelected(id,true);},id);
  // Handle.svelte omits corner-specific classes in its touch-device branch.
  // The edge handle is shared by both actual editor renderings.
  await expect(page.locator('.a9s-edge-handle-right')).toHaveCount(1);
  await expect(page.locator('.drawing [role="button"]').first()).toBeVisible();
  await dragPixels(page,[100,100],[120,130]);
  await expect.poll(async () => (await geometry(page))?.x).toBeCloseTo(70,3);
  await expect.poll(async () => (await geometry(page))?.y).toBeCloseTo(90,3);
  await dragPixels(page,[170,170],[210,200]);
  await expect.poll(async () => (await geometry(page))?.w).toBeCloseTo(140,3);
  await expect.poll(async () => (await geometry(page))?.h).toBeCloseTo(110,3);
  await page.evaluate(() => {poc.component.cancelSelected();document.querySelector('#world').style.transform='translate(35px,25px) scale(1.25)';});
  await page.evaluate(id => poc.component.setSelected(id,true),id);
  await dragPixels(page,[120,130],[140,150]);
  await expect.poll(async () => (await geometry(page))?.x).toBeCloseTo(90,3);
  await expect.poll(async () => (await geometry(page))?.y).toBeCloseTo(110,3);
  await dragPixels(page,[230,220],[250,240]);
  await expect.poll(async () => (await geometry(page))?.w).toBeCloseTo(160,3);
  await expect.poll(async () => (await geometry(page))?.h).toBeCloseTo(130,3);
  const movedGt = await page.evaluate(() => poc.adapter.fromAnno(poc.component.getAnnotations()[0],{
    width:640,height:480,originalBoxesById:new Map(),newLabel:{code:'person',class_id:7},
  }));
  expect(movedGt.x1).toBeCloseTo(90,3);
  expect(movedGt.y1).toBeCloseTo(110,3);
  expect(movedGt.x2).toBeCloseTo(250,3);
  expect(movedGt.y2).toBeCloseTo(240,3);
  await page.evaluate(() => {poc.component.cancelSelected();poc.component.setDrawingEnabled(true);});
  await dragPixels(page,[300,260],[380,320]);
  await expect.poll(() => page.evaluate(() => poc.component.getAnnotations().length)).toBe(2);
  const created = await page.evaluate(() => poc.component.getAnnotations().find(a => a.target.selector.geometry.x > 280));
  expect(created.target.selector.geometry.x).toBeCloseTo(300,3);
  expect(created.target.selector.geometry.w).toBeCloseTo(80,3);
  expect(created.id).not.toBe(id);
  await expect.poll(() => page.evaluate(() => poc.events.filter(e => e.name === 'createAnnotation').length)).toBe(2);
});

test('official setAnnotations round trip, visible subset filtering, cancel and destroy use only public APIs', async ({page}) => {
  await openPoc(page);
  const result = await page.evaluate(() => {
    const original = [
      {id:'old-a',class_id:7,label:'person',x1:30.1,y1:40.2,x2:160.3,y2:170.4,source:'manual',provenance:{reviewer:'human'}},
      {id:'old-b',class_id:19,label:'helmet',x1:300,y1:200,x2:360,y2:270,source:'ai_candidate_reviewed'},
    ];
    const size = {width:640,height:480};
    const map = new Map(original.map(b => [b.id,b]));
    poc.component.setAnnotations(original.map(b => poc.adapter.toAnno(b,size)),true);
    const roundTrip = poc.component.getAnnotations().map(a => poc.adapter.fromAnno(a,{...size,originalBoxesById:map}));
    // 3.9.5 setFilter warns without filtering. Use the original GT visible
    // projection: absence from the component makes hidden boxes unselectable.
    poc.component.cancelSelected();
    poc.component.setAnnotations(original.filter(b => b.class_id===7).map(b => poc.adapter.toAnno(b,size)),true);
    poc.component.setSelected('old-b');
    const hiddenSelection = poc.component.getSelected();
    poc.component.cancelSelected();
    poc.component.setVisible(false);
    return {original,roundTrip,hiddenSelection,projected:poc.component.getAnnotations().map(a=>a.id)};
  });
  expect(result.roundTrip).toEqual(result.original);
  expect(result.projected).toEqual(['old-a']);
  expect(result.hiddenSelection).toEqual([]);
  await expect(page.locator('svg.a9s-annotationlayer')).toBeHidden();
  await page.evaluate(() => {poc.component.setVisible(true);poc.component.setDrawingEnabled(true);});
  await expect(page.locator('svg.a9s-annotationlayer')).toBeVisible();
  const image = await page.locator('#image').boundingBox();
  await page.mouse.move(image.x+400,image.y+300);
  await page.mouse.down();
  await page.mouse.move(image.x+450,image.y+350,{steps:4});
  await page.evaluate(() => poc.component.cancelDrawing());
  await page.mouse.up();
  expect(await page.evaluate(() => poc.component.getAnnotations().map(a=>a.id))).toEqual(['old-a']);
  await page.evaluate(() => poc.component.destroy());
  await expect(page.locator('svg.a9s-annotationlayer')).toHaveCount(0);
  await expect(page.locator('#world > #image')).toHaveCount(1);
  const eventCount = await page.evaluate(() => poc.events.length);
  await dragPixels(page,[400,300],[450,350]);
  expect(await page.evaluate(() => poc.events.length)).toBe(eventCount);
});
