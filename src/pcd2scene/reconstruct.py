"""點雲 → 場景中介表示（scene.json 的內容）。

步驟（docs/pipeline.md）：
1. 預處理：輸入變換、裁切、體素平均。
2. 水平面：依序 RANSAC 找出接近水平的平面，最低的是地面，夠高的最高者是天花板。
3. 場景座標：把地面轉正、移到 z = 0（floor.mode=level）。
4. 牆：高覆蓋格點上的 2D 直線 RANSAC，以牆面填滿率排除貨架、家具。
5. 物件：其餘點做 26 連通分群，佔地取最小面積矩形，依目錄的尺寸比對類別與重複單元數。
6. 殘餘：沒被以上解釋的點轉成體素表面網格。
"""
from __future__ import annotations

import math

import numpy as np

from . import __version__
from .config import config_sha256
from .geometry import (apply_T, grid_rects, inv_T, make_T, min_area_rect, pose_T, ransac_plane, rot_between,
                       sparse_components, voxel_downsample, voxel_keys, wrap_half_pi)
from .mesh import voxel_surface
from .models import build_parts, total_length


def r6(x):
    if isinstance(x, (list, tuple, np.ndarray)):
        return [r6(v) for v in x]
    v = round(float(x), 6)
    return 0.0 if v == 0 else v


def r9(x):
    """變換矩陣與平面係數：小數 9 位，1 km 外的位置誤差仍在 1e-6 m 以下。"""
    if isinstance(x, (list, tuple, np.ndarray)):
        return [r9(v) for v in x]
    v = round(float(x), 9)
    return 0.0 if v == 0 else v


def _plane_height(n, d, xy):
    return float(-(n[0] * xy[0] + n[1] * xy[1] + d) / n[2])


def _rects_from_points(xy, cell, closing, fill):
    from scipy import ndimage
    lo = np.floor(xy.min(axis=0) / cell) * cell
    ij = np.floor((xy - lo) / cell).astype(int)
    mask = np.zeros(tuple(ij.max(axis=0)[::-1] + 1), bool)
    mask[ij[:, 1], ij[:, 0]] = True
    if closing > 0:
        mask = np.pad(mask, closing)
        mask = ndimage.binary_closing(mask, iterations=closing)[closing:-closing, closing:-closing]
    if fill:
        mask = ndimage.binary_fill_holes(mask)
    out = []
    for iy, ix, h, w in grid_rects(mask):
        out.append((lo[0] + (ix + w / 2) * cell, lo[1] + (iy + h / 2) * cell, w * cell, h * cell))
    return out, int(mask.sum())


def _longest_run(t, gap):
    order = np.argsort(t)
    ts = t[order]
    cuts = np.flatnonzero(np.diff(ts) > gap) + 1
    starts = np.concatenate([[0], cuts])
    ends = np.concatenate([cuts, [len(ts)]])
    k = int(np.argmax(ends - starts))
    return ends[k] - starts[k], ts[starts[k]], ts[ends[k] - 1], order[starts[k]:ends[k]]


def _in_box(P, T_elem, size, center_z, margin):
    """點在零件盒（只有 yaw）內：size=(sx, sy, sz)，盒心在元素座標 (0, 0, center_z)。"""
    q = apply_T(inv_T(T_elem), P)
    return ((np.abs(q[:, 0]) <= size[0] / 2 + margin) & (np.abs(q[:, 1]) <= size[1] / 2 + margin)
            & (np.abs(q[:, 2] - center_z) <= size[2] / 2 + margin))


def detect_walls(P, cw, ceiling_h, rng, centroid_xy, log, trace=None):
    cell, zbin = cw["cell"], cw["zbin"]
    if len(P) == 0:
        return []
    ij = np.floor(P[:, :2] / cell).astype(np.int64)
    k = np.floor(P[:, 2] / zbin).astype(np.int64)
    ijk = np.unique(np.column_stack([ij, k]), axis=0)
    cells, vc = np.unique(ijk[:, :2], axis=0, return_counts=True)
    tall = vc * zbin >= 0.5 * cw["min_height"] * cw["min_fill"]
    C = (cells[tall] + 0.5) * cell
    if trace is not None:
        trace["wall_cells"] = C.copy()
        trace["wall_candidates"] = []
    alive = np.ones(len(C), bool)
    walls, fails = [], 0
    min_cells = max(3, int(cw["min_length"] / cell * 0.5))
    while len(walls) < cw["max_walls"] and fails < 12:
        idx = np.flatnonzero(alive)
        if len(idx) < min_cells:
            break
        Ca = C[idx]
        best = None
        best_cnt = 0
        for a, b in rng.integers(0, len(Ca), size=(cw["ransac_iters"], 2)):
            d = Ca[b] - Ca[a]
            ln = math.hypot(d[0], d[1])
            if ln < 0.3:
                continue
            u = d / ln
            nrm = np.array([-u[1], u[0]])
            inl = np.flatnonzero(np.abs((Ca - Ca[a]) @ nrm) < cw["inlier"])
            if len(inl) <= best_cnt:
                continue
            cnt, _, _, mem = _longest_run((Ca[inl] - Ca[a]) @ u, cw["max_gap"])
            if cnt > best_cnt:
                best_cnt, best = cnt, inl[mem]
        if best is None or best_cnt < min_cells:
            break
        M = Ca[best]
        c = M.mean(axis=0)
        _, _, vt = np.linalg.svd(M - c, full_matrices=False)
        u = vt[0]
        nrm = np.array([-u[1], u[0]])
        inl = np.flatnonzero(np.abs((Ca - c) @ nrm) < cw["inlier"])
        if len(inl) == 0:
            alive[idx[best]] = False
            fails += 1
            continue
        _, t0, t1, mem = _longest_run((Ca[inl] - c) @ u, cw["max_gap"])
        alive[idx[inl[mem]]] = False
        alive[idx[best]] = False
        length = t1 - t0 + cell
        tp = (P[:, :2] - c) @ u
        sp = (P[:, :2] - c) @ nrm
        band = (np.abs(sp) < cw["inlier"]) & (tp >= t0 - cell) & (tp <= t1 + cell)
        if band.sum() < 10 or length < cw["min_length"]:
            fails += 1
            continue
        zb = P[band, 2]
        top = float(np.percentile(zb, 98))
        nt = max(1, int(math.ceil(length / 0.1)))
        nz = max(1, int(math.ceil(top / 0.1)))
        ti = np.clip(((tp[band] - t0) / 0.1).astype(int), 0, nt - 1)
        zi = np.clip((zb / 0.1).astype(int), 0, nz - 1)
        fill = len(np.unique(ti * nz + zi)) / float(nt * nz)
        z_up = int(nz * 0.5)                 # 上半部：家具多半只擋住牆的下半部
        up = zi >= z_up
        fill_upper = len(np.unique(ti[up] * nz + zi[up])) / float(nt * (nz - z_up)) if nz > z_up else 0.0
        contact_ok = True
        if ceiling_h is not None and cw["ceiling_contact"] is not None:
            contact_ok = top >= ceiling_h - cw["ceiling_contact"]
        seg = (c + u * t0, c + u * t1)
        if top < cw["min_height"] or fill < cw["min_fill"] or not contact_ok:
            if trace is not None:
                why = [k for k, bad in (("height", top < cw["min_height"]), ("fill", fill < cw["min_fill"]),
                                        ("ceiling_contact", not contact_ok)) if bad]
                trace["wall_candidates"].append({"segment": seg, "length": length, "top": top, "fill": fill,
                                                 "accepted": False, "reason": why})
            log(f"  wall candidate rejected: length {length:.2f} top {top:.2f} fill {fill:.2f} upper {fill_upper:.2f}"
                f" contact {contact_ok}")
            fails += 1
            continue
        if ceiling_h is not None and contact_ok and cw["ceiling_contact"] is not None:
            top = ceiling_h
        s = sp[band]
        s5, s95 = np.percentile(s, [5, 95])
        if s95 - s5 >= cw["thickness"]:
            lo, hi = s5, s95
        else:
            side = float((centroid_xy - c) @ nrm)
            outer = -1.0 if side > 0 else 1.0
            face = float(np.median(s))
            lo, hi = sorted((face, face + outer * cw["thickness"]))
        mid = (lo + hi) / 2
        center = c + nrm * mid + u * (t0 + t1) / 2
        if trace is not None:
            trace["wall_candidates"].append({"segment": seg, "length": length, "top": top, "fill": fill,
                                             "accepted": True, "reason": []})
        yaw = wrap_half_pi(math.atan2(u[1], u[0]))
        walls.append({"center": center, "yaw": yaw, "length": float(length), "thickness": float(hi - lo),
                      "height": float(top), "fill": float(fill)})
        fails = 0
    return walls


def classify(dims, on_floor, catalog):
    Lo, Wo, Ho = dims
    best = None
    for e in catalog:
        if e.get("on_floor", True) and not on_floor:
            continue
        L, W, H = e["size"]
        tl, tw, th = e.get("tolerance", [0.15 * L, 0.15 * W, 0.15 * H])
        if abs(Wo - W) > tw or abs(Ho - H) > th:
            continue
        if "array" in e:
            pitch = e["array"].get("pitch", L)
            n = int(max(1, round((Lo - L) / pitch) + 1))
            n = min(n, int(e["array"].get("max_units", 64)))
        else:
            n = 1
        err = abs(Lo - total_length(e, n))
        if err > tl:
            continue
        score = err / tl + abs(Wo - W) / tw + abs(Ho - H) / th
        if best is None or score < best[0]:
            best = (score, e, n)
    return best


def reconstruct(cloud, cfg, log=print, trace=None):
    """trace 給 dict 時，記下各步驟的中間結果（供 stages 繪圖）；不影響輸出與亂數。"""
    rng = np.random.default_rng(cfg["seed"])
    stats = {"points_raw": cloud.raw_points, "points_finite": int(len(cloud.xyz))}
    pts = cloud.xyz
    T_in = np.eye(4)
    if cfg["input"]["transform"] is not None:
        T_in = np.asarray(cfg["input"]["transform"], float).reshape(4, 4)
        pts = apply_T(T_in, pts)
    if cfg["input"]["crop"] is not None:
        b = np.asarray(cfg["input"]["crop"], float)
        pts = pts[np.all((pts >= b[:3]) & (pts <= b[3:]), axis=1)]
    stats["points_cropped"] = int(len(pts))
    P0, _ = voxel_downsample(pts, cfg["preprocess"]["voxel"], cfg["preprocess"]["min_points"])
    if trace is not None:
        trace["input"] = pts
        trace["voxel"] = P0
    stats["points_voxel"] = int(len(P0))
    log(f"points: raw {cloud.raw_points}, finite {len(cloud.xyz)}, voxel {len(P0)}")

    # ---- 水平面
    cf = cfg["floor"]
    rest = P0
    planes = []
    for _ in range(cf["max_planes"]):
        r = ransac_plane(rest, rng, cf["ransac_iters"], cf["inlier"], math.radians(cf["max_tilt_deg"]))
        if r is None:
            break
        n, d, mask = r
        if mask.sum() < cf["min_fraction"] * len(P0):
            break
        planes.append((n, d, int(mask.sum())))
        rest = rest[~mask]
    if not planes:
        raise RuntimeError("no horizontal plane found; check floor.max_tilt_deg or input.transform")
    cxy = P0[:, :2].mean(axis=0)
    heights = [_plane_height(n, d, cxy) for n, d, _ in planes]
    fi = int(np.argmin(heights))
    n_f, d_f, cnt_f = planes[fi]
    if cf["mode"] == "level":
        R = rot_between(n_f, np.array([0.0, 0.0, 1.0]))
        T_lvl = make_T(R, [0.0, 0.0, d_f])
    elif cf["mode"] == "shift":
        T_lvl = make_T(None, [0.0, 0.0, -heights[fi]])
    else:
        raise ValueError("floor.mode must be level or shift")
    T = T_lvl @ T_in                                   # 場景 ← 原始輸入
    P = apply_T(T_lvl, P0)
    tilt = math.degrees(math.acos(min(1.0, abs(n_f[2]))))
    log(f"floor: {cnt_f} points, tilt {tilt:.3f} deg, height at centroid {heights[fi]:.3f}")
    if trace is not None:
        trace.update(planes=[{"normal": n.tolist(), "d": float(d), "points": c, "height_at_centroid": h}
                             for (n, d, c), h in zip(planes, heights)],
                     floor_index=fi, tilt_deg=tilt, T_level=T_lvl, leveled=P)

    ceiling_h = None
    if cfg["ceiling"]["detect"]:
        cands = []
        for i, (n, d, c) in enumerate(planes):
            if i == fi:
                continue
            q = apply_T(T_lvl, np.array([[cxy[0], cxy[1], heights[i]]]))[0]
            if q[2] >= cfg["ceiling"]["min_height"]:
                cands.append(float(q[2]))
        if cands:
            ceiling_h = max(cands)
            log(f"ceiling: z {ceiling_h:.3f}")

    z = P[:, 2]
    label = np.full(len(P), "", dtype=object)
    label[np.abs(z) <= cf["band"]] = "floor"
    label[z < -cf["band"]] = "below_floor"
    if ceiling_h is not None:
        label[np.abs(z - ceiling_h) <= cfg["ceiling"]["band"]] = "ceiling"
        label[z > ceiling_h + cfg["ceiling"]["band"]] = "above_ceiling"

    elements = []
    # ---- 牆
    cw = cfg["walls"]
    free = label == ""
    if trace is not None:
        trace["ceiling_h"] = ceiling_h
        trace["label_surface"] = label.copy()
    walls = detect_walls(P[free], cw, ceiling_h, rng, P[free][:, :2].mean(axis=0) if free.any() else cxy, log,
                         trace)
    for i, w in enumerate(walls):
        Te = pose_T([w["center"][0], w["center"][1], 0.0], w["yaw"])
        size = [w["length"], w["thickness"], w["height"]]
        inside = _in_box(P, Te, size, w["height"] / 2, cw["margin"]) & (label == "")
        label[inside] = f"wall_{i:03d}"
        elements.append({"id": f"wall_{i:03d}", "kind": "wall", "class": "wall",
                         "pose": {"xyz": r6([w["center"][0], w["center"][1], 0.0]), "yaw": r6(w["yaw"])},
                         "parts": [{"type": "box", "size": r6(size), "xyz": r6([0, 0, w["height"] / 2])}],
                         "stats": {"points": int(inside.sum()), "fill": r6(w["fill"])}})
    log(f"walls: {len(walls)}")

    # ---- 地面與天花板：格點對齊最長那面牆，邊界才不會因為斜放而變成鋸齒
    grid_yaw = max(walls, key=lambda w: w["length"])["yaw"] if walls else 0.0
    Rg = pose_T([0, 0, 0], grid_yaw)
    local = apply_T(inv_T(Rg), P)
    surf = []
    fl = label == "floor"
    rects, ncell = _rects_from_points(local[fl, :2], cf["cell"], cf["fill_holes"], True)
    th = cf["thickness"]
    surf.append({"id": "floor", "kind": "floor", "class": "floor", "pose": {"xyz": [0, 0, 0], "yaw": r6(grid_yaw)},
                 "parts": [{"type": "box", "size": r6([w, h, th]), "xyz": r6([x, y, -th / 2])}
                           for x, y, w, h in rects],
                 "stats": {"points": int(fl.sum()), "area_m2": r6(ncell * cf["cell"] ** 2), "tilt_deg": r6(tilt)}})
    if ceiling_h is not None:
        cl = label == "ceiling"
        crects, ccell = _rects_from_points(local[cl, :2], cf["cell"], cf["fill_holes"], True)
        cth = cfg["ceiling"]["thickness"]
        surf.append({"id": "ceiling", "kind": "ceiling", "class": "ceiling",
                     "pose": {"xyz": [0, 0, 0], "yaw": r6(grid_yaw)}, "export": bool(cfg["ceiling"]["export"]),
                     "parts": [{"type": "box", "size": r6([w, h, cth]), "xyz": r6([x, y, ceiling_h + cth / 2])}
                               for x, y, w, h in crects],
                     "stats": {"points": int(cl.sum()), "height": r6(ceiling_h),
                               "area_m2": r6(ccell * cf["cell"] ** 2)}})
    elements[:0] = surf

    # ---- 物件
    co = cfg["objects"]
    cand = np.flatnonzero(label == "")
    if trace is not None:
        trace["label_walls"] = label.copy()
        trace["clusters"] = []
    counts = {}
    n_unknown = 0
    if len(cand):
        keys = voxel_keys(P[cand], co["cluster_voxel"], P[cand].min(axis=0))
        uk, inv = np.unique(keys, axis=0, return_inverse=True)
        lab_v = sparse_components(uk)
        lab = lab_v[inv.reshape(-1)]
        # 依叢集最小點索引排序，順序與 RANSAC 無關、可重現
        comp_ids = sorted(np.unique(lab), key=lambda c: int(np.flatnonzero(lab == c)[0]))
        for c in comp_ids:
            idx = cand[lab == c]
            if len(idx) < co["min_points"]:
                continue
            Q = P[idx]
            zmin = float(Q[:, 2].min())
            zmax = float(np.percentile(Q[:, 2], 99))
            on_floor = zmin <= co["floor_contact"]
            bottom = 0.0 if on_floor else zmin
            height = zmax - bottom
            if height < co["min_height"]:
                continue
            center, Lo, Wo, yaw = min_area_rect(Q[:, :2])
            match = classify((Lo, Wo, height), on_floor, co["catalog"])
            if trace is not None:
                trace["clusters"].append({"index": idx, "center": center, "length": Lo, "width": Wo, "yaw": yaw,
                                          "height": height, "on_floor": on_floor,
                                          "class": match[1]["class"] if match else None,
                                          "units": match[2] if match else None})
            Te = pose_T([center[0], center[1], bottom], yaw)
            if match is not None:
                _, entry, nunit = match
                cls = entry["class"]
                local = apply_T(inv_T(Te), Q)
                parts, info = build_parts(entry, nunit, local)
                L, W, H = entry["size"]
                size_box = [total_length(entry, nunit), W, H]
                k = counts.get(cls, 0)
                counts[cls] = k + 1
                eid = f"{cls}_{k:03d}"
            else:
                log(f"  unmatched cluster at ({center[0]:.2f}, {center[1]:.2f}): {Lo:.2f} x {Wo:.2f} x {height:.2f}"
                    f" m, {len(idx)} points, on_floor {on_floor}")
            if match is not None:
                pass
            elif co["unknown"] == "box":
                cls, nunit, info = "unknown", 1, {"model": "box"}
                size_box = [Lo, Wo, height]
                parts = [{"type": "box", "size": r6(size_box), "xyz": r6([0, 0, height / 2])}]
                eid = f"unknown_{n_unknown:03d}"
                n_unknown += 1
            else:
                if co["unknown"] == "drop":
                    label[idx] = "dropped"
                continue
            inside = _in_box(P, Te, size_box, size_box[2] / 2, co["margin"]) & (label == "")
            label[inside] = eid
            label[idx] = eid
            elements.append({"id": eid, "kind": "object", "class": cls,
                             "pose": {"xyz": r6([center[0], center[1], bottom]), "yaw": r6(yaw)},
                             "units": int(nunit),
                             "parts": [dict(p, size=r6(p["size"]), xyz=r6(p["xyz"])) if p["type"] == "box"
                                       else dict(p, xyz=r6(p["xyz"])) for p in parts],
                             "observed": {"length": r6(Lo), "width": r6(Wo), "height": r6(height),
                                          "points": int(len(idx))},
                             "model": info})
    log("objects: " + (", ".join(f"{k} {v}" for k, v in sorted(counts.items())) or "none")
        + (f", unknown boxes {n_unknown}" if n_unknown else ""))

    # ---- 殘餘網格
    cm = cfg["mesh"]
    res = label == ""
    n_out = 0
    if cm["outlier_min_points"] > 0 and res.any():
        # 零星點：連通後點數太少的小叢集（掃描雜訊、反光、遠處稀疏點），轉成網格只會是散落的小方塊
        idx = np.flatnonzero(res)
        keys = voxel_keys(P[idx], cm["outlier_voxel"], P[idx].min(axis=0))
        uk, inv = np.unique(keys, axis=0, return_inverse=True)
        lab_v = sparse_components(uk)[inv.reshape(-1)]
        small = np.bincount(lab_v)[lab_v] < cm["outlier_min_points"]
        label[idx[small]] = "outlier"
        res[idx[small]] = False
        n_out = int(small.sum())
    label[res] = "residual"
    verts, tris = voxel_surface(P[res], cm["voxel"], cm["min_points"], merge=cm["merge_faces"])
    meshes = {}
    if len(tris):
        meshes["residual"] = (verts, tris)
        elements.append({"id": "residual", "kind": "mesh", "class": "residual",
                         "pose": {"xyz": [0, 0, 0], "yaw": 0.0},
                         "parts": [{"type": "mesh", "file": "meshes/residual.stl", "xyz": [0, 0, 0],
                                    "scale": [1, 1, 1]}],
                         "collision": bool(cm["collision"]),
                         "stats": {"points": int(res.sum()), "triangles": int(len(tris)),
                                   "outlier_points": n_out}})
    log(f"residual: {int(res.sum())} points -> {len(tris)} triangles"
        + (f", outliers removed {n_out}" if n_out else ""))
    if trace is not None:
        trace["label_final"] = label.copy()

    groups = {}
    fixed = {"floor", "ceiling", "below_floor", "above_ceiling", "dropped", "outlier", "residual"}
    for v in label:
        key = v if v in fixed else ("wall" if v.startswith("wall_") else "object")
        groups[key] = groups.get(key, 0) + 1
    stats["labels"] = dict(sorted(groups.items()))
    scene = {
        "format": "pcd2scene/scene",
        "version": "1.0",
        "units": "m",
        "up": "+z",
        "tool": {"name": "pcd2scene", "version": __version__},
        "source": {"file": cloud.source, "sha256": cloud.sha256, **stats},
        "config_sha256": config_sha256(cfg),
        "frame": {
            "description": "scene frame: floor plane at z=0, +z up; T_scene_from_input maps input points to scene; floor_plane (n, d) is in the input frame after input.transform",
            "T_scene_from_input": [r9(row) for row in T.tolist()],
            "floor_plane": r9(list(n_f) + [d_f]),
            "mode": cf["mode"],
        },
        "elements": elements,
    }
    return scene, meshes, P, label
