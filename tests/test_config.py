import pytest

from pcd2scene.config import DEFAULTS, load_config


def test_empty_section_keeps_defaults(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("walls:\n#  min_fill: 0.24\nobjects:\n  min_points: 10\n", encoding="utf-8")
    cfg = load_config(p)
    assert cfg["walls"] == DEFAULTS["walls"]
    assert cfg["objects"]["min_points"] == 10


def test_section_must_be_mapping(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("walls: 0.3\n", encoding="utf-8")
    with pytest.raises(TypeError, match="walls must be a mapping"):
        load_config(p)


def test_unknown_key_rejected(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text("walls:\n  min_fil: 0.3\n", encoding="utf-8")
    with pytest.raises(KeyError, match="walls.min_fil"):
        load_config(p)
