"""還原品質：輸入點到場景表面的距離，與場景表面有沒有點支撐。

- coverage@tol：輸入點（場景座標、體素後）離最近場景表面不超過 tol 的比例。量的是「點雲被場景解釋了多少」。
  刻意不建模的點（地面以下、天花板以上、drop 掉的叢集）另列，不算進 coverage。
- support@tol：每個元素表面取樣點離最近輸入點不超過 tol 的比例。量的是「模型有多少面有資料佐證」；
  貼地的底面、背牆面本來就掃不到，所以只當參考，不當驗收。
"""
from __future__ import annotations

import numpy as np
from scipy.spatial import cKDTree

from .geometry import apply_T, pose_T
from .mesh import read_stl

EXCLUDED = ("below_floor", "above_ceiling", "dropped")


def sample_box(size, step):
    sx, sy, sz = size
    out = []
    for ax in range(3):
        u, v = [a for a in range(3) if a != ax]
        nu = max(2, int(np.ceil(size[u] / step)) + 1)
        nv = max(2, int(np.ceil(size[v] / step)) + 1)
        gu, gv = np.meshgrid(np.linspace(-size[u] / 2, size[u] / 2, nu), np.linspace(-size[v] / 2, size[v] / 2, nv))
        for s in (-1, 1):
            f = np.zeros((gu.size, 3))
            f[:, u], f[:, v], f[:, ax] = gu.ravel(), gv.ravel(), s * size[ax] / 2
            out.append(f)
    return np.concatenate(out)


def scene_samples(scene, out_dir, step):
    pts, owner = [], []
    cache = {}
    for k, el in enumerate(scene["elements"]):
        T = pose_T(el["pose"]["xyz"], el["pose"]["yaw"])
        for p in el["parts"]:
            if p["type"] == "box":
                s = sample_box(p["size"], step) + np.asarray(p["xyz"])
            else:
                f = out_dir / p["file"]
                if f not in cache:
                    v, t = read_stl(f)
                    cache[f] = np.concatenate([v, v[t].mean(axis=1)])
                s = cache[f] * np.asarray(p["scale"]) + np.asarray(p["xyz"])
            pts.append(apply_T(T, s))
            owner.append(np.full(len(s), k))
    if not pts:
        return np.zeros((0, 3)), np.zeros(0, int)
    return np.concatenate(pts), np.concatenate(owner)


def validate(scene, P, label, out_dir, cfg):
    cv = cfg["validate"]
    tols = [float(t) for t in cv["tolerances"]]
    S, owner = scene_samples(scene, out_dir, cv["sample_step"])
    keep = ~np.isin(label, EXCLUDED)
    d, _ = cKDTree(S).query(P[keep], workers=1)
    rep = {"points_evaluated": int(keep.sum()), "points_excluded": int((~keep).sum()),
           "coverage": {f"{t:g}": round(float(np.mean(d <= t)), 4) for t in tols},
           "distance_m": {"median": round(float(np.median(d)), 4), "p95": round(float(np.percentile(d, 95)), 4),
                          "max": round(float(d.max()), 4)}}
    ds, _ = cKDTree(P).query(S, workers=1)
    tmax = max(tols)
    support = {}
    for k, el in enumerate(scene["elements"]):
        m = owner == k
        if m.any():
            support[el["id"]] = round(float(np.mean(ds[m] <= tmax)), 4)
    rep["support"] = {"tolerance": tmax, "by_element": support}
    by_class = {}
    for el in scene["elements"]:
        by_class[el["class"]] = by_class.get(el["class"], 0) + 1
    rep["elements"] = dict(sorted(by_class.items()))
    rep["labels"] = scene["source"].get("labels", {})
    return rep
