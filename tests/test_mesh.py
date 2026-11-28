import numpy as np

from pcd2scene.mesh import voxel_surface


def _blob(seed=0, n=20000):
    """不規則的體素團：幾個方塊加上散點，有凹處與分離的部分。"""
    rng = np.random.default_rng(seed)
    pts = [rng.uniform([0, 0, 0], [1.0, 0.6, 0.4], size=(n, 3)),
           rng.uniform([0.4, 0.2, 0.4], [0.8, 0.5, 0.9], size=(n // 2, 3)),
           rng.uniform([2.0, 2.0, 0.0], [2.1, 2.1, 0.1], size=(5, 3))]
    return np.concatenate(pts)


def _area_by_normal(v, t):
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    n = np.cross(b - a, c - a) / 2                     # 面積向量，朝外
    out = {}
    for axis in range(3):
        for s in (1, -1):
            m = np.sign(n[:, axis]) == s
            out[(axis, s)] = float(np.abs(n[m, axis]).sum())
    return out


def _volume(v, t):
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    return float(np.einsum("ij,ij->i", a, np.cross(b, c)).sum() / 6)


def test_merge_keeps_shape_and_cuts_triangles():
    pts = _blob()
    size = 0.05
    v0, t0 = voxel_surface(pts, size, merge=False)
    v1, t1 = voxel_surface(pts, size, merge=True)
    occ = len(np.unique(np.floor((pts - np.floor(pts.min(axis=0) / size) * size) / size), axis=0))
    assert abs(_volume(v0, t0) - occ * size ** 3) < 1e-9
    assert abs(_volume(v1, t1) - occ * size ** 3) < 1e-9          # 朝外、封閉，體積不變
    a0, a1 = _area_by_normal(v0, t0), _area_by_normal(v1, t1)
    for k in a0:
        assert abs(a0[k] - a1[k]) < 1e-9                         # 每個方向的面積不變
    assert len(t1) < len(t0) / 3


def test_merge_is_deterministic():
    pts = _blob(1)
    v1, t1 = voxel_surface(pts, 0.05)
    v2, t2 = voxel_surface(pts[::-1].copy(), 0.05)
    np.testing.assert_array_equal(v1, v2)
    np.testing.assert_array_equal(t1, t2)
