import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(scope="session")
def synth_build(tmp_path_factory):
    """合成倉庫：產生 → 還原 → 匯出。整個測試階段共用一份。"""
    from pcd2scene.cli import main
    root = tmp_path_factory.mktemp("synth")
    assert main(["synth", str(root / "data"), "--spacing", "0.05"]) == 0
    assert main(["build", str(root / "data" / "warehouse.pcd"), "-c", str(root / "data" / "catalog.yaml"),
                 "-o", str(root / "out"), "--no-preview"]) == 0
    return root


@pytest.fixture(scope="session")
def office_build(tmp_path_factory):
    """合成辦公室：產生 → 還原（含 --stages）→ 匯出。"""
    from pcd2scene.cli import main
    root = tmp_path_factory.mktemp("office")
    assert main(["synth", str(root / "data"), "--layout", "office", "--spacing", "0.05"]) == 0
    assert main(["build", str(root / "data" / "office.pcd"), "-c", str(root / "data" / "catalog.yaml"),
                 "-o", str(root / "out"), "--no-preview", "--stages"]) == 0
    return root
