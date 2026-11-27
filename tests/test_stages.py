import json

import numpy as np

from pcd2scene.evaluate import compare
from pcd2scene.viewer import load

STAGES = ["01_input", "02_voxel", "03_level", "04_walls", "05_floor", "06_clusters", "07_match", "08_residual",
          "09_scene", "10_urdf", "11_usd"]


def test_office_matches_truth(office_build):
    scene = json.loads((office_build / "out" / "scene.json").read_text())
    truth = json.loads((office_build / "data" / "truth.json").read_text())
    res = compare(scene, truth)
    assert res["pass"], res
    assert res["ceiling"]["ok"] and res["extra_objects"] == [] and res["extra_walls"] == 0


def test_stage_images(office_build):
    sd = office_build / "out" / "stages"
    for name in STAGES:
        head = (sd / f"{name}.png").read_bytes()[:8]
        assert head == b"\x89PNG\r\n\x1a\n", name
    info = json.loads((sd / "stages.json").read_text())
    assert info["04_walls"]["walls"] == 5
    assert info["07_match"]["matched"] == {"cabinet": 2, "desk": 4, "shelf": 1}
    assert any(not c["accepted"] and "ceiling_contact" in c["reason"] for c in info["04_walls"]["candidates"])


def test_exported_formats_agree(office_build):
    """URDF、SDF、USD 從檔案讀回來的三角形要一致：同樣的盒子與網格、同樣的位置。"""
    out = office_build / "out"
    tris = {f: load(out / f)[0] for f in ("scene.urdf", "scene.sdf", "scene.usda")}
    n = {f: len(t) for f, t in tris.items()}
    assert len(set(n.values())) == 1, n
    ref = np.sort(tris["scene.urdf"].reshape(-1, 3), axis=0)
    for f in ("scene.sdf", "scene.usda"):
        assert np.allclose(np.sort(tris[f].reshape(-1, 3), axis=0), ref, atol=1e-4), f
