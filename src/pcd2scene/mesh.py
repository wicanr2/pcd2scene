"""殘餘點的體素表面網格與二進位 STL 讀寫。

體素表面：被佔的體素朝向空體素的面就是表面。結果是封閉的階梯狀表面，
位置誤差不超過半個體素，不需要估法向量，也不會因為點稀疏而破洞擴大。

merge=True 時，同一平面上相鄰、同方向的面貪婪合併成矩形，每個矩形兩個三角形。
頂點仍在體素格點上，覆蓋的區域與不合併時完全相同；相鄰矩形的邊可能形成 T 形接點
（一個矩形的角落在另一個矩形的邊上），碰撞與光柵化不受影響。
"""
from __future__ import annotations

import struct

import numpy as np

from .geometry import voxel_keys

# 六個方向：法向量與該面四個角（單位體素內，逆時針朝外）
_FACES = [
    ((1, 0, 0), [(1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)]),
    ((-1, 0, 0), [(0, 0, 0), (0, 0, 1), (0, 1, 1), (0, 1, 0)]),
    ((0, 1, 0), [(0, 1, 0), (0, 1, 1), (1, 1, 1), (1, 1, 0)]),
    ((0, -1, 0), [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]),
    ((0, 0, 1), [(0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)]),
    ((0, 0, -1), [(0, 0, 0), (0, 1, 0), (1, 1, 0), (1, 0, 0)]),
]


def _merge_plane(cells):
    """一個平面上的面 (v, u) 整數座標集合，貪婪分解成矩形 [(v0, u0, h, w)]，順序固定。"""
    avail = set(cells)
    rects = []
    for v0, u0 in sorted(avail):
        if (v0, u0) not in avail:
            continue
        w = 1
        while (v0, u0 + w) in avail:
            w += 1
        h = 1
        while all((v0 + h, u0 + i) in avail for i in range(w)):
            h += 1
        for dv in range(h):
            for du in range(w):
                avail.discard((v0 + dv, u0 + du))
        rects.append((v0, u0, h, w))
    return rects


def _exposed(occ):
    """每個方向朝空體素的被佔體素。回傳 [(normal, base (N,3))]。"""
    occ_set = {tuple(k) for k in occ.tolist()}
    out = []
    for normal, _ in _FACES:
        nb = occ + np.array(normal)
        exposed = np.array([tuple(k) not in occ_set for k in nb.tolist()], dtype=bool)
        out.append((normal, occ[exposed]))
    return out


def _merged_quads(exposed):
    quads = []
    for normal, base in exposed:
        a = int(np.flatnonzero(normal)[0])
        u, v = [x for x in range(3) if x != a]
        plane = base[:, a] + (1 if normal[a] > 0 else 0)
        for c in np.unique(plane).tolist():
            sel = base[plane == c]
            for v0, u0, h, w in _merge_plane(zip(sel[:, v].tolist(), sel[:, u].tolist())):
                q = np.zeros((4, 3), np.int64)
                q[:, a] = c
                q[:, u] = [u0, u0 + w, u0 + w, u0]
                q[:, v] = [v0, v0, v0 + h, v0 + h]
                if np.dot(np.cross(q[1] - q[0], q[2] - q[0]), normal) < 0:
                    q = q[::-1]
                quads.append(q)
    return np.array(quads, np.int64).reshape(-1, 4, 3)


def voxel_surface(pts, size, min_points=1, origin=None, merge=True):
    """回傳 (vertices (V,3), triangles (F,3) int)。頂點共用、順序固定。"""
    if len(pts) == 0:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    if origin is None:
        origin = np.floor(pts.min(axis=0) / size) * size
    keys = voxel_keys(pts, size, origin)
    uniq, cnt = np.unique(keys, axis=0, return_counts=True)
    occ = uniq[cnt >= min_points]
    if len(occ) == 0:
        return np.zeros((0, 3)), np.zeros((0, 3), np.int64)
    exposed = _exposed(occ)
    if merge:
        q = _merged_quads(exposed)
    else:
        q = np.concatenate([base[:, None, :] + np.array(corners)[None, :, :]
                            for (_, base), (_, corners) in zip(exposed, _FACES)], axis=0)
    flat = q.reshape(-1, 3)
    verts_i, inv = np.unique(flat, axis=0, return_inverse=True)
    inv = inv.reshape(-1, 4)
    tris = np.concatenate([inv[:, [0, 1, 2]], inv[:, [0, 2, 3]]], axis=0)
    verts = verts_i * size + origin
    return verts.astype(np.float64), tris.astype(np.int64)


def write_stl(path, verts, tris, name=b"pcd2scene"):
    v = np.asarray(verts, np.float64)
    t = np.asarray(tris, np.int64)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    n = np.cross(b - a, c - a)
    ln = np.linalg.norm(n, axis=1)
    n[ln > 0] /= ln[ln > 0, None]
    rec = np.zeros(len(t), dtype=[("n", "<f4", 3), ("a", "<f4", 3), ("b", "<f4", 3), ("c", "<f4", 3), ("attr", "<u2")])
    rec["n"], rec["a"], rec["b"], rec["c"] = n, a, b, c
    with open(path, "wb") as f:
        f.write(name.ljust(80, b" ")[:80])
        f.write(struct.pack("<I", len(t)))
        f.write(rec.tobytes())


def read_stl(path):
    """二進位 STL：回傳去重後的 (vertices, triangles)。"""
    with open(path, "rb") as f:
        head = f.read(80)
        (n,) = struct.unpack("<I", f.read(4))
        rec = np.fromfile(f, dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("attr", "<u2")], count=n)
    if len(rec) != n:
        if head.lstrip().lower().startswith(b"solid"):
            raise ValueError("ASCII STL not supported; convert to binary STL")
        raise ValueError("STL truncated")
    flat = rec["v"].reshape(-1, 3).astype(np.float64)
    verts, inv = np.unique(flat, axis=0, return_inverse=True)
    return verts, inv.reshape(-1, 3).astype(np.int64)
