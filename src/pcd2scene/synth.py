"""合成點雲與真值：測試與示範用，不依賴任何現場資料。

兩種版面（--layout）：
- warehouse：24 m x 14 m 地面、四面牆（南牆有 3 m 門口）、兩排貨架（第二排轉 30 度）、三張桌子、
  兩個棧板、兩個未登錄的箱子，沒有天花板。
- office：10 m x 7 m 辦公室、2.8 m 天花板、四面牆（南牆有 1 m 門口）、四張辦公桌、兩個櫃子、
  一排三格的書架、兩個未登錄的箱子（椅子大小）。
表面均勻取樣加高斯雜訊，不模擬遮蔽。最後整體套一個傾斜、旋轉、平移，
模擬定位地圖座標與重力方向不完全一致的情形。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .geometry import R_from_rpy, apply_T, make_T, pose_T
from .io_pcd import write_pcd
from .models import build_parts

RACK = {"class": "rack", "size": [2.7, 1.1, 3.0], "array": {"pitch": 2.7},
        "model": {"type": "rack", "levels": [1.0, 2.0], "upright": [0.09, 0.07], "beam": [0.1, 0.05]}}
TABLE = {"class": "table", "size": [1.6, 0.8, 0.75], "model": {"type": "table"}}
PALLET = {"class": "pallet", "size": [1.2, 1.0, 0.15], "model": {"type": "box"}}

CATALOG = [
    dict(RACK, tolerance=[0.3, 0.15, 0.25], model=dict(RACK["model"], levels="auto")),
    dict(TABLE, tolerance=[0.15, 0.1, 0.08]),
    dict(PALLET, tolerance=[0.1, 0.1, 0.06]),
]

DESK = {"class": "desk", "size": [1.4, 0.7, 0.74], "model": {"type": "table", "top_thickness": 0.03}}
CABINET = {"class": "cabinet", "size": [0.9, 0.45, 1.8], "model": {"type": "box"}}
SHELF = {"class": "shelf", "size": [1.0, 0.4, 2.0], "array": {"pitch": 1.0},
         "model": {"type": "rack", "levels": [0.7, 1.4], "upright": [0.04, 0.04], "beam": [0.05, 0.03],
                   "brace": [0.02, 0.5]}}

OFFICE_CATALOG = [
    dict(DESK, tolerance=[0.15, 0.1, 0.06]),
    dict(CABINET, tolerance=[0.1, 0.08, 0.1]),
    dict(SHELF, tolerance=[0.2, 0.08, 0.15], model=dict(SHELF["model"], levels="auto")),
]

LAYOUTS = ("warehouse", "office")


def _box_surface(size, center, rng, spacing, bottom=False):
    pts = []
    for ax in range(3):
        u, v = [a for a in range(3) if a != ax]
        area = size[u] * size[v]
        n = rng.poisson(area / spacing ** 2)
        for s in (-1, 1):
            if ax == 2 and s == -1 and not bottom:
                continue
            q = np.zeros((n, 3))
            q[:, u] = (rng.random(n) - 0.5) * size[u]
            q[:, v] = (rng.random(n) - 0.5) * size[v]
            q[:, ax] = s * size[ax] / 2
            pts.append(q + center)
    return np.concatenate(pts) if pts else np.zeros((0, 3))


def _plane(x0, x1, y0, y1, z, rng, spacing):
    n = rng.poisson((x1 - x0) * (y1 - y0) / spacing ** 2)
    return np.column_stack([rng.uniform(x0, x1, n), rng.uniform(y0, y1, n), np.full(n, z)])


def _wall_face(p0, p1, height, rng, spacing):
    """牆內側面：p0→p1 的直線，從 z=0 到 height。"""
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    L = np.linalg.norm(p1 - p0)
    n = rng.poisson(L * height / spacing ** 2)
    t = rng.random(n)
    xy = p0 + (p1 - p0) * t[:, None]
    return np.column_stack([xy, rng.random(n) * height])


def _warehouse():
    walls = [((-12, 7), (12, 7)), ((12, 7), (12, -7)), ((-12, -7), (-12, 7)),
             ((-12, -7), (-2, -7)), ((1, -7), (12, -7))]
    objects = [(RACK, 4, (-4.0, 3.5), 0.0), (RACK, 3, (4.0, -1.5), math.radians(30))]
    objects += [(TABLE, 1, xy, yaw) for xy, yaw in (((-8.0, -3.0), 0.0), ((-5.0, -3.0), math.radians(90)),
                                                     ((7.5, 4.0), math.radians(-15)))]
    objects += [(PALLET, 1, xy, yaw) for xy, yaw in (((-1.5, -5.0), 0.0), ((1.5, -5.5), math.radians(10)))]
    unknown = [((9.5, -5.0), (0.8, 0.6, 0.9)), ((-10.0, 1.0), (0.5, 0.5, 1.4))]
    T_in = make_T(R_from_rpy(math.radians(0.8), math.radians(-0.5), math.radians(25)), [12.3, -4.1, 0.9])
    return {"extent": (-12, 12, -7, 7), "height": 4.0, "thickness": 0.2, "ceiling": None, "walls": walls,
            "objects": objects, "unknown": unknown, "T_in": T_in, "catalog": CATALOG, "name": "warehouse"}


def _office():
    walls = [((-5, 3.5), (5, 3.5)), ((5, 3.5), (5, -3.5)), ((-5, -3.5), (-5, 3.5)),
             ((-5, -3.5), (1, -3.5)), ((2, -3.5), (5, -3.5))]
    objects = [(DESK, 1, xy, 0.0) for xy in ((-2.6, 1.6), (0.2, 1.6), (-2.6, -0.9), (0.2, -0.9))]
    objects += [(CABINET, 1, (4.4, y), math.radians(90)) for y in (1.6, 0.4)]
    objects += [(SHELF, 3, (-4.45, 0.2), math.radians(90))]
    unknown = [((-1.2, 0.35), (0.5, 0.5, 0.9)), ((2.6, -2.2), (0.5, 0.5, 0.9))]
    T_in = make_T(R_from_rpy(math.radians(-0.4), math.radians(0.6), math.radians(-40)), [3.2, 7.5, -1.1])
    return {"extent": (-5, 5, -3.5, 3.5), "height": 2.8, "thickness": 0.15, "ceiling": 2.8, "walls": walls,
            "objects": objects, "unknown": unknown, "T_in": T_in, "catalog": OFFICE_CATALOG, "name": "office",
            "preview": {"azimuth_deg": -60.0, "elevation_deg": 62.0}}


def generate(out_dir, seed=0, spacing=0.04, noise=0.01, layout="warehouse"):
    if layout not in LAYOUTS:
        raise ValueError(f"layout must be one of {LAYOUTS}")
    L = _warehouse() if layout == "warehouse" else _office()
    rng = np.random.default_rng(seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    clouds = []
    truth = {"layout": layout, "floor_extent": list(L["extent"]), "ceiling": L["ceiling"],
             "walls": [], "objects": [], "unknown": []}

    x0, x1, y0, y1 = L["extent"]
    clouds.append(_plane(x0, x1, y0, y1, 0.0, rng, spacing))
    if L["ceiling"] is not None:
        clouds.append(_plane(x0, x1, y0, y1, L["ceiling"], rng, spacing))
    H, th = L["height"], L["thickness"]
    # 牆：內側面座標；真值記牆盒（往外長 th）
    for p0, p1 in L["walls"]:
        clouds.append(_wall_face(p0, p1, H, rng, spacing))
        p0a, p1a = np.asarray(p0, float), np.asarray(p1, float)
        u = (p1a - p0a) / np.linalg.norm(p1a - p0a)
        nrm = np.array([-u[1], u[0]])
        mid = (p0a + p1a) / 2
        outward = nrm if mid @ nrm > 0 else -nrm
        c = mid + outward * th / 2
        truth["walls"].append({"center": c.tolist(), "yaw": math.atan2(u[1], u[0]),
                               "length": float(np.linalg.norm(p1a - p0a)), "thickness": th, "height": H})

    def place(entry, n, xy, yaw):
        T = pose_T([xy[0], xy[1], 0.0], yaw)
        parts, _ = build_parts(entry, n)
        for p in parts:
            clouds.append(apply_T(T, _box_surface(p["size"], np.asarray(p["xyz"]), rng, spacing, bottom=True)))
        row = {"class": entry["class"], "center": list(xy), "yaw": yaw, "units": n}
        if entry["model"]["type"] == "rack":
            row["levels"] = list(entry["model"]["levels"])
        truth["objects"].append(row)

    for entry, n, xy, yaw in L["objects"]:
        place(entry, n, xy, yaw)
    for xy, size in L["unknown"]:
        clouds.append(_box_surface(size, np.array([xy[0], xy[1], size[2] / 2]), rng, spacing))
        truth["unknown"].append({"center": list(xy), "size": list(size)})

    P = np.concatenate(clouds)
    P += rng.normal(0, noise, P.shape)
    T_in = L["T_in"]
    P = apply_T(T_in, P)
    P = P[rng.permutation(len(P))]
    write_pcd(out_dir / f"{layout}.pcd", P)
    truth["T_input_from_truth"] = T_in.tolist()
    truth["seed"], truth["spacing"], truth["noise"] = seed, spacing, noise
    (out_dir / "truth.json").write_text(json.dumps(truth, indent=1), encoding="utf-8")
    import yaml
    cfg = {"objects": {"catalog": L["catalog"]}}
    if "preview" in L:
        cfg["preview"] = L["preview"]
    (out_dir / "catalog.yaml").write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    return out_dir / f"{layout}.pcd", len(P)
