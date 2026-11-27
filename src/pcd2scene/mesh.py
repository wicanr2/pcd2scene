"""殘餘點的體素表面網格與二進位 STL 讀寫。

體素表面：被佔的體素朝向空體素的面各輸出兩個三角形。結果是封閉的階梯狀表面，
位置誤差不超過半個體素，不需要估法向量，也不會因為點稀疏而破洞擴大。
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


def voxel_surface(pts, size, min_points=1, origin=None):
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
    occ_set = {tuple(k) for k in occ.tolist()}
    quads = []
    for normal, corners in _FACES:
        nb = occ + np.array(normal)
        exposed = np.array([tuple(k) not in occ_set for k in nb.tolist()])
        base = occ[exposed]
        quads.append(base[:, None, :] + np.array(corners)[None, :, :])
    q = np.concatenate(quads, axis=0)                 # (Q, 4, 3) 整數角點
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
