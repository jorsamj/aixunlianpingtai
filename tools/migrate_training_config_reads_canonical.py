from pathlib import Path

APP = Path("static/app.js")

BASE = "function baseCfg428(){return{model:'',epochs:100,imgsz:640,batch:8,device:'cpu',optimizer:'auto',patience:100,workers:0,lr0:.01,lrf:.01,momentum:.937,weight_decay:.0005,warmup_epochs:3,close_mosaic:10,mosaic:1,mixup:0,hsv_h:.015,hsv_s:.7,hsv_v:.4,degrees:0,translate:.1,scale:.5,shear:0,perspective:0,flipud:0,fliplr:.5,cache:'False',pretrained:true,amp:true,rect:false,cos_lr:false,freeze:0,multi_scale:0,save_period:-1,seed:0,deterministic:true,eval_interval:10,eval_metric:'map50',continue_threshold:0,stop_threshold:.90,val_max_samples:0,queue_priority:50,auto_convert_targets:[]}}"
LOCAL_HELPER = "function trainingConfig428(){const draft=state.trainingDraft||{},resource=draft.resource||{},legacy=state.train428Config||{},c=Object.assign(baseCfg428(),legacy,draft.config||{});if(resource.device&&resource.device!=='auto')c.device=resource.device;if(resource.batch!=null)c.batch=resource.batch;if(resource.workers!=null)c.workers=resource.workers;if(resource.cache!=null)c.cache=resource.cache===false?'False':resource.cache;if(resource.strategy)c.resource_strategy=resource.strategy;if(resource.gpuPolicy)c.gpu_policy=resource.gpuPolicy;return c}"
EXPORTED_HELPER = LOCAL_HELPER + "\n  window.trainingConfigCanonical428=trainingConfig428;"
INITIAL_HELPER = BASE + "\n  " + LOCAL_HELPER

LEGACY_BASE_READ = "state.train428Config||baseCfg428()"
CFG429_OLD = "function cfg429(){return Object.assign({model:'',epochs:100,imgsz:640,batch:8,eval_interval:10,val_max_samples:0,eval_metric:'map50',continue_threshold:0,stop_threshold:.9,optimizer:'auto',patience:100,workers:0,lr0:.01,lrf:.01,momentum:.937,weight_decay:.0005,warmup_epochs:3,close_mosaic:10,mosaic:1,mixup:0,hsv_h:.015,hsv_s:.7,hsv_v:.4,degrees:0,translate:.1,scale:.5,shear:0,perspective:0,flipud:0,fliplr:.5,cache:'False',pretrained:true,amp:true,rect:false,cos_lr:false,freeze:0,multi_scale:false,save_period:-1,seed:0,deterministic:true,auto_convert_targets:[]},state.train428Config||{})}"
CFG429_LOCAL = "function cfg429(){return trainingConfig428()}"
CFG429_GLOBAL = "function cfg429(){return window.trainingConfigCanonical428()}"
CFG415_OLD = "const cfg415=()=>Object.assign({model:'',epochs:100,imgsz:640,batch:8,device:'cpu',eval_interval:10,val_max_samples:0,eval_metric:'map50',continue_threshold:0,stop_threshold:.9,optimizer:'auto',patience:100,workers:0,lr0:.01,lrf:.01,momentum:.937,weight_decay:.0005,warmup_epochs:3,close_mosaic:10,mosaic:1,mixup:0,hsv_h:.015,hsv_s:.7,hsv_v:.4,degrees:0,translate:.1,scale:.5,shear:0,perspective:0,flipud:0,fliplr:.5,cache:'False',pretrained:true,amp:true,single_cls:false,rect:false,cos_lr:false,freeze:0,multi_scale:0,save_period:-1,seed:0,deterministic:true,auto_convert_targets:[]},state.train428Config||{});"
CFG415_LOCAL = "const cfg415=()=>trainingConfig428();"
CFG415_GLOBAL = "const cfg415=()=>window.trainingConfigCanonical428();"


def main() -> None:
    text = APP.read_text(encoding="utf-8")

    if LOCAL_HELPER not in text:
        if text.count(BASE) != 1:
            raise SystemExit(f"expected one baseCfg428 insertion point, found {text.count(BASE)}")
        text = text.replace(BASE, INITIAL_HELPER, 1)
        print("installed canonical-first local training config reader")

    if "window.trainingConfigCanonical428=trainingConfig428;" not in text:
        if text.count(LOCAL_HELPER) != 1:
            raise SystemExit(f"expected one local training config helper, found {text.count(LOCAL_HELPER)}")
        text = text.replace(LOCAL_HELPER, EXPORTED_HELPER, 1)
        print("exported canonical config reader for later legacy scopes")

    count = text.count(LEGACY_BASE_READ)
    if count:
        if count != 5:
            raise SystemExit(f"expected five legacy base config reads, found {count}")
        text = text.replace(LEGACY_BASE_READ, "trainingConfig428()")
        print("migrated five local 428 config reads")

    if CFG429_OLD in text:
        if text.count(CFG429_OLD) != 1:
            raise SystemExit("unexpected cfg429 legacy definition count")
        text = text.replace(CFG429_OLD, CFG429_GLOBAL, 1)
    elif CFG429_LOCAL in text:
        if text.count(CFG429_LOCAL) != 1:
            raise SystemExit("unexpected local cfg429 definition count")
        text = text.replace(CFG429_LOCAL, CFG429_GLOBAL, 1)
    elif text.count(CFG429_GLOBAL) != 1:
        raise SystemExit("canonical cfg429 definition missing")

    if CFG415_OLD in text:
        if text.count(CFG415_OLD) != 1:
            raise SystemExit("unexpected cfg415 legacy definition count")
        text = text.replace(CFG415_OLD, CFG415_GLOBAL, 1)
    elif CFG415_LOCAL in text:
        if text.count(CFG415_LOCAL) != 1:
            raise SystemExit("unexpected local cfg415 definition count")
        text = text.replace(CFG415_LOCAL, CFG415_GLOBAL, 1)
    elif text.count(CFG415_GLOBAL) != 1:
        raise SystemExit("canonical cfg415 definition missing")

    if LEGACY_BASE_READ in text or CFG429_OLD in text or CFG429_LOCAL in text or CFG415_OLD in text or CFG415_LOCAL in text:
        raise SystemExit("cross-scope legacy training config read path remains")

    APP.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
