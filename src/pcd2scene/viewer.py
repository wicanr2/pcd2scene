"""從匯出的 URDF、SDF 或 USD 檔讀回幾何，畫成 PNG。

只讀檔案本身，不經過 scene.json：畫出來的就是模擬器會載入的內容（盒子、網格、位姿、顏色）。
URDF 依 joint 鏈組合變換；SDF 依 model 與 link 的 pose；USD 用 pxr 計算每個 prim 的世界變換。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

from .geometry import R_from_rpy, make_T
from .mesh import read_stl
from .render import _BOX_CORNERS, _BOX_TRIS, Camera, raster, write_png

GRAY = (0.6, 0.6, 0.6)


def _nums(s, n, default=0.0):
    v = [float(x) for x in (s or "").split()]
    return v + [default] * (n - len(v)) if len(v) < n else v[:n]


def _xyz_rpy_T(xyz, rpy):
    return make_T(R_from_rpy(*rpy), xyz)


def _box(T, size, color):
    v = _BOX_CORNERS * np.asarray(size, float)
    v = v @ T[:3, :3].T + T[:3, 3]
    return v[_BOX_TRIS], np.repeat(np.asarray(color, float)[None], len(_BOX_TRIS), axis=0)


def _mesh(T, path, scale, color):
    v, t = read_stl(path)
    v = (v * np.asarray(scale, float)) @ T[:3, :3].T + T[:3, 3]
    return v[t], np.repeat(np.asarray(color, float)[None], len(t), axis=0)


def _resolve(base, uri):
    for pre in ("file://", "model://"):
        if uri.startswith(pre):
            uri = uri[len(pre):]
    if uri.startswith("package://"):
        uri = uri.split("/", 3)[3]          # package://<名稱>/meshes/x.stl → meshes/x.stl（相對輸出目錄）
    p = Path(uri)
    return p if p.is_absolute() else Path(base) / p


def load_urdf(path):
    path = Path(path)
    root = ET.parse(path).getroot()
    mats = {}
    for m in root.findall("material"):
        c = m.find("color")
        if c is not None:
            mats[m.get("name")] = _nums(c.get("rgba"), 4)[:3]
    parent_of = {}
    for j in root.findall("joint"):
        o = j.find("origin")
        T = _xyz_rpy_T(_nums(o.get("xyz") if o is not None else "", 3),
                       _nums(o.get("rpy") if o is not None else "", 3))
        parent_of[j.find("child").get("link")] = (j.find("parent").get("link"), T)
    cache = {}

    def world(link):
        if link not in cache:
            if link in parent_of:
                p, T = parent_of[link]
                cache[link] = world(p) @ T
            else:
                cache[link] = np.eye(4)
        return cache[link]

    tris, cols = [], []
    for link in root.findall("link"):
        Tl = world(link.get("name"))
        for vis in link.findall("visual"):
            o = vis.find("origin")
            Tv = Tl @ _xyz_rpy_T(_nums(o.get("xyz") if o is not None else "", 3),
                                 _nums(o.get("rpy") if o is not None else "", 3))
            m = vis.find("material")
            color = GRAY
            if m is not None:
                c = m.find("color")
                color = _nums(c.get("rgba"), 4)[:3] if c is not None else mats.get(m.get("name"), GRAY)
            g = vis.find("geometry")
            if g.find("box") is not None:
                t, c = _box(Tv, _nums(g.find("box").get("size"), 3), color)
            elif g.find("mesh") is not None:
                me = g.find("mesh")
                t, c = _mesh(Tv, _resolve(path.parent, me.get("filename")), _nums(me.get("scale"), 3, 1.0), color)
            else:
                continue
            tris.append(t)
            cols.append(c)
    return tris, cols


def _pose(el):
    p = _nums(el.findtext("pose"), 6)
    return _xyz_rpy_T(p[:3], p[3:])


def load_sdf(path):
    path = Path(path)
    root = ET.parse(path).getroot()
    tris, cols = [], []
    for model in root.iter("model"):
        Tm = _pose(model)
        for link in model.findall("link"):
            Tl = Tm @ _pose(link)
            for vis in link.findall("visual"):
                Tv = Tl @ _pose(vis)
                color = _nums(vis.findtext("material/diffuse"), 4)[:3] if vis.find("material/diffuse") is not None \
                    else GRAY
                g = vis.find("geometry")
                if g.find("box") is not None:
                    t, c = _box(Tv, _nums(g.findtext("box/size"), 3), color)
                elif g.find("mesh") is not None:
                    t, c = _mesh(Tv, _resolve(path.parent, g.findtext("mesh/uri")),
                                 _nums(g.findtext("mesh/scale"), 3, 1.0), color)
                else:
                    continue
                tris.append(t)
                cols.append(c)
    return tris, cols


def load_usd(path):
    from pxr import Usd, UsdGeom

    stage = Usd.Stage.Open(str(path))
    cache = UsdGeom.XformCache()
    tris, cols = [], []
    for prim in stage.Traverse():
        if not (prim.IsA(UsdGeom.Cube) or prim.IsA(UsdGeom.Mesh)):
            continue
        M = np.array(cache.GetLocalToWorldTransform(prim), float).T     # USD 存轉置（列向量）
        g = UsdGeom.Gprim(prim)
        dc = g.GetDisplayColorAttr().Get()
        color = tuple(dc[0]) if dc else GRAY
        if prim.IsA(UsdGeom.Cube):
            s = UsdGeom.Cube(prim).GetSizeAttr().Get()
            t, c = _box(M, [s, s, s], color)
        else:
            m = UsdGeom.Mesh(prim)
            v = np.asarray(m.GetPointsAttr().Get(), float)
            counts = np.asarray(m.GetFaceVertexCountsAttr().Get())
            idx = np.asarray(m.GetFaceVertexIndicesAttr().Get())
            if not np.all(counts == 3):
                raise ValueError(f"{prim.GetPath()}: only triangle meshes are supported")
            v = v @ M[:3, :3].T + M[:3, 3]
            t = v[idx.reshape(-1, 3)]
            c = np.repeat(np.asarray(color, float)[None], len(t), axis=0)
        tris.append(t)
        cols.append(c)
    return tris, cols


def load(path):
    suf = Path(path).suffix.lower()
    if suf == ".urdf":
        tris, cols = load_urdf(path)
    elif suf in (".sdf", ".world"):
        tris, cols = load_sdf(path)
    elif suf in (".usd", ".usda", ".usdc"):
        tris, cols = load_usd(path)
    else:
        raise ValueError(f"unsupported file: {path}")
    if not tris:
        raise ValueError(f"no geometry in {path}")
    return np.concatenate(tris), np.concatenate(cols)


def camera_for(points, width, height, az_deg, el_deg):
    lo, hi = np.percentile(points, 1, axis=0), np.percentile(points, 99, axis=0)
    return Camera(lo, hi, width, height, az_deg, el_deg)


def render_file(path, out_png, width=900, height=640, az_deg=-55.0, el_deg=38.0, cam=None):
    tris, cols = load(path)
    cam = cam or camera_for(tris.reshape(-1, 3), width, height, az_deg, el_deg)
    img = raster(cam, tris, cols)
    write_png(out_png, np.clip(img, 0, 255).astype(np.uint8))
    return {"file": str(Path(path).name), "triangles": int(len(tris))}


def bounds(path):
    tris, _ = load(path)
    P = tris.reshape(-1, 3)
    return P.min(axis=0), P.max(axis=0)


__all__ = ["load", "load_urdf", "load_sdf", "load_usd", "render_file", "camera_for", "bounds"]
