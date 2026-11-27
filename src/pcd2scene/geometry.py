"""幾何工具：平面擬合、RANSAC、剛體變換、最小面積矩形、格點矩形分解、稀疏連通元件。"""
from __future__ import annotations

import math

import numpy as np
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import ConvexHull


# ---------------------------------------------------------------- 變換

def make_T(R=None, t=None):
    T = np.eye(4)
    if R is not None:
        T[:3, :3] = R
    if t is not None:
        T[:3, 3] = t
    return T


def apply_T(T, pts):
    return pts @ T[:3, :3].T + T[:3, 3]


def inv_T(T):
    R, t = T[:3, :3], T[:3, 3]
    return make_T(R.T, -R.T @ t)


def rot_z(yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]])


def pose_T(xyz=(0, 0, 0), yaw=0.0):
    return make_T(rot_z(yaw), np.asarray(xyz, float))


def rpy_from_R(R):
    """URDF/SDF 的固定軸 roll-pitch-yaw：R = Rz(yaw) Ry(pitch) Rx(roll)。"""
    pitch = math.asin(max(-1.0, min(1.0, -R[2, 0])))
    if abs(R[2, 0]) < 1 - 1e-9:
        roll = math.atan2(R[2, 1], R[2, 2])
        yaw = math.atan2(R[1, 0], R[0, 0])
    else:                                   # 萬向鎖：把 roll 設 0
        roll = 0.0
        yaw = math.atan2(-R[0, 1], R[1, 1])
    return roll, pitch, yaw


def R_from_rpy(roll, pitch, yaw):
    cr, sr, cp, sp = math.cos(roll), math.sin(roll), math.cos(pitch), math.sin(pitch)
    Rx = np.array([[1, 0, 0], [0, cr, -sr], [0, sr, cr]])
    Ry = np.array([[cp, 0, sp], [0, 1, 0], [-sp, 0, cp]])
    return rot_z(yaw) @ Ry @ Rx


def rot_between(a, b):
    """把單位向量 a 轉到 b 的最小旋轉（Rodrigues）。"""
    a = a / np.linalg.norm(a)
    b = b / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(a @ b)
    s = np.linalg.norm(v)
    if s < 1e-12:
        if c > 0:
            return np.eye(3)
        axis = np.cross(a, [1.0, 0, 0])
        if np.linalg.norm(axis) < 1e-6:
            axis = np.cross(a, [0, 1.0, 0])
        axis /= np.linalg.norm(axis)
        K = np.array([[0, -axis[2], axis[1]], [axis[2], 0, -axis[0]], [-axis[1], axis[0], 0]])
        return np.eye(3) + 2 * K @ K
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * ((1 - c) / s ** 2)


def wrap_half_pi(a):
    """角度折到 (-pi/2, pi/2]：矩形長軸方向沒有正負之分。"""
    a = (a + math.pi / 2) % math.pi - math.pi / 2
    if a <= -math.pi / 2 + 1e-12:
        a += math.pi
    return a


# ---------------------------------------------------------------- 平面

def fit_plane(pts):
    """最小平方平面 n·p + d = 0，n 朝 +z。"""
    c = pts.mean(axis=0)
    _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
    n = vt[2]
    if n[2] < 0:
        n = -n
    return n, float(-n @ c)


def ransac_plane(pts, rng, iters, inlier, max_tilt_rad, sample_cap=60000):
    """法向量與 +z 夾角不超過 max_tilt 的平面，回傳 (n, d, inlier_mask) 或 None。"""
    if len(pts) < 3:
        return None
    P = pts if len(pts) <= sample_cap else pts[rng.choice(len(pts), sample_cap, replace=False)]
    tri = P[rng.integers(0, len(P), size=(iters, 3))]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    norm = np.linalg.norm(n, axis=1)
    ok = norm > 1e-9
    n[ok] /= norm[ok, None]
    n[n[:, 2] < 0] *= -1
    ok &= n[:, 2] >= math.cos(max_tilt_rad)
    best, best_cnt = None, 0
    for k in np.flatnonzero(ok):
        d = -n[k] @ tri[k, 0]
        cnt = int(np.count_nonzero(np.abs(P @ n[k] + d) < inlier))
        if cnt > best_cnt:
            best, best_cnt = (n[k], d), cnt
    if best is None:
        return None
    nn, dd = best
    for _ in range(3):                      # 以全部點的內點重新擬合
        mask = np.abs(pts @ nn + dd) < inlier
        if mask.sum() < 3:
            return None
        nn, dd = fit_plane(pts[mask])
        if nn[2] < math.cos(max_tilt_rad):
            return None
    mask = np.abs(pts @ nn + dd) < inlier
    return nn, dd, mask


# ---------------------------------------------------------------- 2D

def min_area_rect(xy):
    """最小面積外接矩形：(center(2), length, width, yaw)，length >= width，yaw 是長邊方向。"""
    xy = np.asarray(xy, float)
    if len(xy) < 3:
        c = xy.mean(axis=0)
        return c, 0.0, 0.0, 0.0
    try:
        hull = xy[ConvexHull(xy).vertices]
    except Exception:                       # 共線
        hull = xy
    edges = np.diff(np.vstack([hull, hull[:1]]), axis=0)
    angles = np.unique(np.round(np.mod(np.arctan2(edges[:, 1], edges[:, 0]), math.pi / 2), 9))
    best = None
    for a in angles:
        R = np.array([[math.cos(a), math.sin(a)], [-math.sin(a), math.cos(a)]])
        q = hull @ R.T
        lo, hi = q.min(axis=0), q.max(axis=0)
        area = float(np.prod(hi - lo))
        if best is None or area < best[0] - 1e-12:
            best = (area, a, lo, hi)
    _, a, lo, hi = best
    size = hi - lo
    mid = (lo + hi) / 2
    c = np.array([mid[0] * math.cos(a) - mid[1] * math.sin(a), mid[0] * math.sin(a) + mid[1] * math.cos(a)])
    if size[0] >= size[1]:
        return c, float(size[0]), float(size[1]), wrap_half_pi(a)
    return c, float(size[1]), float(size[0]), wrap_half_pi(a + math.pi / 2)


def grid_rects(mask):
    """把 2D 布林格點貪婪分解成矩形，回傳 [(iy, ix, h, w)]。"""
    mask = mask.copy()
    rects = []
    H, W = mask.shape
    for iy in range(H):
        ix = 0
        while ix < W:
            if not mask[iy, ix]:
                ix += 1
                continue
            w = 1
            while ix + w < W and mask[iy, ix + w]:
                w += 1
            h = 1
            while iy + h < H and mask[iy + h, ix:ix + w].all():
                h += 1
            mask[iy:iy + h, ix:ix + w] = False
            rects.append((iy, ix, h, w))
            ix += w
    return rects


# ---------------------------------------------------------------- 體素

def voxel_keys(pts, size, origin):
    return np.floor((pts - origin) / size).astype(np.int64)


def voxel_downsample(pts, size, min_points=1):
    """每個體素取點的平均；回傳 (點, 每體素點數)。順序依體素索引排序，結果可重現。"""
    if len(pts) == 0:
        return pts, np.zeros(0, int)
    origin = pts.min(axis=0)
    keys = voxel_keys(pts, size, origin)
    uniq, inv, cnt = np.unique(keys, axis=0, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    sums = np.zeros((len(uniq), 3))
    np.add.at(sums, inv, pts)
    mean = sums / cnt[:, None]
    keep = cnt >= min_points
    return mean[keep], cnt[keep]


def sparse_components(keys):
    """整數體素座標 (V, 3) 的 26 連通元件標籤。"""
    V = len(keys)
    if V == 0:
        return np.zeros(0, int)
    lo = keys.min(axis=0) - 1
    k = keys - lo
    dims = k.max(axis=0) + 2
    code = (k[:, 0] * dims[1] + k[:, 1]) * dims[2] + k[:, 2]
    order = np.argsort(code)
    sorted_code = code[order]
    rows, cols = [], []
    offsets = [(dx, dy, dz) for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
               if (dx, dy, dz) > (0, 0, 0)]
    for dx, dy, dz in offsets:
        nb = ((k[:, 0] + dx) * dims[1] + (k[:, 1] + dy)) * dims[2] + (k[:, 2] + dz)
        pos = np.searchsorted(sorted_code, nb)
        pos[pos >= V] = V - 1
        hit = sorted_code[pos] == nb
        rows.append(np.flatnonzero(hit))
        cols.append(order[pos[hit]])
    r = np.concatenate(rows)
    c = np.concatenate(cols)
    g = coo_matrix((np.ones(len(r), np.int8), (r, c)), shape=(V, V))
    _, labels = connected_components(g, directed=False)
    return labels
