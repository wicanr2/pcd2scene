"""俯視總覽 SVG：點的佔據格、地面、牆、物件（標類別）。給人與 agent 目視檢查還原結果。"""
from __future__ import annotations

from xml.sax.saxutils import escape

import numpy as np

from .export import class_color
from .geometry import apply_T, pose_T


def _hex(c):
    return "#" + "".join(f"{int(round(v * 255)):02x}" for v in c)


def write_overview(scene, P, label, path, px_per_m=60, cell=0.1):
    keep = ~np.isin(label, ("below_floor", "above_ceiling", "ceiling", "floor"))
    pts = P[keep]
    allxy = P[:, :2]
    lo = allxy.min(axis=0) - 0.5
    hi = allxy.max(axis=0) + 0.5
    W, H = (hi - lo) * px_per_m

    def tx(x, y):
        return (x - lo[0]) * px_per_m, (hi[1] - y) * px_per_m

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="0 0 {W:.1f} {H:.1f}" font-family="sans-serif">',
           f'<rect width="{W:.1f}" height="{H:.1f}" fill="#ffffff"/>']
    for el in scene["elements"]:
        if el["kind"] in ("ceiling", "mesh"):
            continue
        T = pose_T(el["pose"]["xyz"], el["pose"]["yaw"])
        col = _hex(class_color(el))
        for p in el["parts"]:
            if p["type"] != "box":
                continue
            sx, sy, _ = p["size"]
            c = np.array([[-sx / 2, -sy / 2, 0], [sx / 2, -sy / 2, 0], [sx / 2, sy / 2, 0], [-sx / 2, sy / 2, 0]])
            q = apply_T(T, c + np.asarray(p["xyz"]))
            pts_s = " ".join("%.1f,%.1f" % tx(x, y) for x, y, _ in q)
            if el["kind"] == "floor":
                out.append(f'<polygon points="{pts_s}" fill="#eeeeee" stroke="none"/>')
            else:
                out.append(f'<polygon points="{pts_s}" fill="{col}" fill-opacity="0.55" stroke="#333" '
                           f'stroke-width="0.6"/>')
    if len(pts):
        ij = np.unique(np.floor((pts[:, :2] - lo) / cell).astype(int), axis=0)
        s = cell * px_per_m
        cells = "".join(f"M{i * s:.1f},{H - (j + 1) * s:.1f}h{s:.1f}v{s:.1f}h{-s:.1f}z" for i, j in ij)
        out.append(f'<path d="{cells}" fill="#000" fill-opacity="0.35"/>')
    for el in scene["elements"]:
        if el["kind"] == "object":
            x, y = tx(*el["pose"]["xyz"][:2])
            text = el["class"] + (f" x{el['units']}" if el.get("units", 1) > 1 else "")
            out.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="11" text-anchor="middle" fill="#000">'
                       f'{escape(text)}</text>')
    x0, y0 = 10, H - 12
    out.append(f'<line x1="{x0}" y1="{y0}" x2="{x0 + px_per_m}" y2="{y0}" stroke="#000" stroke-width="2"/>'
               f'<text x="{x0}" y="{y0 - 4}" font-size="11">1 m</text>')
    out.append("</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
