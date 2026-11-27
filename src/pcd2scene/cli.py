"""命令列入口。

  pcd2scene build  CLOUD -o OUT [-c CONFIG.yaml] [--formats urdf,sdf,usd] [--frame scene|input]
  pcd2scene export OUT/scene.json --formats urdf [--frame input]
  pcd2scene synth  OUT [--seed 0]
  pcd2scene compare OUT/scene.json TRUTH.json
  pcd2scene accept OUT examples/<name>/accept.json
  pcd2scene info   CLOUD
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

from . import __version__


def _dump(path, obj):
    Path(path).write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def cmd_build(a):
    from .config import load_config
    from .export import copy_mesh_assets, export_all
    from .io_pcd import read_cloud
    from .mesh import write_stl
    from .overview import write_overview
    from .reconstruct import reconstruct
    from .validate import validate

    cfg = load_config(a.config)
    if a.formats:
        cfg["export"]["formats"] = a.formats.split(",")
    if a.frame:
        cfg["export"]["frame"] = a.frame
    out = Path(a.out)
    if out.exists() and any(out.iterdir()) and not a.force:
        print(f"output directory not empty: {out} (use --force)", file=sys.stderr)
        return 2
    (out / "meshes").mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    cloud = read_cloud(a.cloud)
    scene, meshes, P, label = reconstruct(cloud, cfg, log=lambda s: print(s, flush=True))
    for name, (v, t) in meshes.items():
        write_stl(out / "meshes" / f"{name}.stl", v, t)
    copy_mesh_assets(scene, out, Path(a.config).parent if a.config else Path.cwd())
    _dump(out / "scene.json", scene)
    _dump(out / "config.resolved.json", cfg)
    written = export_all(scene, out, cfg["export"]["formats"], cfg["export"]["frame"], cfg["export"]["mesh_uri"])
    rep = validate(scene, P, label, out, cfg)
    rep["seconds"] = round(time.monotonic() - t0, 2)
    rep["outputs"] = ["scene.json", "overview.svg", "report.json"] + written
    _dump(out / "report.json", rep)
    write_overview(scene, P, label, out / "overview.svg")
    if not a.no_preview:
        from .render import render_preview
        pv = cfg["preview"]
        render_preview(scene, P, label, out, out / "preview.png", pv["width"], pv["height"], pv["azimuth_deg"],
                       pv["elevation_deg"])
        rep["outputs"].append("preview.png")
        _dump(out / "report.json", rep)
    cov = ", ".join(f"{k} m {v:.3f}" for k, v in rep["coverage"].items())
    print(f"coverage: {cov}; elements: {rep['elements']}")
    print(f"wrote {out}: {', '.join(rep['outputs'])}")
    return 0


def cmd_export(a):
    from .export import export_all
    scene = json.loads(Path(a.scene).read_text(encoding="utf-8"))
    out = Path(a.scene).parent
    print("wrote", export_all(scene, out, a.formats.split(","), a.frame, a.mesh_uri))
    return 0


def cmd_synth(a):
    from .synth import generate
    path, n = generate(a.out, seed=a.seed, spacing=a.spacing, noise=a.noise)
    print(f"wrote {path} ({n} points), truth.json, catalog.yaml")
    return 0


def cmd_compare(a):
    from .evaluate import compare
    res = compare(json.loads(Path(a.scene).read_text()), json.loads(Path(a.truth).read_text()))
    if a.out:
        _dump(a.out, res)
    bad = [r for r in res["walls"] + res["objects"] if not r["ok"]]
    print(f"floor {res['floor']}; walls {len(res['walls']) - sum(not r['ok'] for r in res['walls'])}/"
          f"{len(res['walls'])}; objects {len(res['objects']) - sum(not r['ok'] for r in res['objects'])}/"
          f"{len(res['objects'])}; extra objects {res['extra_objects']}; extra walls {res['extra_walls']}")
    for r in bad:
        print("  mismatch:", r)
    print("PASS" if res["pass"] else "FAIL")
    return 0 if res["pass"] else 1


def cmd_accept(a):
    from .accept import check
    rows, m = check(a.out_dir, a.spec)
    width = max(len(str(r[0])) for r in rows) if rows else 10
    for name, v, want, ok in rows:
        print(f"{'PASS' if ok else 'FAIL'}  {name:<{width}}  {v}  ({want})")
    passed = all(r[3] for r in rows)
    if a.json:
        _dump(a.json, {"pass": passed, "metrics": m,
                       "rules": [{"name": r[0], "value": r[1], "want": r[2], "ok": r[3]} for r in rows]})
    print("ACCEPT" if passed else "REJECT")
    return 0 if passed else 1


def cmd_info(a):
    from .io_pcd import read_cloud
    c = read_cloud(a.cloud)
    p = c.xyz
    print(json.dumps({"file": c.source, "sha256": c.sha256, "points_raw": c.raw_points, "points_finite": len(p),
                      "min": np.round(p.min(0), 3).tolist(), "max": np.round(p.max(0), 3).tolist(),
                      "intensity": c.intensity is not None}, indent=1))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="pcd2scene", description="point cloud -> simulation scene (URDF, SDF, USD)")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="reconstruct a scene from a point cloud")
    b.add_argument("cloud")
    b.add_argument("-o", "--out", required=True)
    b.add_argument("-c", "--config")
    b.add_argument("--formats")
    b.add_argument("--frame", choices=["scene", "input"])
    b.add_argument("--force", action="store_true")
    b.add_argument("--no-preview", action="store_true", help="skip the software-rendered preview.png")
    b.set_defaults(fn=cmd_build)
    e = sub.add_parser("export", help="re-export scene.json")
    e.add_argument("scene")
    e.add_argument("--formats", default="urdf,sdf,usd")
    e.add_argument("--frame", default="scene", choices=["scene", "input"])
    e.add_argument("--mesh-uri", default="relative")
    e.set_defaults(fn=cmd_export)
    s = sub.add_parser("synth", help="generate a synthetic warehouse cloud with ground truth")
    s.add_argument("out")
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--spacing", type=float, default=0.04)
    s.add_argument("--noise", type=float, default=0.01)
    s.set_defaults(fn=cmd_synth)
    c = sub.add_parser("compare", help="compare scene.json with synth truth.json")
    c.add_argument("scene")
    c.add_argument("truth")
    c.add_argument("--out")
    c.set_defaults(fn=cmd_compare)
    ac = sub.add_parser("accept", help="check an output directory against an acceptance spec")
    ac.add_argument("out_dir")
    ac.add_argument("spec")
    ac.add_argument("--json")
    ac.set_defaults(fn=cmd_accept)
    i = sub.add_parser("info", help="print point cloud summary")
    i.add_argument("cloud")
    i.set_defaults(fn=cmd_info)
    a = ap.parse_args(argv)
    return a.fn(a)
