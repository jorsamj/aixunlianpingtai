import {test, expect} from '@playwright/test';
import {mkdir, writeFile} from 'node:fs/promises';
import {dirname} from 'node:path';

// 13C-04C: isolated Chrome observability. No application-side instrumentation,
// production data, state mutation, artificial latency, or performance pass line.
const PERFORMANCE_SCOPE = 'isolated-chrome-fixture-not-production';
const APP_ASSET = '/static/app.js';
const MAIN_ASSET = '/static/main.mjs';

async function saveEvidence(testInfo, filename, value) {
  const file = testInfo.outputPath(filename);
  await mkdir(dirname(file), {recursive:true});
  await writeFile(file, JSON.stringify(value, null, 2) + '\n', 'utf8');
  await testInfo.attach(filename, {path:file, contentType:'application/json'});
}

function quantile(values, ratio) {
  if (!values.length) return null;
  const sorted = values.slice().sort((a,b)=>a-b);
  return Math.round(sorted[Math.ceil(ratio*sorted.length)-1]*10)/10;
}

async function installLongTaskObserver(page) {
  await page.addInitScript(() => {
    window.__frontendProfileLongTasks = [];
    try {
      const observer = new PerformanceObserver(list => {
        for (const item of list.getEntries()) {
          window.__frontendProfileLongTasks.push({
            startMs: Math.round(item.startTime*10)/10,
            durationMs: Math.round(item.duration*10)/10
          });
        }
      });
      observer.observe({type:'longtask', buffered:true});
    } catch (_) {
      // The browser's lack of support is recorded, not assumed to mean zero work.
      window.__frontendProfileLongTasks = null;
    }
  });
}

async function readBrowserSnapshot(page) {
  return page.evaluate(() => {
    const nav = performance.getEntriesByType('navigation')[0] || {};
    const paint = performance.getEntriesByType('paint').find(row => row.name === 'first-contentful-paint');
    const scriptRows = performance.getEntriesByType('resource')
      .filter(row => {
        const url = new URL(row.name, location.origin);
        return url.origin === location.origin && /^\/static\/.*\.(?:m?js)$/.test(url.pathname);
      })
      .map(row => {
        const url = new URL(row.name);
        return {
          path: url.pathname,
          transferBytes: Math.max(0, Math.round(row.transferSize || 0)),
          decodedBytes: Math.max(0, Math.round(row.decodedBodySize || 0)),
          durationMs: Math.round(row.duration*10)/10
        };
      });
    const total = key => scriptRows.reduce((sum,row)=>sum+row[key],0);
    const app = scriptRows.find(row=>row.path === '/static/app.js') || null;
    const main = scriptRows.find(row=>row.path === '/static/main.mjs') || null;
    const tasks = window.__frontendProfileLongTasks;
    return {
      scope:'isolated-chrome-fixture-not-production',
      page:String(state.page || ''),
      uiReady:Boolean(state.uiReady),
      readyAtMs:Math.round(performance.now()*10)/10,
      domContentLoadedMs:Math.round((nav.domContentLoadedEventEnd || 0)*10)/10,
      loadEventMs:Math.round((nav.loadEventEnd || 0)*10)/10,
      firstContentfulPaintMs:paint ? Math.round(paint.startTime*10)/10 : null,
      scriptResources:scriptRows.length,
      scriptTransferBytes:total('transferBytes'),
      scriptDecodedBytes:total('decodedBytes'),
      appScript:app,
      mainScript:main,
      longTasksSupported:Array.isArray(tasks),
      longTasks:tasks || [],
      // Asset paths only; no project IDs, user IDs, request bodies, or auth.
      largestScripts:scriptRows.sort((a,b)=>b.decodedBytes-a.decodedBytes).slice(0,8),
    };
  });
}

function numericMetrics(data) {
  const names = new Set(['ScriptDuration','TaskDuration','LayoutDuration','RecalcStyleDuration','JSHeapUsedSize','Nodes']);
  return Object.fromEntries((data?.metrics||[]).filter(row=>names.has(row.name)).map(row=>[row.name, row.value]));
}

function usedCoverageChars(functions,totalChars) {
  // Playwright JSCoverage reports V8 nested function ranges, not CSS ranges.
  // The most specific live range decides whether each span was executed.
  const segments=[];
  for(const fn of functions||[]){
    for(const range of fn.ranges||[]){
      const start=Math.max(0,Math.min(totalChars,Number(range.startOffset)));
      const end=Math.max(0,Math.min(totalChars,Number(range.endOffset)));
      if(Number.isFinite(start)&&Number.isFinite(end)&&end>start){
        segments.push({start,end,count:Number(range.count)||0,length:end-start});
      }
    }
  }
  if(!segments.length)return null;
  const events=[];
  for(let i=0;i<segments.length;i++){
    events.push({at:segments[i].start,type:1,index:i});
    events.push({at:segments[i].end,type:-1,index:i});
  }
  events.sort((a,b)=>a.at-b.at||a.type-b.type);
  const active=new Set();
  let previous=0,used=0,index=0;
  while(index<events.length){
    const position=events[index].at;
    if(position>previous&&active.size){
      let mostSpecific=null;
      for(const key of active){
        const span=segments[key];
        if(!mostSpecific||span.length<mostSpecific.length||
          (span.length===mostSpecific.length&&span.count<mostSpecific.count))mostSpecific=span;
      }
      if(mostSpecific?.count>0)used+=position-previous;
    }
    while(index<events.length&&events[index].at===position){
      const {type,index:rangeIndex}=events[index];
      if(type>0)active.add(rangeIndex);else active.delete(rangeIndex);
      index++;
    }
    previous=position;
  }
  return used;
}

test('13C-04C measures independent cold and cache-preserving Chrome startups', async ({page}, testInfo) => {
  test.setTimeout(60_000);
  const errors=[];
  page.on('pageerror', error=>errors.push(error.message));
  await installLongTaskObserver(page);
  const session=await page.context().newCDPSession(page);
  await session.send('Network.enable');
  await session.send('Performance.enable');
  const samples=[];
  try{
    for(let index=0;index<5;index++){
      if(index<3)await session.send('Network.clearBrowserCache');
      const beforeMetrics=numericMetrics(await session.send('Performance.getMetrics'));
      await page.goto('/', {waitUntil:'load'});
      await expect.poll(()=>page.evaluate(()=>state.uiReady===true),{timeout:15_000}).toBe(true);
      const snapshot=await readBrowserSnapshot(page);
      const cdp=await session.send('Performance.getMetrics');
      samples.push({
        iteration:index+1,
        cacheMode:index<3?'cleared-before-navigation':'preserved-from-prior-navigation',
        ...snapshot,
        cdp:Object.fromEntries(Object.entries(numericMetrics(cdp)).map(([key,value])=>[
          key,key.endsWith('Duration') ? Math.max(0,value-Number(beforeMetrics[key]||0)) : value
        ]))
      });
      expect(snapshot.uiReady).toBe(true);
      expect(snapshot.appScript).not.toBeNull();
      expect(snapshot.mainScript).not.toBeNull();
    }
  } finally {
    await session.detach();
  }
  const evidence={
    scope:PERFORMANCE_SCOPE,
    browser:'Playwright Chrome on isolated CI runner',
    samples,
    startupReadyP50Ms:quantile(samples.map(row=>row.readyAtMs),0.5),
    startupReadyMaxMs:Math.max(...samples.map(row=>row.readyAtMs)),
    warning:'Five CI fixture samples are NOT production percentiles; CDP profiler is separate from these timings.'
  };
  await saveEvidence(testInfo,'frontend-startup-profile.json',evidence);
  console.log('[13c04c-startup-profile] '+JSON.stringify({
    scope:evidence.scope,samples:samples.length,
    startupReadyP50Ms:evidence.startupReadyP50Ms,
    startupReadyMaxMs:evidence.startupReadyMaxMs,
    coldScriptDecodedBytes:samples[0].scriptDecodedBytes,
    coldScriptTransferBytes:samples[0].scriptTransferBytes,
    appDecodedBytes:samples[0].appScript?.decodedBytes,
    longTaskCount:samples[0].longTasks?.length ?? null
  }));
  expect(errors).toEqual([]);
});

test('13C-04C captures real V8 JS coverage and scoped page navigation', async ({page}, testInfo) => {
  test.setTimeout(60_000);
  const errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await installLongTaskObserver(page);
  await page.coverage.startJSCoverage({resetOnNavigation:false});
  await page.goto('/',{waitUntil:'load'});
  await expect.poll(()=>page.evaluate(()=>state.uiReady===true),{timeout:15_000}).toBe(true);
  const startup=await readBrowserSnapshot(page);
  const entries=await page.coverage.stopJSCoverage();
  const coverage=entries.filter(row=>{
    try {return /^\/static\/.*\.(?:m?js)$/.test(new URL(row.url).pathname);}catch(_){return false;}
  }).map(row=>{
    const path=new URL(row.url).pathname;
    const totalChars=row.source?.length||0;
    const usedChars=usedCoverageChars(row.functions,totalChars);
    return {
      path,totalChars,usedChars,
      usedRatio:totalChars ? Math.round(usedChars/totalChars*1000)/10 : null
    };
  }).sort((a,b)=>b.totalChars-a.totalChars);
  const app=coverage.find(row=>row.path===APP_ASSET);
  const main=coverage.find(row=>row.path===MAIN_ASSET);
  expect(app).toBeDefined();
  expect(main).toBeDefined();
  const navigation=[];
  for(const name of ['训练任务','数据集']){
    const before=await page.evaluate(()=>({
      time:performance.now(),
      longTaskCount:window.__frontendProfileLongTasks?.length ?? null
    }));
    await page.evaluate(target=>window.setPage(target),name);
    if(name==='训练任务')await expect(page.locator('.train428-page')).toBeVisible({timeout:10_000});
    if(name==='数据集')await expect(page.locator('.data426-shell')).toBeVisible({timeout:10_000});
    const after=await page.evaluate(()=>({
      time:performance.now(),
      longTaskCount:window.__frontendProfileLongTasks?.length ?? null,
      page:state.page
    }));
    navigation.push({
      page:name,visibleMs:Math.round((after.time-before.time)*10)/10,
      additionalLongTasks:before.longTaskCount===null||after.longTaskCount===null?null:Math.max(0,after.longTaskCount-before.longTaskCount),
      renderedPage:after.page
    });
  }
  const evidence={
    scope:PERFORMANCE_SCOPE,
    method:'V8 precise JS function coverage; used ratio is UTF-16 source-character coverage, not traffic bytes or parse time',
    startup,
    appCoverage:app,
    mainCoverage:main,
    scriptCoverage:coverage,
    navigation,
    caveats:[
      'V8 coverage changes runtime overhead and is separated from uninstrumented startup timing.',
      'Coverage marks functions invoked during this one startup; it is not a safe deletion list.',
      'Page navigation visible time includes fixture rendering and asynchronous requests, not a production P95.'
    ]
  };
  await saveEvidence(testInfo,'frontend-script-coverage.json',evidence);
  console.log('[13c04c-script-coverage] '+JSON.stringify({
    scope:PERFORMANCE_SCOPE,app,main,loadedScripts:coverage.length,navigation
  }));
  expect(errors).toEqual([]);
});
