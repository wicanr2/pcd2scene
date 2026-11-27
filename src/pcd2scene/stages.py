"""把還原流程每一步的中間結果畫成圖：`pcd2scene build --stages` 寫在輸出目錄的 `stages/`。

圖檔與流程步驟一一對應（見 docs/tutorial.md）：
  01_input        讀檔、套用 input.transform 與 input.crop 後的點（輸入座標，依高度上色）
  02_voxel        體素平均後的點
  03_level        轉正後，沿最長牆方向的剖面側視：地面（綠）、天花板（藍）、地面以下（橘）、其他點（深灰）
  04_walls        俯視：高格子（灰）、被拒絕的牆候選（橘線）、接受的牆（紅）
  05_floor        俯視：地面點與分解出的地面板
  06_clusters     剩下的點分群，每群一色
  07_match        俯視：每群的最小面積矩形；對上目錄的填類別色，沒對上的只畫框
  08_residual     殘餘網格
  09_scene        scene.json 的完整場景
  10_urdf、11_usd 從匯出的 scene.urdf、scene.usda 讀回來畫（viewer.py）
所有 3D 圖用同一個相機，方便前後對照。
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .export import class_color
from .geometry import apply_T, pose_T
from .mesh import read_stl
from .render import Camera, raster, scene_triangles, write_png

FLOOR, CEIL, WALL, RESID, LIGHT = (0.55, 0.55, 0.55), (0.45, 0.65, 0.95), (0.85, 0.45, 0.3), (0.45, 0.6, 0.75), \
    (0.85, 0.85, 0.85)
PALETTE = [(0.89, 0.1, 0.11), (0.22, 0.49, 0.72), (0.3, 0.69, 0.29), (0.6, 0.31, 0.64), (1.0, 0.5, 0.0),
           (0.65, 0.34, 0.16), (0.97, 0.51, 0.75), (0.1, 0.62, 0.62), (0.74, 0.74, 0.13), (0.4, 0.4, 0.4)]


def height_colors(z):
    t = (z - np.percentile(z, 1)) / max(1e-6, np.percentile(z, 99) - np.percentile(z, 1))
    t = np.clip(t, 0, 1)
    return np.column_stack([0.15 + 0.8 * t, 0.35 + 0.4 * (1 - np.abs(2 * t - 1)), 0.9 - 0.75 * t])


def splat(cam, P, colors, size=2):
    img = np.full((cam.h, cam.w, 3), 255.0)
    zbuf = np.full((cam.h, cam.w), np.inf)
    s = cam.project(P)
    order = np.argsort(-s[:, 2])
    col = np.asarray(colors, float) * 255
    for dx in range(size):
        for dy in range(size):
            x = (s[order, 0] + dx).astype(int)
            y = (s[order, 1] + dy).astype(int)
            ok = (x >= 0) & (x < cam.w) & (y >= 0) & (y < cam.h)
            xo, yo, zo, co = x[ok], y[ok], s[order, 2][ok], col[order][ok]
            closer = zo < zbuf[yo, xo]
            zbuf[yo[closer], xo[closer]] = zo[closer]
            img[yo[closer], xo[closer]] = co[closer]
    return img


class TopView:
    """俯視的正投影畫布：x 向右、y 向上。"""

    def __init__(self, lo, hi, width=900, margin=0.5):
        self.lo = np.asarray(lo[:2], float) - margin
        span = np.asarray(hi[:2], float) + margin - self.lo
        self.s = width / span[0]
        self.w, self.h = width, max(1, int(math.ceil(span[1] * self.s)))
        self.img = np.full((self.h, self.w, 3), 255.0)

    def px(self, xy):
        xy = np.atleast_2d(xy)
        return np.column_stack([(xy[:, 0] - self.lo[0]) * self.s, self.h - (xy[:, 1] - self.lo[1]) * self.s])

    def points(self, xy, color, size=1):
        q = self.px(xy).astype(int)
        col = np.broadcast_to(np.asarray(color, float) * 255, (len(q), 3))
        for dx in range(size):
            for dy in range(size):
                x, y = q[:, 0] + dx, q[:, 1] + dy
                ok = (x >= 0) & (x < self.w) & (y >= 0) & (y < self.h)
                self.img[y[ok], x[ok]] = col[ok]

    def line(self, a, b, color, width=2):
        a, b = self.px(a)[0], self.px(b)[0]
        n = int(max(2, np.hypot(*(b - a)) * 2))
        t = np.linspace(0, 1, n)[:, None]
        q = a + (b - a) * t
        r = width // 2
        for dx in range(-r, width - r):
            for dy in range(-r, width - r):
                x, y = (q[:, 0] + dx).astype(int), (q[:, 1] + dy).astype(int)
                ok = (x >= 0) & (x < self.w) & (y >= 0) & (y < self.h)
                self.img[y[ok], x[ok]] = np.asarray(color, float) * 255

    def poly(self, corners, fill=None, edge=None, width=2, alpha=1.0):
        q = self.px(corners)
        if fill is not None:
            x0, y0 = np.floor(q.min(axis=0)).astype(int)
            x1, y1 = np.ceil(q.max(axis=0)).astype(int)
            x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, self.w - 1), min(y1, self.h - 1)
            if x0 <= x1 and y0 <= y1:
                gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
                inside = np.ones(gx.shape, bool)
                k = len(q)
                area = sum(q[i, 0] * q[(i + 1) % k, 1] - q[(i + 1) % k, 0] * q[i, 1] for i in range(k))
                sgn = 1.0 if area > 0 else -1.0
                for i in range(k):
                    a, b = q[i], q[(i + 1) % k]
                    inside &= sgn * ((b[0] - a[0]) * (gy - a[1]) - (b[1] - a[1]) * (gx - a[0])) >= 0
                sub = self.img[y0:y1 + 1, x0:x1 + 1]
                sub[inside] = (1 - alpha) * sub[inside] + alpha * np.asarray(fill, float) * 255
        if edge is not None:
            for i in range(len(corners)):
                self.line(corners[i], corners[(i + 1) % len(corners)], edge, width)

    def save(self, path):
        write_png(path, np.clip(self.img, 0, 255).astype(np.uint8))


def rect_corners(center, length, width, yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    u, v = np.array([c, s]) * length / 2, np.array([-s, c]) * width / 2
    c0 = np.asarray(center[:2], float)
    return np.array([c0 - u - v, c0 + u - v, c0 + u + v, c0 - u + v])


def _save3d(path, img):
    write_png(path, np.clip(img, 0, 255).astype(np.uint8))


def write_stages(trace, scene, out_dir, cfg, formats=(), width=900, height=600):
    out_dir = Path(out_dir)
    sd = out_dir / "stages"
    sd.mkdir(parents=True, exist_ok=True)
    pv = cfg["preview"]
    az, el = pv["azimuth_deg"], pv["elevation_deg"]
    P = trace["leveled"]
    lab_s, lab_w, lab_f = trace["label_surface"], trace["label_walls"], trace["label_final"]
    info = {}

    # 01、02：輸入座標
    X, V = trace["input"], trace["voxel"]
    cam_in = Camera(np.percentile(X, 1, axis=0), np.percentile(X, 99, axis=0), width, height, az, el)
    _save3d(sd / "01_input.png", splat(cam_in, X, height_colors(X[:, 2]), 1))
    _save3d(sd / "02_voxel.png", splat(cam_in, V, height_colors(V[:, 2]), 1))
    info["01_input"] = {"points": int(len(X))}
    info["02_voxel"] = {"points": int(len(V)), "voxel_m": cfg["preprocess"]["voxel"]}

    # 03：沿最長牆方向切一片 0.5 m 厚的剖面，從側面看：地面、天花板是水平線
    floor_el = next(e for e in scene["elements"] if e["kind"] == "floor")
    gy = floor_el["pose"]["yaw"]
    Lc = apply_T(pose_T([0, 0, 0], -gy), P)
    mid = np.median(Lc[:, 1])
    keep = (np.abs(Lc[:, 1] - mid) < 0.25) & (lab_s != "above_ceiling")
    lo, hi = np.percentile(Lc[keep], 0.5, axis=0), np.percentile(Lc[keep], 99.5, axis=0)
    cam_side = Camera(lo, hi, width, int(height * 0.6), -90.0, 0.0)
    col = np.tile(LIGHT, (len(P), 1))
    col[lab_s == ""] = (0.35, 0.35, 0.35)
    col[lab_s == "floor"] = (0.2, 0.6, 0.25)
    col[lab_s == "ceiling"] = CEIL
    col[lab_s == "below_floor"] = (0.95, 0.6, 0.1)
    _save3d(sd / "03_level.png", splat(cam_side, Lc[keep], col[keep], 2))
    info["03_level"] = {"planes": [{"points": p["points"], "height_at_centroid": round(p["height_at_centroid"], 3)}
                                   for p in trace["planes"]],
                        "floor_index": trace["floor_index"], "tilt_deg": round(trace["tilt_deg"], 3),
                        "ceiling_height": None if trace["ceiling_h"] is None else round(trace["ceiling_h"], 3),
                        "labels": {k: int((lab_s == k).sum()) for k in ("floor", "ceiling", "below_floor",
                                                                        "above_ceiling")}}

    walls = [e for e in scene["elements"] if e["kind"] == "wall"]
    plo, phi = P.min(axis=0), P.max(axis=0)

    # 04：牆
    tv = TopView(plo, phi, width)
    free = lab_s == ""
    tv.points(P[free][:, :2], LIGHT)
    tv.points(trace["wall_cells"], (0.45, 0.45, 0.45), 2)
    for c in trace["wall_candidates"]:
        if not c["accepted"]:
            tv.line(c["segment"][0], c["segment"][1], (1.0, 0.6, 0.0), 3)
    for w in walls:
        L, T, _ = w["parts"][0]["size"]
        tv.poly(rect_corners(w["pose"]["xyz"], L, T, w["pose"]["yaw"]), fill=WALL, edge=(0.6, 0.15, 0.1))
    tv.save(sd / "04_walls.png")
    info["04_walls"] = {"tall_cells": int(len(trace["wall_cells"])), "walls": len(walls),
                        "candidates": [{"length": round(c["length"], 2), "top": round(c["top"], 2),
                                        "fill": round(c["fill"], 2), "accepted": c["accepted"],
                                        "reason": c["reason"]} for c in trace["wall_candidates"]]}

    # 05：地面板
    tv = TopView(plo, phi, width)
    fl = lab_s == "floor"
    tv.points(P[fl][:, :2], (0.7, 0.7, 0.7))
    Tg = pose_T([0, 0, 0], floor_el["pose"]["yaw"])
    for p in floor_el["parts"]:
        cx, cy = (Tg[:3, :3] @ np.asarray(p["xyz"]))[:2]
        tv.poly(rect_corners((cx, cy), p["size"][0], p["size"][1], floor_el["pose"]["yaw"]), fill=FLOOR,
                edge=(0.3, 0.3, 0.3), width=1, alpha=0.45)
    for w in walls:
        L, T, _ = w["parts"][0]["size"]
        tv.poly(rect_corners(w["pose"]["xyz"], L, T, w["pose"]["yaw"]), fill=WALL)
    tv.save(sd / "05_floor.png")
    info["05_floor"] = {"plates": len(floor_el["parts"]), "area_m2": floor_el["stats"]["area_m2"]}

    # 06：分群
    cam = Camera(np.percentile(P[~np.isin(lab_f, ("ceiling", "above_ceiling"))], 1, axis=0),
                 np.percentile(P[~np.isin(lab_f, ("ceiling", "above_ceiling"))], 99, axis=0), width, height, az, el)
    show = (lab_w == "") | (lab_w == "floor")              # 牆點不畫，免得擋住室內
    col = np.tile(LIGHT, (len(P), 1))
    for i, c in enumerate(trace["clusters"]):
        col[c["index"]] = PALETTE[i % len(PALETTE)]
    _save3d(sd / "06_clusters.png", splat(cam, P[show], col[show], 2))
    info["06_clusters"] = {"clusters": len(trace["clusters"])}

    # 07：比對目錄
    tv = TopView(plo, phi, width)
    tv.points(P[lab_w == ""][:, :2], LIGHT)
    for w in walls:
        L, T, _ = w["parts"][0]["size"]
        tv.poly(rect_corners(w["pose"]["xyz"], L, T, w["pose"]["yaw"]), fill=(0.8, 0.8, 0.8))
    objs = {e["id"]: e for e in scene["elements"] if e["kind"] == "object"}
    matched = {}
    for c in trace["clusters"]:
        corners = rect_corners(c["center"], c["length"], c["width"], c["yaw"])
        if c["class"]:
            color = class_color({"kind": "object", "class": c["class"]})
            tv.poly(corners, fill=color, edge=(0.15, 0.15, 0.15), width=2)
            matched[c["class"]] = matched.get(c["class"], 0) + 1
        else:
            tv.poly(corners, edge=(0.4, 0.4, 0.4), width=1)
    tv.save(sd / "07_match.png")
    info["07_match"] = {"matched": dict(sorted(matched.items())),
                        "unmatched": sum(1 for c in trace["clusters"] if not c["class"]),
                        "objects": len(objs)}

    # 08：殘餘網格
    res = [e for e in scene["elements"] if e["kind"] == "mesh"]
    if res:
        v, t = read_stl(out_dir / res[0]["parts"][0]["file"])
        tris = v[t]
        img = raster(cam, tris, np.tile(RESID, (len(tris), 1)))
        info["08_residual"] = {"triangles": int(len(t)), "points": res[0]["stats"]["points"]}
    else:
        img = np.full((height, width, 3), 255.0)
        info["08_residual"] = {"triangles": 0}
    _save3d(sd / "08_residual.png", img)

    # 09：完整場景
    tris, cols = scene_triangles(scene, out_dir)
    _save3d(sd / "09_scene.png", raster(cam, tris, cols))
    info["09_scene"] = {"elements": len([e for e in scene["elements"] if e.get("export", True)]),
                        "triangles": int(len(tris))}

    # 10、11：從匯出檔讀回
    from .viewer import load
    for name, fmt, f in (("10_urdf", "urdf", "scene.urdf"), ("11_usd", "usd", "scene.usda")):
        if fmt in formats and (out_dir / f).exists():
            tris, cols = load(out_dir / f)
            if cfg["export"]["frame"] == "input":
                T = np.asarray(scene["frame"]["T_scene_from_input"], float)
                tris = apply_T(T, tris.reshape(-1, 3)).reshape(-1, 3, 3)
            _save3d(sd / f"{name}.png", raster(cam, tris, cols))
            info[name] = {"file": f, "triangles": int(len(tris))}
    (sd / "stages.json").write_text(json.dumps(info, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return sorted(p.name for p in sd.glob("*.png"))


__all__ = ["write_stages", "TopView", "splat"]
