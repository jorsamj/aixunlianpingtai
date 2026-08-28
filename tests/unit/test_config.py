from pathlib import Path

from platform_core.config import choose_data_dir


def test_explicit_data_dir_always_wins(tmp_path: Path):
    explicit = tmp_path / "explicit"
    old = tmp_path / "XiaojiangAlgorithmTrain" / "data"
    new = tmp_path / "XJAlgo" / "data"
    assert choose_data_dir(explicit, [old, new]) == explicit.resolve()


def test_non_empty_legacy_dir_beats_empty_new_dir(tmp_path: Path):
    old = tmp_path / "XiaojiangAlgorithmTrain" / "data"
    new = tmp_path / "XJAlgo" / "data"
    old.mkdir(parents=True)
    new.mkdir(parents=True)
    (old / "projects.json").write_text('[{"id":"p1"}]', encoding="utf-8")
    (new / "projects.json").write_text("[]", encoding="utf-8")
    assert choose_data_dir(None, [new, old]) == old.resolve()

