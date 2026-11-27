"""驗收：從輸出目錄算出指標，逐條比對驗收規格（examples/*/accept.json）。

規格格式：{"files": [必須存在的檔案], "rules": {指標: {"min": x, "max": y, "eq": z}}}
指標：
- coverage.<tol>：report.json 的 coverage
- distance.median、distance.p95：report.json 的距離統計（m）
- count.<class>：該類別的元素數
- floor.tilt_deg：輸入地面相對 +z 的傾角
- ceiling.height：天花板離地高度（沒有天花板時是 null）
- compare.pass：compare.json 的結果（只有合成資料有）
"""
from __future__ import annotations

import json
from pathlib import Path


def metrics(out_dir):
    out_dir = Path(out_dir)
    rep = json.loads((out_dir / "report.json").read_text(encoding="utf-8"))
    scene = json.loads((out_dir / "scene.json").read_text(encoding="utf-8"))
    m = {f"coverage.{k}": v for k, v in rep["coverage"].items()}
    m["distance.median"] = rep["distance_m"]["median"]
    m["distance.p95"] = rep["distance_m"]["p95"]
    for cls, n in rep["elements"].items():
        m[f"count.{cls}"] = n
    m["ceiling.height"] = None
    for el in scene["elements"]:
        if el["kind"] == "floor":
            m["floor.tilt_deg"] = el["stats"]["tilt_deg"]
        if el["kind"] == "ceiling":
            m["ceiling.height"] = el["stats"]["height"]
    cmp_path = out_dir / "compare.json"
    if cmp_path.exists():
        m["compare.pass"] = json.loads(cmp_path.read_text(encoding="utf-8"))["pass"]
    return m


def check(out_dir, spec_path):
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    m = metrics(out_dir)
    rows = []
    for f in spec.get("files", []):
        ok = (Path(out_dir) / f).is_file()
        rows.append((f"file {f}", "present" if ok else "missing", "present", ok))
    for key, rule in spec.get("rules", {}).items():
        v = m.get(key, 0 if key.startswith("count.") else None)
        ok = v is not None
        if ok and "min" in rule:
            ok = v >= rule["min"]
        if ok and "max" in rule:
            ok = v <= rule["max"]
        if "eq" in rule:
            ok = v == rule["eq"]
        want = " ".join(f"{k} {rule[k]}" for k in ("min", "max", "eq") if k in rule)
        rows.append((key, v, want, bool(ok)))
    return rows, m
