import json
import xml.etree.ElementTree as ET
from pathlib import Path

from pcd2scene.cli import main
from pcd2scene.evaluate import compare

SCHEMA = Path(__file__).resolve().parents[1] / "schema" / "scene.schema.json"


def test_synth_matches_truth(synth_build):
    scene = json.loads((synth_build / "out" / "scene.json").read_text())
    truth = json.loads((synth_build / "data" / "truth.json").read_text())
    res = compare(scene, truth)
    assert res["pass"], res
    assert res["extra_objects"] == [] and res["extra_walls"] == 0


def test_scene_matches_schema(synth_build):
    import jsonschema
    scene = json.loads((synth_build / "out" / "scene.json").read_text())
    jsonschema.validate(scene, json.loads(SCHEMA.read_text()))


def test_report_coverage(synth_build):
    rep = json.loads((synth_build / "out" / "report.json").read_text())
    assert rep["coverage"]["0.1"] >= 0.99


def test_urdf_structure(synth_build):
    scene = json.loads((synth_build / "out" / "scene.json").read_text())
    root = ET.parse(synth_build / "out" / "scene.urdf").getroot()
    links = {l.get("name") for l in root.findall("link")}
    exported = [e["id"] for e in scene["elements"] if e.get("export", True)]
    assert links == {"world", "scene_root", *exported}
    joints = root.findall("joint")
    assert len(joints) == len(exported) + 1 and all(j.get("type") == "fixed" for j in joints)


def test_sdf_structure(synth_build):
    scene = json.loads((synth_build / "out" / "scene.json").read_text())
    root = ET.parse(synth_build / "out" / "scene.sdf").getroot()
    assert root.get("version") == "1.9"
    model = root.find("world/model")
    assert model.find("static").text == "true"
    assert len(model.findall("link")) == sum(e.get("export", True) for e in scene["elements"])


def test_usd_loads_and_complies(synth_build):
    from pxr import Usd, UsdGeom, UsdPhysics, UsdValidation
    stage = Usd.Stage.Open(str(synth_build / "out" / "scene.usda"))
    assert UsdGeom.GetStageUpAxis(stage) == UsdGeom.Tokens.z
    assert UsdGeom.GetStageMetersPerUnit(stage) == 1.0
    prims = list(stage.Traverse())
    assert sum(p.HasAPI(UsdPhysics.CollisionAPI) for p in prims) > 0
    reg = UsdValidation.ValidationRegistry()
    validators = reg.GetOrLoadValidatorsByName([m.name for m in reg.GetAllValidatorMetadata()])
    assert len(validators) > 0
    errors = UsdValidation.ValidationContext(validators).Validate(stage)
    assert errors == [], [e.GetErrorAsString() for e in errors]


def test_build_is_deterministic(synth_build, tmp_path):
    data = synth_build / "data"
    assert main(["build", str(data / "warehouse.pcd"), "-c", str(data / "catalog.yaml"), "-o", str(tmp_path),
                 "--no-preview"]) == 0
    for f in ("scene.json", "scene.urdf", "scene.sdf", "scene.usda", "meshes/residual.stl"):
        assert (tmp_path / f).read_bytes() == (synth_build / "out" / f).read_bytes(), f


def test_input_frame_export_round_trip(synth_build, tmp_path):
    """frame=input 時根節點帶反變換：地面角點回到原始點雲座標。"""
    import numpy as np
    from pcd2scene.export import root_T
    from pcd2scene.geometry import apply_T
    scene = json.loads((synth_build / "out" / "scene.json").read_text())
    truth = json.loads((synth_build / "data" / "truth.json").read_text())
    corner_truth = np.array([[12.0, 7.0, 0.0]])
    in_input = apply_T(np.asarray(truth["T_input_from_truth"]), corner_truth)
    in_scene = apply_T(np.asarray(scene["frame"]["T_scene_from_input"]), in_input)
    np.testing.assert_allclose(apply_T(root_T(scene, "input"), in_scene), in_input, atol=1e-6)
