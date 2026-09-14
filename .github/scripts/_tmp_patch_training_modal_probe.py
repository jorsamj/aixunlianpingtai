from pathlib import Path

path = Path('static/app.js')
text = path.read_text(encoding='utf-8')
old = '''  window.startAlgorithmTraining429=async function(aid){
    if(!state.uiReady&&window.__v53InitPromise)await window.__v53InitPromise;
    if(!(state.targets||[]).some(target=>target.status==='ready')){
      const options=await api(`/api/training_options?project_id=${pid()}`);
      state.targets=options?.targets||[];
    }
    try{state.trainingDevicesV3=await api('/api/v62/training-devices')}catch(error){state.trainingDevicesV3={options:[],error:String(error.message||error)}}
    const result=await previousStart?.(aid);const recommendedDevice=state.trainingDevicesV3.recommended||'auto';window.TrainingDraftRuntime?.update?.({resource:{device:recommendedDevice}});const deviceSelect=document.getElementById('trV3Device');if(deviceSelect)deviceSelect.value=recommendedDevice;[40,140,340,650].forEach(delay=>setTimeout(renderSplit,delay));return result
  };'''
new = '''  window.startAlgorithmTraining429=async function(aid){
    if(!state.uiReady&&window.__v53InitPromise)await window.__v53InitPromise;
    if(!(state.targets||[]).some(target=>target.status==='ready')){
      const options=await api(`/api/training_options?project_id=${pid()}`);
      state.targets=options?.targets||[];
    }
    const cachedDevices=state.trainingDevicesV3;
    const cacheFresh=Boolean(cachedDevices?.options?.length)&&Date.now()-Number(state.trainingDevicesV3LoadedAt||0)<60000;
    if(!cachedDevices?.options?.length){state.trainingDevicesV3={options:[{id:'auto',label:'自动（优先 GPU）',type:'auto',available:true}],recommended:'auto',loading:true}}
    const resultPromise=previousStart?.(aid);
    const applyDevices=devices=>{state.trainingDevicesV3={...devices,loading:false};state.trainingDevicesV3LoadedAt=Date.now();const recommendedDevice=devices?.recommended||'auto';window.TrainingDraftRuntime?.update?.({resource:{device:recommendedDevice}});const deviceSelect=document.getElementById('trV3Device');if(deviceSelect)deviceSelect.value=recommendedDevice;renderSplit()};
    if(cacheFresh){applyDevices(cachedDevices)}else{api('/api/v62/training-devices').then(applyDevices).catch(error=>{state.trainingDevicesV3={...(state.trainingDevicesV3||{}),loading:false,error:String(error.message||error)}})}
    const result=await resultPromise;[40,140,340,650].forEach(delay=>setTimeout(renderSplit,delay));return result
  };'''
count = text.count(old)
if count != 1:
    raise SystemExit(f'expected exactly one training device wrapper, found {count}')
path.write_text(text.replace(old, new), encoding='utf-8')
print('patched static/app.js training modal device probe ordering')
