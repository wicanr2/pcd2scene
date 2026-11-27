"""目錄物件的參數化模型：把類別參數展開成物件座標下的零件。

物件座標：原點在佔地矩形中心、落在物件底部；x 沿長邊，y 沿短邊，z 向上。
零件格式：{"type": "box", "size": [sx, sy, sz], "xyz": [x, y, z]}（盒心）或
{"type": "mesh", "file": ..., "scale": [...], "xyz": [...]}。零件只有平移，沒有旋轉。
"""
from __future__ import annotations

import numpy as np


def box(size, xyz):
    return {"type": "box", "size": [float(s) for s in size], "xyz": [float(v) for v in xyz]}


def total_length(entry, n):
    L = entry["size"][0]
    pitch = entry.get("array", {}).get("pitch", L)
    return (n - 1) * pitch + L


def auto_levels(local_pts, height, frames=(), frame_clear=0.15, bin_size=0.02, min_gap=0.25):
    """層板高度：格間內（離框架 frame_clear 以外）的點的 z 直方圖峰值。

    橫樑與層板跨整個格間，在同一高度集中很多點；框架的橫撐只在框架位置，所以先排除框架附近的點。
    回傳值是峰值所在連續高密度區段的上緣，也就是橫樑頂面。
    """
    if len(local_pts) == 0:
        return []
    if len(frames):
        d = np.min(np.abs(local_pts[:, 0:1] - np.asarray(frames)[None, :]), axis=1)
        local_pts = local_pts[d > frame_clear]
        if len(local_pts) == 0:
            return []
    z = local_pts[:, 2]
    bins = np.arange(0.0, height + bin_size, bin_size)
    h, e = np.histogram(z, bins=bins)
    if h.sum() == 0:
        return []
    thr = max(3.0, 3.0 * float(h.mean()))      # 以整個高度的平均密度為基準：橫樑只佔少數高度格
    peaks = [i for i in range(1, len(h) - 1) if h[i] >= thr and h[i] >= h[i - 1] and h[i] >= h[i + 1]]
    levels = []
    for i in sorted(peaks, key=lambda i: -h[i]):
        j = i
        while j + 1 < len(h) and h[j + 1] >= thr:
            j += 1
        top = float(e[j + 1])
        if top < 0.1 or top > height - 0.05:
            continue
        if all(abs(top - l) >= min_gap for l in levels):
            levels.append(top)
    return sorted(levels)


def build_parts(entry, n, local_pts=None):
    """回傳 (零件, 參數紀錄)。"""
    m = entry.get("model", {"type": "box"})
    t = m.get("type", "box")
    L, W, H = entry["size"]
    T = total_length(entry, n)
    info = {"model": t}
    if t == "box":
        return [box((T, W, H), (0, 0, H / 2))], info
    if t == "table":
        tt = m.get("top_thickness", 0.04)
        leg = m.get("leg", 0.05)
        inset = m.get("leg_inset", 0.05)
        parts = [box((T, W, tt), (0, 0, H - tt / 2))]
        for sx in (-1, 1):
            for sy in (-1, 1):
                parts.append(box((leg, leg, H - tt), (sx * (T / 2 - inset - leg / 2), sy * (W / 2 - inset - leg / 2),
                                                      (H - tt) / 2)))
        return parts, info
    if t == "rack":
        pitch = entry.get("array", {}).get("pitch", L)
        ua, ub = m.get("upright", [0.09, 0.07])
        bh, bd = m.get("beam", [0.1, 0.05])
        x0 = -T / 2
        ends = sorted({round(x0 + k * pitch, 6) for k in range(n)} | {round(x0 + k * pitch + L, 6) for k in range(n)})
        levels = m.get("levels", [])
        if levels == "auto":
            levels = auto_levels(local_pts if local_pts is not None else np.zeros((0, 3)), H, ends)
        info["levels"] = [round(float(l), 3) for l in levels]
        parts = []
        brace = m.get("brace", [0.04, 0.6])   # 框架橫撐：[截面邊長, 間距]；前後立柱靠它連成一個框架
        for xe in ends:                       # 立柱：每個框架兩支（前、後）
            xc = min(max(xe, -T / 2 + ua / 2), T / 2 - ua / 2)
            for sy in (-1, 1):
                parts.append(box((ua, ub, H), (xc, sy * (W / 2 - ub / 2), H / 2)))
            if brace:
                bs, bp = brace
                for zb in np.arange(bp / 2, H - bs, bp):
                    parts.append(box((bs, W - 2 * ub, bs), (xc, 0.0, float(zb))))
        for k in range(n):                    # 橫樑：每格每層前後各一支
            xs = x0 + k * pitch
            cx = xs + L / 2
            span = L - ua
            for lv in levels:
                for sy in (-1, 1):
                    parts.append(box((span, bd, bh), (cx, sy * (W / 2 - bd / 2), lv - bh / 2)))
                if m.get("deck", False):
                    parts.append(box((span, W - 2 * bd, 0.02), (cx, 0, lv - 0.01)))
        return parts, info
    if t == "mesh":
        return [{"type": "mesh", "file": m["file"], "scale": [float(s) for s in m.get("scale", [1, 1, 1])],
                 "xyz": [0.0, 0.0, 0.0]}], info
    raise ValueError(f"unknown model type: {t}")
