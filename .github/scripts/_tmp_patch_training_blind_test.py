from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one patch target, found {count}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "platform_core/training_tasks.py",
    '        label_ref = f"dataset/labels/{role}/{Path(stored_name).stem}.txt"\n',
    '        label_ref = (\n'
    '            f"evaluation/ground_truth/test/{Path(stored_name).stem}.txt"\n'
    '            if role == "test"\n'
    '            else f"dataset/labels/{role}/{Path(stored_name).stem}.txt"\n'
    '        )\n',
)

replace_once(
    "platform_core/training_tasks.py",
    '''    data_yaml = {\n        "path": ".",\n        "train": "images/train",\n        "val": "images/validation",\n        "test": "images/test",\n        "names": names,\n    }\n''',
    '''    # Independent test images stay portable, but their hidden answers are deliberately\n    # absent from the Ultralytics training YAML. Final evaluation is image-only inference\n    # followed by a separate scorer that opens evaluation/ground_truth/test afterwards.\n    data_yaml = {\n        "path": ".",\n        "train": "images/train",\n        "val": "images/validation",\n        "names": names,\n    }\n''',
)

replace_once(
    "platform_core/training_evaluation.py",
    '''    if not path.is_file():\n        return []\n''',
    '''    if not path.is_file():\n        raise FileNotFoundError(f"hidden blind-test ground truth is missing: {path.name}")\n''',
)

replace_once(
    "train_worker.py",
    '''            try:\n                test_metrics=best_model.val(data=args.data, split="test", verbose=False)\n                test_values=(build_report_from_metrics(test_metrics,getattr(best_model,"names",None)).get("metrics") or {})\n                training_report["test_metrics"]=test_values\n                training_report["test_result"]={"status":"succeeded","metrics":test_values}\n            except Exception as te:\n                training_report["test_note"]="评测集为空或无法评测："+str(te)\n                training_report["test_result"]={"status":"failed","metrics":{},"error":str(te)}\n''',
    '''            try:\n                import yaml\n                from platform_core.training_evaluation import evaluate_blind_detection\n\n                runtime_spec=yaml.safe_load(Path(args.data).read_text(encoding="utf-8")) or {}\n                dataset_root=Path(str(runtime_spec.get("path") or "."))\n                if not dataset_root.is_absolute():\n                    dataset_root=(Path(args.data).resolve().parent/dataset_root).resolve()\n                else:\n                    dataset_root=dataset_root.resolve()\n                test_images_dir=dataset_root/"images"/"test"\n                hidden_ground_truth_dir=dataset_root.parent/"evaluation"/"ground_truth"/"test"\n                current_job=read_json(job_file,{})\n                update_job(\n                    job_file,\n                    progress_percent=max(96.0,float(current_job.get("progress_percent") or 0.0)),\n                    current_item="独立试验集盲测",\n                    message="训练完成，正在对无标注试验图片执行盲测",\n                )\n\n                def blind_predict(image_path):\n                    results=best_model.predict(\n                        source=str(image_path),\n                        conf=0.001,\n                        iou=0.7,\n                        device=args.device,\n                        verbose=False,\n                    )\n                    result=results[0] if results else None\n                    rows=[]\n                    if result is not None and getattr(result,"boxes",None) is not None:\n                        boxes=result.boxes\n                        xyxy=boxes.xyxy.detach().cpu().tolist()\n                        classes=boxes.cls.detach().cpu().tolist()\n                        confidences=boxes.conf.detach().cpu().tolist()\n                        rows=[\n                            {\n                                "class_id":int(class_id),\n                                "confidence":float(confidence),\n                                "box":list(map(float,box)),\n                            }\n                            for box,class_id,confidence in zip(xyxy,classes,confidences)\n                        ]\n                    return rows\n\n                blind_result=evaluate_blind_detection(\n                    test_images_dir,\n                    hidden_ground_truth_dir,\n                    blind_predict,\n                    names=getattr(best_model,"names",None),\n                )\n                training_report["test_metrics"]=blind_result.get("metrics") or {}\n                training_report["test_result"]=blind_result\n                training_report["test_per_class"]=blind_result.get("per_class") or []\n                training_report["test_protocol"]=blind_result.get("protocol") or {}\n            except Exception as te:\n                training_report["test_note"]="独立试验集盲测失败："+str(te)\n                training_report["test_result"]={\n                    "status":"failed",\n                    "metrics":{},\n                    "error":str(te),\n                    "protocol":{"mode":"blind_image_only_inference_then_hidden_ground_truth_scoring"},\n                }\n''',
)

print("training blind-test patch applied")
