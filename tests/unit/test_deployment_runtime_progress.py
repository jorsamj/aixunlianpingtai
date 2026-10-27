import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from PIL import Image


def test_runner_reports_actual_loading_inference_and_result_stages(tmp_path, monkeypatch):
    progress = tmp_path / "progress.json"
    phases = []
    class Model:
        def __init__(self, model):
            phases.append(json.loads(progress.read_text())["phase"])
        def predict(self, **kwargs):
            phases.append(json.loads(progress.read_text())["phase"])
            return [SimpleNamespace(speed={}, names={}, boxes=[])]
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=Model))
    path = Path(__file__).resolve().parents[2] / "predict_ultralytics_runner.py"
    spec = importlib.util.spec_from_file_location("isolated_predict_runner", path)
    runner = importlib.util.module_from_spec(spec); spec.loader.exec_module(runner)
    image = tmp_path / "input.jpg"; Image.new("RGB", (20, 20)).save(image)
    monkeypatch.setenv("CHANGLIAN_DEPLOYMENT_PROGRESS", str(progress))
    monkeypatch.setattr(sys, "argv", [str(path), "--model", "isolated.pt", "--input", str(image), "--output", str(tmp_path / "out.jpg")])
    runner.main()
    assert phases == ["PREPARING_MODEL", "INFERENCING"]
    assert json.loads(progress.read_text())["phase"] == "GENERATING_RESULT"
    assert (tmp_path / "out.jpg").is_file()
