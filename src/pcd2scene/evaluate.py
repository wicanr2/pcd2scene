"""還原結果對真值（synth 產生的 truth.json）。

真值在合成時的座標；先用 T_input_from_truth 轉到輸入座標，再用還原得到的 T_scene_from_input 轉到場景座標比較。
"""
from __future__ import annotations

import math

import numpy as np

from .geometry import apply_T

TOL = {"center": 0.2, "yaw_deg": 3.0, "wall_length": 0.4, "level": 0.05, "ceiling": 0.05}


def _to_scene(scene, truth):
    T = np.asarray(scene["frame"]["T_scene_from_input"], float) @ np.asarray(truth["T_input_from_truth"], float)
    return T


def _yaw_map(T, yaw):
    d = T[:3, :3] @ np.array([math.cos(yaw), math.sin(yaw), 0.0])
    return math.atan2(d[1], d[0])


def _ang(a, b, period=math.pi):
    d = (a - b) % period
    return math.degrees(min(d, period - d))


def compare(scene, truth, tol=TOL):
    T = _to_scene(scene, truth)
    res = {"floor": {}, "walls": [], "objects": [], "pass": True}
    x0, x1, y0, y1 = truth.get("floor_extent", (-12, 12, -7, 7))
    corners = np.array([[x, y, 0.0] for x in (x0, x1) for y in (y0, y1)])
    zc = apply_T(T, corners)[:, 2]
    res["floor"] = {"max_abs_z_at_corners": round(float(np.abs(zc).max()), 4)}
    if np.abs(zc).max() > 0.03:
        res["pass"] = False
    if truth.get("ceiling") is not None:
        ce = [e for e in scene["elements"] if e["kind"] == "ceiling"]
        got = ce[0]["stats"]["height"] if ce else None
        ok = got is not None and abs(got - truth["ceiling"]) <= tol["ceiling"]
        res["ceiling"] = {"truth": truth["ceiling"], "height": got, "ok": ok}
        res["pass"] &= ok
    walls = [e for e in scene["elements"] if e["kind"] == "wall"]
    for w in truth["walls"]:
        c = apply_T(T, np.array([[*w["center"], 0.0]]))[0, :2]
        yaw = _yaw_map(T, w["yaw"])
        best = None
        for e in walls:
            d = float(np.hypot(*(np.asarray(e["pose"]["xyz"][:2]) - c)))
            if best is None or d < best[0]:
                best = (d, e)
        row = {"truth_length": w["length"]}
        if best:
            d, e = best
            row.update(id=e["id"], center_err=round(d, 3), yaw_err_deg=round(_ang(e["pose"]["yaw"], yaw), 3),
                       length=e["parts"][0]["size"][0])
            row["ok"] = (d <= tol["center"] and row["yaw_err_deg"] <= tol["yaw_deg"]
                         and abs(row["length"] - w["length"]) <= tol["wall_length"])
        else:
            row["ok"] = False
        res["pass"] &= row["ok"]
        res["walls"].append(row)
    objs = [e for e in scene["elements"] if e["kind"] == "object"]
    used = set()
    for o in truth["objects"]:
        c = apply_T(T, np.array([[*o["center"], 0.0]]))[0, :2]
        yaw = _yaw_map(T, o["yaw"])
        best = None
        for e in objs:
            if e["class"] != o["class"] or e["id"] in used:
                continue
            d = float(np.hypot(*(np.asarray(e["pose"]["xyz"][:2]) - c)))
            if best is None or d < best[0]:
                best = (d, e)
        row = {"class": o["class"], "truth_units": o["units"]}
        if best and best[0] <= tol["center"]:
            d, e = best
            used.add(e["id"])
            row.update(id=e["id"], center_err=round(d, 3), yaw_err_deg=round(_ang(e["pose"]["yaw"], yaw), 3),
                       units=e.get("units", 1))
            row["ok"] = row["yaw_err_deg"] <= tol["yaw_deg"] and row["units"] == o["units"]
            if "levels" in o:
                got = e.get("model", {}).get("levels", [])
                row["levels"] = got
                row["ok"] &= len(got) == len(o["levels"]) and all(
                    abs(a - b) <= tol["level"] for a, b in zip(sorted(got), sorted(o["levels"])))
        else:
            row["ok"] = False
        res["pass"] &= row["ok"]
        res["objects"].append(row)
    res["extra_objects"] = sorted(e["id"] for e in objs if e["id"] not in used)
    res["extra_walls"] = max(0, len(walls) - len(truth["walls"]))
    return res
