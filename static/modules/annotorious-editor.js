import {toAnno, fromAnno, annotationColor} from './annotation-geometry-adapter.js?v=20261022a';
import {withRequestDeadline} from './api.js?v=20261021s';

// One local official distribution, shared by manual GT and candidate editors.
// This module owns interaction and viewport only. The caller owns GT/history/save.
let assets;
export function loadAnnotorious(doc = document) {
  if (!assets) assets = withRequestDeadline(signal=>new Promise((resolve,reject)=>{
    let css=doc.querySelector('link[data-annotorious-css]'),script;
    let cssReady=!!(css?.sheet||css?.dataset.annotoriousLoaded==='1'),jsReady=!!globalThis.Annotorious?.createImageAnnotator;
    const ownCss=!css;let settled=false;
    if(!css){css=doc.createElement('link');css.rel='stylesheet';css.href='/static/vendor/annotorious/annotorious.css?v=3.9.5';css.dataset.annotoriousCss='1';}
    const clean=()=>{css.removeEventListener('load',loadedCss);css.removeEventListener('error',failed);script?.removeEventListener('load',loadedScript);script?.removeEventListener('error',failed);signal.removeEventListener('abort',aborted);};
    const fail=error=>{if(settled)return;settled=true;clean();if(ownCss&&!cssReady)css.remove();if(script&&!jsReady)script.remove();reject(error);};
    const finish=()=>{if(!settled&&cssReady&&jsReady){settled=true;clean();resolve(globalThis.Annotorious);}};
    const failed=()=>fail(new Error('本地标注组件资源加载失败，请重试'));
    const aborted=()=>fail(Object.assign(new Error('本地标注组件加载已中止'),{name:'AbortError'}));
    const loadedCss=()=>{cssReady=true;css.dataset.annotoriousLoaded='1';finish();};
    const loadedScript=()=>{jsReady=!!globalThis.Annotorious?.createImageAnnotator;if(jsReady)finish();else failed();};
    css.addEventListener('load',loadedCss);css.addEventListener('error',failed);signal.addEventListener('abort',aborted,{once:true});
    if(ownCss)doc.head.appendChild(css);
    if(!jsReady){script=doc.createElement('script');script.src='/static/vendor/annotorious/annotorious.js?v=3.9.5';script.addEventListener('load',loadedScript);script.addEventListener('error',failed);doc.head.appendChild(script);}
    finish();
  }),{timeoutMs:30000,label:'本地标注组件加载'}).catch(error=>{assets=null;if(error.code==='REQUEST_TIMEOUT')throw Object.assign(new Error('本地标注组件加载超时，请重试'),{code:error.code});throw error;});
  return assets;
}

export async function createAnnotoriousEditor(options) {
  const {image, viewport, world, getBoxes = () => [], getLabels = () => [],
    getLabel = () => null, getSelectedId = () => null, onCommit = () => {},
    onSelect = options.onSelection || (() => {}), onError = () => {},
    isActive = () => true, onViewportChange = () => {}} = options;
  if (!image || !viewport || !world) throw new Error('Image, viewport and world are required');
  const doc = image.ownerDocument || document;
  const imageSource = () => image.src || image.currentSrc;
  const initialSource = imageSource();
  if(options.signal?.aborted)throw Object.assign(new Error('标注编辑已关闭'),{name:'AbortError'});
  const create = options.createAnnotator || (await withRequestDeadline(()=>loadAnnotorious(doc),{timeoutMs:30000,label:'标注编辑初始化',signal:options.signal})).createImageAnnotator;
  if(options.signal?.aborted)throw Object.assign(new Error('标注编辑已关闭'),{name:'AbortError'});
  if (imageSource() !== initialSource || image.isConnected === false)
    throw new Error('标注图片已切换');
  const controller = new AbortController(), signal = controller.signal;
  let destroyed = false, syncing = false, locked = false, visible = true;
  let mode = 'draw', selectedId = getSelectedId(), filteredCodes = null;
  let autoFit = true, resizeObserver;
  let scale = 1, tx = 0, ty = 0, drawing = false, pan = null, source = initialSource;
  let labelOverride, labelsOverride;
  const size = () => ({width:Number(image.naturalWidth || options.width || image.width),height:Number(image.naturalHeight || options.height || image.height)});
  const labels = () => labelsOverride || getLabels();
  const label = () => labelOverride === undefined ? getLabel() : labelOverride;
  const active = () => !destroyed && isActive();
  const editable = () => active() && !locked && visible && mode !== 'pan';
  const allowed = box => visible && (!filteredCodes || filteredCodes.has(String(box.label)));
  const rows = () => getBoxes() || [];
  const idOf = box => String(box.id);
  // autoSave is the official lifecycle event policy; persistence remains the caller's.
  const annotationStyle = annotation => {
    const box=rows().find(row=>idOf(row)===String(annotation.id));
    const color=annotationColor(box,labels());
    return {stroke:color,strokeWidth:2,fill:color,fillOpacity:.08};
  };
  const official = create(image, {disableUndoRedoKeys:true,autoSave:true,drawingEnabled:false,drawingMode:'drag',userSelectAction:'EDIT',style:annotationStyle});
  official.setDrawingTool('rectangle');
  const listeners = [];
  const notifySelection = id => { selectedId=id == null ? null : String(id); onSelect(selectedId); };
  const transform = () => {
    const {width,height}=size();
    world.style.width=`${width}px`; world.style.height=`${height}px`;
    world.style.transformOrigin='0 0'; world.style.transform=`translate(${tx}px, ${ty}px) scale(${scale})`;
    // The official wrapper contains both image and SVG in natural pixel units.
    image.style.width=`${width}px`;image.style.height=`${height}px`;image.style.maxWidth='none';
    onViewportChange({scale});
  };
  function project() {
    if (destroyed) return;
    syncing=true;
    try {
      const projected=rows().filter(allowed).map(box=>toAnno(box,size()));
      official.setAnnotations(projected);
      // Official 3.9.5 renders these values as inline styles on both normal
      // rectangles and selected editors, above its ordinary theme CSS.
      official.setStyle?.(annotationStyle);
      const selected=projected.some(row=>String(row.id)===String(selectedId));
      if (!selected || locked || mode!=='select') { official.cancelSelected(); if(selectedId!=null)notifySelection(null); }
      else official.setSelected(String(selectedId),true);
      official.setDrawingEnabled(!locked && visible && mode==='draw' && !!label());
      official.setUserSelectAction(locked || !visible || mode!=='select' ? 'NONE' : 'EDIT');
      viewport.style.cursor=mode==='pan'?'grab':mode==='draw'?'crosshair':'default';
    } catch(error) { onError(error); }
    finally { syncing=false; }
  }
  function commit(next,reason,id=selectedId) {
    if (!editable()) return false;
    if(JSON.stringify(next)===JSON.stringify(rows()))return false;
    onCommit(next,{selectedId:id == null ? null : String(id),reason});
    notifySelection(id); project(); return true;
  }
  const changed = (annotation,reason) => {
    if (syncing || !editable()) return;
    try {
      // Lifecycle callbacks are deferred by the official library. Read its current
      // public value so an older queued event cannot undo a later pointer gesture.
      if(official.getAnnotationById){annotation=official.getAnnotationById(annotation.id);if(!annotation)return;}
      const current=rows(), originals=new Map(current.map(box=>[idOf(box),box]));
      const previous=originals.get(String(annotation.id));
      if(previous&&!allowed(previous)){project();return;}
      const box=fromAnno(annotation,{...size(),originalBoxesById:originals,labels:labels(),newLabel:label()});
      // A newly created rectangle is classified by the explicitly chosen class.
      if(!previous && (!label() || (filteredCodes&&!filteredCodes.has(String(box.label))))) {project();return;}
      drawing=false;
      commit(previous?current.map(row=>idOf(row)===String(annotation.id)?box:row):[...current,box],reason,box.id);
    } catch(error) { drawing=false; onError(error); project(); }
  };
  const listen = (event,fn) => {official.on(event,fn);listeners.push([event,fn]);};
  listen('createAnnotation',annotation=>changed(annotation,'create'));
  listen('updateAnnotation',annotation=>changed(annotation,'update'));
  listen('deleteAnnotation',annotation=>{
    if(!syncing&&editable()&&rows().some(box=>idOf(box)===String(annotation.id)&&allowed(box)))
      commit(rows().filter(box=>idOf(box)!==String(annotation.id)),'delete',null);
  });
  listen('selectionChanged',annotations=>{
    if(syncing||!editable())return;
    annotations=official.getSelected?.() || annotations;
    const first=annotations?.[0],id=first?.id;
    notifySelection(id!=null&&rows().some(box=>idOf(box)===String(id)&&allowed(box))?id:null);
  });
  function flush() {
    if(!editable()||syncing)return false;
    try {
      const current=rows(),originals=new Map(current.map(box=>[idOf(box),box]));
      const updates=new Map((official.getAnnotations?.()||[]).map(annotation=>{
        const box=fromAnno(annotation,{...size(),originalBoxesById:originals,labels:labels(),newLabel:label()});
        return [idOf(box),box];
      }));
      const next=current.map(box=>allowed(box)&&updates.has(idOf(box))?updates.get(idOf(box)):box);
      let newId=null;
      for(const [id,box]of updates)if(!originals.has(id)&&allowed(box)){next.push(box);newId=id;}
      const selected=official.getSelected?.()?.[0]?.id ?? newId ?? selectedId;
      return commit(next,newId?'create':'update',selected);
    }catch(error){onError(error);project();return false;}
  }
  function select(id) {
    if(!editable())return false;
    mode='select';official.setDrawingEnabled(false);official.setUserSelectAction('EDIT');options.onModeChange?.(mode);
    const found=rows().find(box=>idOf(box)===String(id)&&allowed(box));
    notifySelection(found?found.id:null);
    if(found)official.setSelected(String(found.id),true);else official.cancelSelected();
    return !!found;
  }
  function deleteSelected() {
    // Official selectionChanged is deferred; a quick Delete after pointerup
    // still acts on the currently selected public component value.
    if(official.getSelected){const actual=official.getSelected()[0]?.id;selectedId=actual==null?null:String(actual);}
    if(!editable()||selectedId==null)return false;
    const found=rows().find(box=>idOf(box)===String(selectedId)&&allowed(box));
    return found?commit(rows().filter(box=>idOf(box)!==String(selectedId)),'delete',null):false;
  }
  function reclassSelected(nextLabel) {
    const choice=typeof nextLabel==='object'?nextLabel:labels().find(row=>String(row.code)===String(nextLabel)||String(row.class_id)===String(nextLabel));
    if(!editable()||!choice||selectedId==null)return false;
    return commit(rows().map(box=>idOf(box)===String(selectedId)&&allowed(box)?{...box,class_id:choice.class_id,label:choice.code}:box),'reclass');
  }
  function setMode(next) {
    if(destroyed||!['draw','select','pan'].includes(next))return;
    official.cancelDrawing();drawing=false;mode=next;project();options.onModeChange?.(mode);
  }
  function handleEscape(event) {
    if(!active())return false;
    options.onEscape?.();
    if(official.getSelected){const actual=official.getSelected()[0]?.id;selectedId=actual==null?null:String(actual);}
    if(drawing){official.cancelDrawing();drawing=false;setMode('select');}
    else if(selectedId!=null){official.cancelSelected();notifySelection(null);if(mode==='draw')setMode('select');}
    else if(mode==='draw'){setMode('select');}
    else return false;
    event?.preventDefault();event?.stopImmediatePropagation();return true;
  }
  const inputTarget = target => !!target?.closest?.('input,textarea,select,[contenteditable]:not([contenteditable="false"])') || ['INPUT','TEXTAREA','SELECT'].includes(target?.tagName);
  doc.addEventListener('keydown',event=>{
    if(!active()||inputTarget(event.target))return;
    if(event.key==='Escape'){handleEscape(event);return;}
    if(locked)return;
    const key=String(event.key).toLowerCase(),command=event.ctrlKey||event.metaKey;
    let handled=true;
    if(command&&key==='s'){flush();options.onSave?.();}
    else if(command&&key==='z'){flush();(event.shiftKey?options.onRedo:options.onUndo)?.();}
    else if(command&&key==='y')options.onRedo?.();
    else if(!command&&(key==='delete'||key==='backspace'))deleteSelected();
    else if(!command&&key==='h')api.setVisibility(!visible);
    else if(!command&&/^[1-9]$/.test(key)){const choice=labels()[Number(key)-1];if(choice){labelOverride=choice;options.onChooseLabel?.(choice);project();}}
    else if(!command&&(key==='arrowleft'||key==='arrowright'))options.onNavigate?.(key==='arrowleft'?-1:1);
    else handled=false;
    if(handled){event.preventDefault();event.stopImmediatePropagation();}
  },{capture:true,signal});
  viewport.addEventListener('pointerdown',event=>{
    if(!active()||locked||event.button!==0)return;
    if(mode==='pan'){autoFit=false;pan={id:event.pointerId,x:event.clientX,y:event.clientY,tx,ty};viewport.setPointerCapture?.(event.pointerId);event.preventDefault();event.stopImmediatePropagation();}
    else if(mode==='draw'&&visible&&!event.target.closest?.('.a9s-annotation,.a9s-selection'))drawing=true;
  },{capture:true,signal});
  viewport.addEventListener('pointermove',event=>{
    if(!pan||pan.id!==event.pointerId)return;
    tx=pan.tx+event.clientX-pan.x;ty=pan.ty+event.clientY-pan.y;transform();event.preventDefault();
  },{signal});
  const finishPan=event=>{if(pan?.id===event.pointerId){viewport.releasePointerCapture?.(event.pointerId);pan=null;}else queueMicrotask(()=>{if(!destroyed)flush();});};
  viewport.addEventListener('pointerup',finishPan,{signal});viewport.addEventListener('pointercancel',event=>{finishPan(event);drawing=false;official.cancelDrawing();},{signal});
  viewport.addEventListener('wheel',event=>{if(!active()||locked)return;event.preventDefault();api.zoom(event.deltaY<0?.1:-.1,{x:event.clientX,y:event.clientY});},{passive:false,signal});
  function fitViewport() {
    if(destroyed)return;
    const {width,height}=size(), vw=viewport.clientWidth, vh=viewport.clientHeight;
    if(![width,height,vw,vh].every(n=>Number.isFinite(n)&&n>0))return;
    scale=Math.min(vw/width,vh/height);
    tx=(vw-width*scale)/2;ty=(vh-height*scale)/2;transform();
  }
  image.addEventListener('load',()=>{
    if(destroyed)return;
    if(source!==imageSource()){source=imageSource();autoFit=true;notifySelection(null);}
    if(autoFit)fitViewport();else transform();
    project();
  },{signal});
  const api={
    sync(value={}) {
      if(destroyed)return;
      if('labels'in value)labelsOverride=value.labels;
      if('label'in value)labelOverride=value.label;
      if('selectedId'in value)selectedId=value.selectedId==null?null:String(value.selectedId);
      if('locked'in value)locked=!!value.locked;
      const nextSource=imageSource();
      if(source!==nextSource){source=nextSource;autoFit=true;selectedId=null;drawing=false;official.cancelDrawing();}
      if(locked){drawing=false;official.cancelDrawing();}
      if(autoFit)fitViewport();else transform();project();
    },select,deleteSelected,reclassSelected,setMode,handleEscape,flush,
    setVisibility(value){if(destroyed)return;visible=!!value;official.cancelDrawing();drawing=false;project();options.onVisibilityChange?.(visible);},
    setClassFilter(codes){if(destroyed)return;filteredCodes=codes==null?null:new Set([...codes].map(String));official.cancelDrawing();drawing=false;project();},
    fit(){if(destroyed)return;autoFit=true;fitViewport();},
    resetZoom(){if(destroyed)return;autoFit=false;scale=1;tx=ty=0;transform();},
    zoom(delta,point){if(destroyed)return;const next=Math.max(.01,Math.min(Math.max(4,scale,4*Math.min(viewport.clientWidth/image.naturalWidth,viewport.clientHeight/image.naturalHeight)),scale+Number(delta)));if(!Number.isFinite(next))return;autoFit=false;const rect=viewport.getBoundingClientRect();const x=point?point.x-rect.left:viewport.clientWidth/2,y=point?point.y-rect.top:viewport.clientHeight/2;tx=x-(x-tx)*next/scale;ty=y-(y-ty)*next/scale;scale=next;transform();},
    snapshot:()=>Object.freeze({mode,visible,scale,selectedId,filteredCodes:filteredCodes?[...filteredCodes]:null,destroyed,locked}),
    destroy(){if(destroyed)return;destroyed=true;controller.abort();resizeObserver?.disconnect();if(pan)viewport.releasePointerCapture?.(pan.id);pan=null;drawing=false;for(const [event,fn]of listeners)official.off(event,fn);official.destroy();},
  };
  api.delete=deleteSelected;api.reclass=reclassSelected;api.mode=setMode;api['100']=api.resetZoom;
  options.signal?.addEventListener('abort',()=>api.destroy(),{once:true,signal});
  const Observer=doc.defaultView?.ResizeObserver || globalThis.ResizeObserver;
  if(Observer){resizeObserver=new Observer(()=>{if(autoFit&&active())fitViewport();});resizeObserver.observe(viewport);}
  fitViewport();project();return api;
}
