from pathlib import Path

from platform_core.paddle_command import build_paddle_command


def test_paddle_command_is_argv_and_preserves_spaces(tmp_path):
    command = build_paddle_command(
        python=tmp_path / "python executable",
        script=tmp_path / "tools" / "train.py",
        config=tmp_path / "configs" / "det model.yml",
        overrides={"epoch": 2, "use_gpu": False},
    )

    assert isinstance(command, list)
    assert command[:5] == [
        str(tmp_path / "python executable"),
        "-u",
        str(tmp_path / "tools" / "train.py"),
        "-c",
        str(tmp_path / "configs" / "det model.yml"),
    ]
    assert "epoch=2" in command
    assert "use_gpu=false" in command
    assert all("shell=" not in part for part in command)


def test_paddle_command_rejects_non_scalar_overrides(tmp_path):
    try:
        build_paddle_command(
            python=Path("python"),
            script=tmp_path / "train.py",
            config=tmp_path / "model.yml",
            overrides={"unsafe": ["a", "b"]},
        )
    except TypeError as error:
        assert "scalar" in str(error)
    else:
        raise AssertionError("non-scalar Paddle overrides must be rejected")
