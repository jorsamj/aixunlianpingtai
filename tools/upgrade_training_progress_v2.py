from pathlib import Path

METRICS = Path('platform_core/training_metrics.py')
WORKER = Path('train_worker.py')
RUNTIME = Path('static/modules/training-task-runtime.js')
MAIN = Path('static/main.mjs')
INDEX = Path('static/index.html')
PY_TEST = Path('tests/unit/test_training_progress_v2.py')
JS_TEST = Path('tests/frontend/training-progress-v2.test.mjs')

# ---- training_metrics.py: one durable epoch snapshot, written in the existing epoch transaction.
text = METRICS.read_text(encoding='utf-8')
old = 'import json\nimport os\nimport shutil\n'
new = 'import json\nimport math\nimport os\nimport shutil\n'
if text.count(old) != 1:
    raise SystemExit(f'metrics import anchor count={text.count(old)}')
text = text.replace(old, new, 1)

anchor = '''def read_metrics(path):\n    path = Path(path)\n    if not path.is_file():\n        return {}\n    try:\n        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1)) as db, db:\n            row = db.execute("SELECT value FROM summary WHERE id=1").fetchone()\n        return json.loads(row[0]) if row else {}\n    except (sqlite3.Error, ValueError, OSError):\n        return {}\n\n\nclass TrainingMetrics:\n'''
replacement = '''def read_metrics(path):\n    path = Path(path)\n    if not path.is_file():\n        return {}\n    try:\n        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1)) as db, db:\n            row = db.execute("SELECT value FROM summary WHERE id=1").fetchone()\n        return json.loads(row[0]) if row else {}\n    except (sqlite3.Error, ValueError, OSError):\n        return {}\n\n\ndef _finite_float(value):\n    try:\n        if hasattr(value, "item"):\n            value = value.item()\n        number = float(value)\n    except (TypeError, ValueError, RuntimeError):\n        return None\n    return number if math.isfinite(number) else None\n\n\ndef _numeric_mapping(value):\n    if not isinstance(value, dict):\n        return {}\n    result = {}\n    for key, raw in value.items():\n        number = _finite_float(raw)\n        if number is not None:\n            result[str(key)] = round(number, 6)\n    return result\n\n\ndef _loss_snapshot(trainer):\n    names = [str(value) for value in (getattr(trainer, "loss_names", ()) or ())]\n    raw = getattr(trainer, "tloss", None)\n    if raw is None:\n        return {}\n    try:\n        if hasattr(raw, "detach"):\n            raw = raw.detach()\n        if hasattr(raw, "cpu"):\n            raw = raw.cpu()\n        if hasattr(raw, "tolist"):\n            raw = raw.tolist()\n        values = list(raw) if isinstance(raw, (list, tuple)) else [raw]\n    except (TypeError, RuntimeError):\n        return {}\n    result = {}\n    for index, value in enumerate(values):\n        number = _finite_float(value)\n        if number is None:\n            continue\n        key = names[index] if index < len(names) else f"loss_{index}"\n        result[key] = round(number, 6)\n    return result\n\n\ndef _learning_rate_snapshot(trainer):\n    current = _numeric_mapping(getattr(trainer, "lr", None))\n    if current:\n        return current\n    optimizer = getattr(trainer, "optimizer", None)\n    groups = getattr(optimizer, "param_groups", ()) if optimizer is not None else ()\n    result = {}\n    for index, group in enumerate(groups or ()):\n        if not isinstance(group, dict):\n            continue\n        number = _finite_float(group.get("lr"))\n        if number is not None:\n            result[f"lr/pg{index}"] = round(number, 10)\n    return result\n\n\ndef _trainer_total_epochs(trainer, completed):\n    total = getattr(trainer, "epochs", None)\n    if total is None:\n        total = getattr(getattr(trainer, "args", None), "epochs", None)\n    try:\n        return max(int(completed), int(total))\n    except (TypeError, ValueError):\n        return int(completed)\n\n\nclass TrainingMetrics:\n'''
if text.count(anchor) != 1:
    raise SystemExit(f'metrics helper anchor count={text.count(anchor)}')
text = text.replace(anchor, replacement, 1)

old = '''        self.epoch_duration = self.images_per_second = None\n        self.oom = False\n'''
new = '''        self.epoch_duration = self.images_per_second = None\n        self.epoch_durations = []\n        self.latest_epoch = None\n        self.oom = False\n'''
if text.count(old) != 1:
    raise SystemExit(f'metrics init anchor count={text.count(old)}')
text = text.replace(old, new, 1)

old = '''            summary = dict(self.resolved, latest=sample, diagnostic=diagnose_window(rows, self.oom),\n                           epoch_duration_seconds=self.epoch_duration, images_per_second=self.images_per_second,\n                           total_duration_seconds=round(time.monotonic() - self.started, 3),\n                           sampled_at=sample["sampled_at"], interval_seconds=self.interval)\n'''
new = '''            summary = dict(self.resolved, latest=sample, diagnostic=diagnose_window(rows, self.oom),\n                           epoch_duration_seconds=self.epoch_duration, images_per_second=self.images_per_second,\n                           latest_epoch=self.latest_epoch,\n                           total_duration_seconds=round(time.monotonic() - self.started, 3),\n                           sampled_at=sample["sampled_at"], interval_seconds=self.interval)\n'''
if text.count(old) != 1:
    raise SystemExit(f'metrics sample summary anchor count={text.count(old)}')
text = text.replace(old, new, 1)

old = '''    def on_epoch_end(self, trainer):\n        duration = max(0.001, time.monotonic() - self.epoch_started)\n        count = len(trainer.train_loader.dataset)\n        with self.lock, closing(self.connect()) as db, db:\n            self.epoch_duration = round(duration, 3)\n            self.images_per_second = round(count / duration, 3)\n            db.execute("INSERT INTO epochs(value) VALUES (?)", (json.dumps(dict(\n                epoch=int(trainer.epoch) + 1, duration_seconds=self.epoch_duration,\n                images_per_second=self.images_per_second, images=count)),))\n            db.execute("DELETE FROM epochs WHERE id NOT IN (SELECT id FROM epochs ORDER BY id DESC LIMIT 1000)")\n'''
new = '''    def on_epoch_end(self, trainer):\n        now = time.monotonic()\n        duration = max(0.001, now - self.epoch_started)\n        count = len(trainer.train_loader.dataset)\n        completed = int(trainer.epoch) + 1\n        total = _trainer_total_epochs(trainer, completed)\n        sampled_at = datetime.now(timezone.utc).isoformat()\n        with self.lock, closing(self.connect()) as db, db:\n            self.epoch_duration = round(duration, 3)\n            self.images_per_second = round(count / duration, 3)\n            self.epoch_durations.append(self.epoch_duration)\n            self.epoch_durations = self.epoch_durations[-20:]\n            window = self.epoch_durations[-5:]\n            average_duration = round(sum(window) / len(window), 3)\n            eta_seconds = round(average_duration * max(0, total - completed), 3)\n            epoch = {\n                "epoch": completed,\n                "total_epochs": total,\n                "duration_seconds": self.epoch_duration,\n                "average_epoch_duration_seconds": average_duration,\n                "elapsed_seconds": round(now - self.started, 3),\n                "eta_seconds": eta_seconds,\n                "images_per_second": self.images_per_second,\n                "images": count,\n                "losses": _loss_snapshot(trainer),\n                "metrics": _numeric_mapping(getattr(trainer, "metrics", None)),\n                "learning_rates": _learning_rate_snapshot(trainer),\n                "eta_basis": "rolling_last_5_epochs",\n                "sampled_at": sampled_at,\n            }\n            self.latest_epoch = epoch\n            db.execute("INSERT INTO epochs(value) VALUES (?)", (json.dumps(epoch),))\n            db.execute("DELETE FROM epochs WHERE id NOT IN (SELECT id FROM epochs ORDER BY id DESC LIMIT 1000)")\n            row = db.execute("SELECT value FROM summary WHERE id=1").fetchone()\n            try:\n                summary = json.loads(row[0]) if row else {}\n            except (TypeError, ValueError, json.JSONDecodeError):\n                summary = {}\n            summary.update(self.resolved)\n            summary.update({\n                "epoch_duration_seconds": self.epoch_duration,\n                "images_per_second": self.images_per_second,\n                "latest_epoch": epoch,\n                "total_duration_seconds": epoch["elapsed_seconds"],\n                "sampled_at": sampled_at,\n                "interval_seconds": self.interval,\n            })\n            db.execute("INSERT OR REPLACE INTO summary VALUES (1,?)", (json.dumps(summary),))\n'''
if text.count(old) != 1:
    raise SystemExit(f'metrics epoch anchor count={text.count(old)}')
text = text.replace(old, new, 1)
METRICS.write_text(text, encoding='utf-8')

# ---- train_worker.py: epoch metrics are captured before publishing the job snapshot; no duplicate callback.
text = WORKER.read_text(encoding='utf-8')
anchor = '''def main():\n'''
helper = '''def publish_epoch_progress(job_file, telemetry, trainer, requested_total_epochs):\n    telemetry.on_epoch_end(trainer)\n    progress = dict(telemetry.latest_epoch or {})\n    epoch = int(progress.get("epoch") or (int(getattr(trainer, "epoch", 0)) + 1))\n    total = max(epoch, int(progress.get("total_epochs") or requested_total_epochs or epoch))\n    percent = round(min(90.0, epoch / max(1, total) * 90.0), 2)\n    update_job(\n        job_file,\n        current_epoch=epoch,\n        total_epochs=total,\n        progress_percent=percent,\n        training_progress=progress,\n        elapsed_seconds=progress.get("elapsed_seconds"),\n        eta_seconds=progress.get("eta_seconds"),\n        message=f"训练中 · Epoch {epoch}/{total}",\n    )\n    return progress\n\n\ndef main():\n'''
if text.count(anchor) != 1:
    raise SystemExit(f'worker main anchor count={text.count(anchor)}')
text = text.replace(anchor, helper, 1)
old = '''        def on_fit_epoch_end(trainer):\n            nonlocal gate_reason, ai_plan, ai_rounds\n            epoch=int(getattr(trainer,"epoch",0))+1\n            update_job(\n                job_file,\n                current_epoch=epoch,\n                total_epochs=int(args.epochs),\n                progress_percent=round(min(90.0, epoch / max(1, int(args.epochs)) * 90.0), 2),\n                message=f"训练中 · Epoch {epoch}/{int(args.epochs)}",\n            )\n'''
new = '''        def on_fit_epoch_end(trainer):\n            nonlocal gate_reason, ai_plan, ai_rounds\n            progress = publish_epoch_progress(job_file, telemetry, trainer, int(args.epochs))\n            epoch = int(progress.get("epoch") or (int(getattr(trainer,"epoch",0))+1))\n'''
if text.count(old) != 1:
    raise SystemExit(f'worker epoch publish anchor count={text.count(old)}')
text = text.replace(old, new, 1)
old = '            target.add_callback("on_fit_epoch_end", telemetry.on_epoch_end)\n'
if text.count(old) != 1:
    raise SystemExit(f'worker duplicate telemetry callback count={text.count(old)}')
text = text.replace(old, '', 1)
WORKER.write_text(text, encoding='utf-8')

# ---- training-task-runtime.js: render the compact truthful snapshot, never synthesize zero-valued metrics.
text = RUNTIME.read_text(encoding='utf-8')
anchor = '''function dateText(value) {\n'''
helper = '''function finiteNumber(value) {\n  if (value === null || value === undefined || value === '') return null;\n  const number = Number(value);\n  return Number.isFinite(number) ? number : null;\n}\n\nfunction metricValue(values, aliases) {\n  if (!values || typeof values !== 'object') return null;\n  const normalized = new Map(Object.entries(values).map(([key, value]) => [String(key).toLowerCase().replace(/\\s+/g, ''), value]));\n  for (const alias of aliases) {\n    const value = finiteNumber(normalized.get(String(alias).toLowerCase().replace(/\\s+/g, '')));\n    if (value !== null) return value;\n  }\n  return null;\n}\n\nfunction metricText(value, digits = 3) {\n  return value === null ? '' : Number(value).toFixed(digits);\n}\n\nexport function trainingProgressView(job = {}) {\n  const progress = job.training_progress && typeof job.training_progress === 'object' ? job.training_progress : {};\n  const epoch = finiteNumber(progress.epoch) ?? finiteNumber(job.current_epoch) ?? 0;\n  const totalEpochs = finiteNumber(progress.total_epochs) ?? finiteNumber(job.total_epochs) ?? finiteNumber(job.epochs);\n  const elapsedSeconds = finiteNumber(progress.elapsed_seconds) ?? finiteNumber(job.elapsed_seconds);\n  const etaSeconds = finiteNumber(progress.eta_seconds) ?? finiteNumber(job.eta_seconds);\n  const throughput = finiteNumber(progress.images_per_second);\n  const losses = progress.losses || {};\n  const metrics = progress.metrics || {};\n  const learningRates = progress.learning_rates || {};\n  const boxLoss = metricValue(losses, ['box_loss', 'train/box_loss']);\n  const clsLoss = metricValue(losses, ['cls_loss', 'train/cls_loss']);\n  const dflLoss = metricValue(losses, ['dfl_loss', 'train/dfl_loss']);\n  const map50 = metricValue(metrics, ['metrics/map50(b)', 'metrics/map50', 'map50']);\n  const map5095 = metricValue(metrics, ['metrics/map50-95(b)', 'metrics/map50-95', 'map50-95', 'map']);\n  const primaryLr = Object.values(learningRates).map(finiteNumber).find(value => value !== null) ?? null;\n  const parts = [];\n  if (map50 !== null) parts.push(`mAP50 ${metricText(map50)}`);\n  if (map5095 !== null) parts.push(`mAP50-95 ${metricText(map5095)}`);\n  if (boxLoss !== null) parts.push(`box loss ${metricText(boxLoss, 4)}`);\n  if (clsLoss !== null) parts.push(`cls loss ${metricText(clsLoss, 4)}`);\n  if (dflLoss !== null) parts.push(`dfl loss ${metricText(dflLoss, 4)}`);\n  if (throughput !== null) parts.push(`${metricText(throughput, 1)} img/s`);\n  if (primaryLr !== null) parts.push(`LR ${Number(primaryLr).toPrecision(3)}`);\n  return {epoch, totalEpochs, elapsedSeconds, etaSeconds, metricLine: parts.join(' · ')};\n}\n\nfunction dateText(value) {\n'''
if text.count(anchor) != 1:
    raise SystemExit(f'runtime helper anchor count={text.count(anchor)}')
text = text.replace(anchor, helper, 1)
old = '''export function trainingTaskRow(job) {\n  const percent = Math.max(0, Math.min(100, Number(job?.progress_percent || 0)));\n  const totalEpochs = job?.total_epochs || job?.epochs || '-';\n  const queueMeta = queueRuntimeMeta(job);\n  const workerMeta = workerRuntimeMeta(job);\n  return `<tr data-job-id="${esc(job.id)}"><td><div class="train428-taskname"><b>${esc(job.asset_algorithm_name || job.algorithm_name || job.id)}</b><span>${esc(job.id)}</span>${job.auto_version_name ? `<em>版本 ${esc(job.auto_version_name)}</em>` : ''}</div></td><td><span class="pill ${statusClass(job.status)}">${esc(statusText(job.status))}</span><small class="queuepriority428">优先级 ${priorityValue(job)}</small>${queueMeta ? `<small>${esc(queueMeta)}</small>` : ''}</td><td><div class="train428-resource"><b>${esc(resourceName(job))}</b><span>${esc(job.framework === 'paddle' ? 'PaddleDetection' : 'Ultralytics / YOLO')}</span>${workerMeta ? `<span>${esc(workerMeta)}</span>` : ''}</div></td><td><div class="progress424"><i style="width:${percent}%"></i></div><span class="train428-progress-txt">${job.current_epoch || 0}/${esc(totalEpochs)} · ${percent.toFixed(0)}%${job.current_item ? ` · ${esc(job.current_item)}` : ''}</span></td><td>${esc(duration(job.elapsed_seconds))}</td><td>${esc(duration(job.eta_seconds))}</td><td>${esc(dateText(job.started_at || job.created_at))}</td><td><div class="row wrap">${actions(job)}</div></td></tr>`;\n}\n'''
new = '''export function trainingTaskRow(job) {\n  const percent = Math.max(0, Math.min(100, Number(job?.progress_percent || 0)));\n  const progress = trainingProgressView(job);\n  const totalEpochs = progress.totalEpochs ?? '-';\n  const queueMeta = queueRuntimeMeta(job);\n  const workerMeta = workerRuntimeMeta(job);\n  const currentItem = job.current_item && String(job.current_item) !== String(progress.epoch) ? ` · ${esc(job.current_item)}` : '';\n  return `<tr data-job-id="${esc(job.id)}"><td><div class="train428-taskname"><b>${esc(job.asset_algorithm_name || job.algorithm_name || job.id)}</b><span>${esc(job.id)}</span>${job.auto_version_name ? `<em>版本 ${esc(job.auto_version_name)}</em>` : ''}</div></td><td><span class="pill ${statusClass(job.status)}">${esc(statusText(job.status))}</span><small class="queuepriority428">优先级 ${priorityValue(job)}</small>${queueMeta ? `<small>${esc(queueMeta)}</small>` : ''}</td><td><div class="train428-resource"><b>${esc(resourceName(job))}</b><span>${esc(job.framework === 'paddle' ? 'PaddleDetection' : 'Ultralytics / YOLO')}</span>${workerMeta ? `<span>${esc(workerMeta)}</span>` : ''}</div></td><td><div class="progress424"><i style="width:${percent}%"></i></div><span class="train428-progress-txt">${progress.epoch}/${esc(totalEpochs)} · ${percent.toFixed(0)}%${currentItem}</span>${progress.metricLine ? `<small class="train428-metrics">${esc(progress.metricLine)}</small>` : ''}</td><td>${esc(duration(progress.elapsedSeconds))}</td><td>${esc(duration(progress.etaSeconds))}</td><td>${esc(dateText(job.started_at || job.created_at))}</td><td><div class="row wrap">${actions(job)}</div></td></tr>`;\n}\n'''
if text.count(old) != 1:
    raise SystemExit(f'runtime row anchor count={text.count(old)}')
text = text.replace(old, new, 1)
RUNTIME.write_text(text, encoding='utf-8')

# ---- cache bust only the files actually changed; formal release version remains untouched.
text = MAIN.read_text(encoding='utf-8')
old = "./modules/training-task-runtime.js?v=422504"
new = "./modules/training-task-runtime.js?v=422505"
if text.count(old) != 1:
    raise SystemExit(f'main training task cache anchor count={text.count(old)}')
MAIN.write_text(text.replace(old, new, 1), encoding='utf-8')

text = INDEX.read_text(encoding='utf-8')
old = '/static/main.mjs?v=42.25.91'
new = '/static/main.mjs?v=42.25.92'
if text.count(old) != 1:
    raise SystemExit(f'index main cache anchor count={text.count(old)}')
INDEX.write_text(text.replace(old, new, 1), encoding='utf-8')

# ---- permanent focused contracts.
PY_TEST.write_text(r'''from types import SimpleNamespace

import platform_core.training_metrics as training_metrics
from train_worker import publish_epoch_progress, read_json


def _resolved():
    return {"resolved_batch": 4, "resolved_workers": 0, "resolved_cache": False}


def _trainer():
    return SimpleNamespace(
        epoch=4,
        epochs=10,
        args=SimpleNamespace(epochs=10),
        train_loader=SimpleNamespace(dataset=list(range(120))),
        loss_names=("box_loss", "cls_loss", "dfl_loss"),
        tloss=[0.51, 0.22, 0.17],
        metrics={
            "metrics/precision(B)": 0.81,
            "metrics/recall(B)": 0.73,
            "metrics/mAP50(B)": 0.66,
            "metrics/mAP50-95(B)": 0.41,
            "ignored/non_numeric": object(),
        },
        lr={"lr/pg0": 0.001, "lr/pg1": 0.0005},
        optimizer=None,
    )


def test_epoch_completion_persists_truthful_progress_without_an_extra_db_connection(tmp_path, monkeypatch):
    db_path = tmp_path / "training-metrics.sqlite3"
    monkeypatch.setattr(training_metrics.time, "monotonic", lambda: 100.0)
    metrics = training_metrics.TrainingMetrics(db_path, _resolved(), interval=999)
    metrics.psutil = None
    metrics.started = 40.0
    metrics.epoch_started = 88.0

    metrics.on_epoch_end(_trainer())

    progress = metrics.latest_epoch
    assert progress["epoch"] == 5
    assert progress["total_epochs"] == 10
    assert progress["duration_seconds"] == 12.0
    assert progress["average_epoch_duration_seconds"] == 12.0
    assert progress["elapsed_seconds"] == 60.0
    assert progress["eta_seconds"] == 60.0
    assert progress["images_per_second"] == 10.0
    assert progress["losses"] == {"box_loss": 0.51, "cls_loss": 0.22, "dfl_loss": 0.17}
    assert progress["metrics"]["metrics/mAP50(B)"] == 0.66
    assert "ignored/non_numeric" not in progress["metrics"]
    assert progress["learning_rates"]["lr/pg0"] == 0.001
    assert progress["eta_basis"] == "rolling_last_5_epochs"

    summary = training_metrics.read_metrics(db_path)
    assert summary["latest_epoch"] == progress
    assert summary["epoch_duration_seconds"] == 12.0
    assert summary["images_per_second"] == 10.0


def test_worker_publishes_epoch_snapshot_to_existing_job_contract(tmp_path):
    job_file = tmp_path / "job.json"
    job_file.write_text('{"id":"job-1","status":"running"}', encoding="utf-8")

    class Telemetry:
        latest_epoch = None
        def on_epoch_end(self, trainer):
            self.latest_epoch = {
                "epoch": 3, "total_epochs": 8, "elapsed_seconds": 44.5, "eta_seconds": 75.0,
                "images_per_second": 22.0, "losses": {"box_loss": 0.4},
                "metrics": {"metrics/mAP50(B)": 0.7}, "learning_rates": {"lr/pg0": 0.001},
            }

    progress = publish_epoch_progress(job_file, Telemetry(), SimpleNamespace(epoch=2), 8)
    job = read_json(job_file, {})
    assert progress["epoch"] == 3
    assert job["current_epoch"] == 3
    assert job["total_epochs"] == 8
    assert job["progress_percent"] == 33.75
    assert job["elapsed_seconds"] == 44.5
    assert job["eta_seconds"] == 75.0
    assert job["training_progress"]["metrics"]["metrics/mAP50(B)"] == 0.7
    assert job["message"] == "训练中 · Epoch 3/8"
''', encoding='utf-8')

JS_TEST.write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';

import {trainingProgressView, trainingTaskRow} from '../../static/modules/training-task-runtime.js';

test('training progress v2 renders real epoch metrics throughput and rolling ETA', () => {
  const job = {
    id: 'train-v2', status: 'running', progress_percent: 45, framework: 'ultralytics',
    current_item: '5', elapsed_seconds: 999, eta_seconds: 999,
    training_progress: {
      epoch: 5, total_epochs: 10, elapsed_seconds: 60, eta_seconds: 61,
      images_per_second: 10.25,
      losses: {box_loss: 0.51234, cls_loss: 0.22345, dfl_loss: 0.17891},
      metrics: {'metrics/mAP50(B)': 0.6612, 'metrics/mAP50-95(B)': 0.4123},
      learning_rates: {'lr/pg0': 0.001},
    },
  };
  const view = trainingProgressView(job);
  assert.equal(view.epoch, 5);
  assert.equal(view.totalEpochs, 10);
  assert.equal(view.elapsedSeconds, 60);
  assert.equal(view.etaSeconds, 61);
  assert.match(view.metricLine, /mAP50 0\.661/);
  assert.match(view.metricLine, /mAP50-95 0\.412/);
  assert.match(view.metricLine, /box loss 0\.5123/);
  assert.match(view.metricLine, /10\.3 img\/s/);
  assert.match(view.metricLine, /LR 0\.00100/);

  const html = trainingTaskRow(job);
  assert.match(html, /5\/10 · 45%/);
  assert.doesNotMatch(html, /45% · 5/);
  assert.match(html, /mAP50 0\.661/);
  assert.match(html, />1m 1s</);
  assert.doesNotMatch(html, />16m 39s</);
});

test('training progress v2 omits unavailable metrics instead of manufacturing zeroes', () => {
  const view = trainingProgressView({id: 'queued', status: 'queued', progress_percent: 0});
  assert.equal(view.metricLine, '');
  const html = trainingTaskRow({id: 'queued', status: 'queued', progress_percent: 0});
  assert.doesNotMatch(html, /mAP50/);
  assert.doesNotMatch(html, /box loss/);
  assert.doesNotMatch(html, /img\/s/);
});
''', encoding='utf-8')

print('training progress v2 migration applied')
