import math

import numpy as np

from pcd2scene.geometry import (R_from_rpy, grid_rects, min_area_rect, rot_between, rpy_from_R, sparse_components,
                                wrap_half_pi)


def test_rot_between_maps_vector():
    rng = np.random.default_rng(0)
    for _ in range(20):
        a, b = rng.normal(size=3), rng.normal(size=3)
        R = rot_between(a, b)
        np.testing.assert_allclose(R @ (a / np.linalg.norm(a)), b / np.linalg.norm(b), atol=1e-9)
        np.testing.assert_allclose(R @ R.T, np.eye(3), atol=1e-9)


def test_rpy_round_trip():
    for rpy in [(0.1, -0.2, 0.3), (0, 0, math.pi * 0.9), (-0.4, 0.5, -2.0)]:
        np.testing.assert_allclose(rpy_from_R(R_from_rpy(*rpy)), rpy, atol=1e-9)


def test_min_area_rect_rotated():
    rng = np.random.default_rng(0)
    L, W, yaw = 4.0, 1.0, math.radians(30)
    local = np.column_stack([rng.uniform(-L / 2, L / 2, 2000), rng.uniform(-W / 2, W / 2, 2000)])
    R = np.array([[math.cos(yaw), -math.sin(yaw)], [math.sin(yaw), math.cos(yaw)]])
    c, l, w, a = min_area_rect(local @ R.T + [5, -2])
    assert abs(l - L) < 0.02 and abs(w - W) < 0.02
    assert abs(wrap_half_pi(a - yaw)) < math.radians(0.5)
    np.testing.assert_allclose(c, [5, -2], atol=0.02)


def test_grid_rects_cover_mask():
    m = np.zeros((5, 6), bool)
    m[0:2, 0:6] = True
    m[2:5, 1:3] = True
    out = np.zeros_like(m)
    for iy, ix, h, w in grid_rects(m):
        assert not out[iy:iy + h, ix:ix + w].any()
        out[iy:iy + h, ix:ix + w] = True
    assert (out == m).all()


def test_sparse_components():
    keys = np.array([[0, 0, 0], [1, 1, 1], [5, 5, 5], [6, 5, 5], [9, 0, 0]])
    lab = sparse_components(keys)
    assert lab[0] == lab[1] and lab[2] == lab[3]
    assert len({lab[0], lab[2], lab[4]}) == 3
