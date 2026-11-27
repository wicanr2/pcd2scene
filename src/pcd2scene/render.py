"""軟體光柵化的 3D 預覽：同一個相機下，左邊畫輸入點雲（依高度上色），右邊畫還原場景（平面著色）。

只用 numpy，不需要 GPU 或模擬器；用來在 CI 與 README 裡目視確認還原結果。
"""
from __future__ import annotations

import math
import struct
import zlib

import numpy as np

from .export import class_color, exported
from .geometry import apply_T, pose_T
from .mesh import read_stl

_BOX_TRIS = np.array([[0, 1, 2], [0, 2, 3], [4, 6, 5], [4, 7, 6], [0, 4, 5], [0, 5, 1],
                      [1, 5, 6], [1, 6, 2], [2, 6, 7], [2, 7, 3], [3, 7, 4], [3, 4, 0]])
_BOX_CORNERS = np.array([[-1, -1, -1], [1, -1, -1], [1, 1, -1], [-1, 1, -1],
                         [-1, -1, 1], [1, -1, 1], [1, 1, 1], [-1, 1, 1]]) * 0.5


def write_png(path, img):
    h, w = img.shape[:2]
    raw = b"".join(b"\0" + img[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def scene_triangles(scene, out_dir):
    tris, cols = [], []
    for el in exported(scene):
        T = pose_T(el["pose"]["xyz"], el["pose"]["yaw"])
        c = np.asarray(class_color(el))
        for p in el["parts"]:
            if p["type"] == "box":
                v = _BOX_CORNERS * np.asarray(p["size"]) + np.asarray(p["xyz"])
                t = _BOX_TRIS
            else:
                v, t = read_stl(out_dir / p["file"])
                v = v * np.asarray(p["scale"]) + np.asarray(p["xyz"])
            tris.append(apply_T(T, v)[t])
            cols.append(np.repeat(c[None], len(t), axis=0))
    return np.concatenate(tris), np.concatenate(cols)


class Camera:
    def __init__(self, lo, hi, width, height, az_deg=-55.0, el_deg=38.0):
        self.w, self.h = width, height
        center = (lo + hi) / 2
        diag = float(np.linalg.norm(hi - lo))
        az, el = math.radians(az_deg), math.radians(el_deg)
        fwd = -np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
        self.eye = center - fwd * diag * 1.25
        right = np.cross(fwd, [0, 0, 1.0])
        right /= np.linalg.norm(right)
        up = np.cross(right, fwd)
        self.R = np.stack([right, up, fwd])
        self.f = 0.5 * width / math.tan(math.radians(25))

    def project(self, P):
        q = (P - self.eye) @ self.R.T
        z = np.maximum(q[:, 2], 1e-3)
        return np.column_stack([self.w / 2 + self.f * q[:, 0] / z, self.h / 2 - self.f * q[:, 1] / z, z])


def raster(cam, tris, cols, light=(0.35, -0.5, 0.8)):
    img = np.full((cam.h, cam.w, 3), 255.0)
    zbuf = np.full((cam.h, cam.w), np.inf)
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    L = np.asarray(light) / np.linalg.norm(light)
    shade = 0.35 + 0.65 * np.abs(n @ L)
    S = cam.project(tris.reshape(-1, 3)).reshape(-1, 3, 3)
    rgb = cols * shade[:, None] * 255
    order = np.argsort(-S[:, :, 2].mean(axis=1))
    for k in order:
        s = S[k]
        x0, y0 = np.floor(s[:, :2].min(axis=0)).astype(int)
        x1, y1 = np.ceil(s[:, :2].max(axis=0)).astype(int)
        x0, y0, x1, y1 = max(x0, 0), max(y0, 0), min(x1, cam.w - 1), min(y1, cam.h - 1)
        if x0 > x1 or y0 > y1:
            continue
        if (x1 - x0) * (y1 - y0) <= 2:
            cx, cy = int(s[:, 0].mean()), int(s[:, 1].mean())
            if 0 <= cx < cam.w and 0 <= cy < cam.h and s[:, 2].mean() < zbuf[cy, cx]:
                zbuf[cy, cx] = s[:, 2].mean()
                img[cy, cx] = rgb[k]
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(y0, y1 + 1) + 0.5)
        (ax, ay, az), (bx, by, bz), (qx, qy, qz) = s
        den = (by - qy) * (ax - qx) + (qx - bx) * (ay - qy)
        if abs(den) < 1e-12:
            continue
        w0 = ((by - qy) * (gx - qx) + (qx - bx) * (gy - qy)) / den
        w1 = ((qy - ay) * (gx - qx) + (ax - qx) * (gy - qy)) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= 0) & (w1 >= 0) & (w2 >= 0)
        if not inside.any():
            continue
        depth = w0 * az + w1 * bz + w2 * qz
        sub = zbuf[y0:y1 + 1, x0:x1 + 1]
        win = inside & (depth < sub)
        sub[win] = depth[win]
        img[y0:y1 + 1, x0:x1 + 1][win] = rgb[k]
    return img


def splat(cam, P, size=2):
    img = np.full((cam.h, cam.w, 3), 255.0)
    zbuf = np.full((cam.h, cam.w), np.inf)
    s = cam.project(P)
    z = P[:, 2]
    t = (z - np.percentile(z, 1)) / max(1e-6, np.percentile(z, 99) - np.percentile(z, 1))
    t = np.clip(t, 0, 1)
    col = np.column_stack([0.15 + 0.8 * t, 0.35 + 0.4 * (1 - abs(2 * t - 1)), 0.9 - 0.75 * t]) * 255
    order = np.argsort(-s[:, 2])
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


def render_preview(scene, P, label, out_dir, path, width=900, height=640, az_deg=-55.0, el_deg=38.0):
    keep = ~np.isin(label, ("ceiling", "above_ceiling", "below_floor"))
    pts = P[keep]
    tris, cols = scene_triangles(scene, out_dir)
    allp = np.concatenate([pts, tris.reshape(-1, 3)])
    lo, hi = np.percentile(allp, 1, axis=0), np.percentile(allp, 99, axis=0)
    cam = Camera(lo, hi, width, height, az_deg, el_deg)
    left = splat(cam, pts)
    right = raster(cam, tris, cols)
    gap = np.full((height, 8, 3), 255.0)
    img = np.concatenate([left, gap, right], axis=1)
    write_png(path, np.clip(img, 0, 255).astype(np.uint8))
