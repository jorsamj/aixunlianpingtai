from pathlib import Path

APP = Path("static/app.js")

BASE = "function baseCfg428(){return{model:'',epochs:100,imgsz:640,batch:8,device:'cpu',optimizer:'auto',patience:100,workers:0,lr0:.01,lrf:.01,momentum:.937,weight_decay:.0005,warmup_epochs:3,close_mosaic:10,mosaic:1,mixup:0,hsv_h:.015,hsv_s:.7,hsv_v:.4,degrees:0,translate:.1,scale:.5,shear:0,perspective:0,flipud:0,fliplr:.5,cache:'False',pretrained:true,amp:true,rect:false,cos_lr:false,freeze:0,multi_scale:0,save_period:-1,seed:0,deterministic:true,eval_interval:10,eval_metric:'map50',continue_threshold:0,stop_threshold:.90,val_max_samples:0,queue_priority:50,auto_convert_targets:[]}}"
HELPER = BASE + "\n  function trainingConfig428(){const draft=state.trainingDraft||{},resource=draft.resource||{},legacy=state.train428Config||{},c=Object.assign(baseCfg428(),legacy,draft.config||{});if(resource.device&&resource.device!=='auto')c.device=resource.device;if(resource.batch!=null)c.batch=resource.batch;if(resource.workers!=null)c.workers=resource.workers;if(resource.cache!=null)c.cache=resource.cache===false?'False':resource.cache;if(resource.strategy)c.resource_strategy=resource.strategy;if(resource.gpuPolicy)c.gpu_policy=resource.gpuPolicy;return c}"

LEGACY_BASE_READ = "state.train428Config||baseCfg428()"

CFG429_OLD = "function cfg429(){return Object.assign({model:'',epochs:100,imgsz:640,batch:8,eval_interval:10,val_max_samples:0,eval_metric:'map50',continue_threshold:0,stop_threshold:.9,optimizer:'auto',patience:100,workers:0,lr0:.01,lrf:.01,momentum:.937,weight_decay:.0005,warmup_epochs:3,close_mosaic:10,mosaic:1,mixup:0,hsv_h:.015,hsv_s:.7,hsv_v:.4,degrees:0,translate:.1,scale:.5,shear:0,perspective:0,flipud:0,fliplr:.5,cache:'False',pretrained:true,amp:true,rect:false,cos_lr:false,freeze:0,multi_scale:false,save_period:-1,seed:0,deterministic:true,auto_convert_targets:[]},state.train428Config||{})}"
CFG429_NEW = "function cfg429(){return trainingConfig428()}"

CFG415_OLD = "const cfg415=()=>Object.assign({model:'',epochs:100,imgsz:640,batch:8,device:'cpu',eval_interval:10,val_max_samples:0,eval_metric:'map50',continue_threshold:0,stop_threshold:.9,optimizer:'auto',patience:100,workers:0,lr0:.01,lrf:.01,momentum:.937,weight_decay:.0005,warmup_epochs:3,close_mosaic:10,mosaic:1,mixup:0,hsv_h:.015,hsv_s:.7,hsv_v:.4,degrees:0,translate:.1,scale:.5,shear:0,perspective:0,flipud:0,fliplr:.5,cache:'False',pretrained:true,amp:true,single_cls:false,rect:false,cos_lr:false,freeze:0,multi_scale:0,save_period:-1,seed:0,deterministic:true,auto_convert_targets:[]},state.train428Config||{});"
CFG415_NEW = "const cfg415=()=>trainingConfig428();"


def replace_exact(text: str, old: str, new: str, expected: int, label: str) -> str:
    count = text.count(old)
    if count == 0 and text.count(new) == expected:
        print(f"{label} already migrated")
        return text
    if count != expected:
        raise SystemExit(f"expected {expected} {label} legacy occurrences, found {count}")
    return text.replace(old, new)


def main() -> None:
    text = APP.read_text(encoding="utf-8")

    if "function trainingConfig428()" not in text:
        if text.count(BASE) != 1:
            raise SystemExit(f"expected one baseCfg428 insertion point, found {text.count(BASE)}")
        text = text.replace(BASE, HELPER, 1)
        print("installed canonical-first trainingConfig428 helper")

    text = replace_exact(text, LEGACY_BASE_READ, "trainingConfig428()", 5, "base config read")
    text = replace_exact(text, CFG429_OLD, CFG429_NEW, 1, "cfg429")
    text = replace_exact(text, CFG415_OLD, CFG415_NEW, 1, "cfg415")

    if LEGACY_BASE_READ in text or CFG429_OLD in text or CFG415_OLD in text:
        raise SystemExit("legacy training config read path remains")

    APP.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
