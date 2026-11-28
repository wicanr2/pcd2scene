"""設定：內建預設值，使用者 YAML 逐層覆蓋。各欄位的意義見 docs/config.md。"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import yaml

DEFAULTS = {
    "seed": 0,
    "input": {
        "transform": None,          # 4x4，讀檔後先套用（例如把 y-up 轉成 z-up）
        "crop": None,               # [xmin, ymin, zmin, xmax, ymax, zmax]，輸入座標
    },
    "preprocess": {"voxel": 0.03, "min_points": 1},
    "floor": {
        "max_tilt_deg": 10.0,       # 地面法向量與輸入 +z 的最大夾角
        "inlier": 0.03,
        "band": 0.05,               # 離地面這個距離內的點算地面
        "min_fraction": 0.02,       # 水平面至少要有這個比例的點才算候選
        "max_planes": 4,
        "ransac_iters": 400,
        "mode": "level",            # level：轉正並把地面移到 z=0；shift：只做 z 平移（不轉正）
        "cell": 0.2,                # 地面範圍格點
        "fill_holes": 2,            # 地面格點閉運算次數
        "thickness": 0.1,
    },
    "ceiling": {
        "detect": True,
        "min_height": 1.8,          # 比地面高這麼多的水平面才可能是天花板
        "band": 0.08,
        "export": False,            # 預設不輸出天花板（模擬車頂視角與渲染常要拿掉）
        "thickness": 0.1,
    },
    "walls": {
        "cell": 0.05,
        "zbin": 0.1,
        "min_height": 1.8,          # 牆頂至少要到這個高度
        "min_length": 1.5,
        "min_fill": 0.33,           # 牆面 (沿線 x 高度) 格子被點佔到的比例
        "inlier": 0.05,
        "max_gap": 0.4,
        "thickness": 0.1,           # 只看到一面時的牆厚
        "margin": 0.06,             # 牆盒外這個距離內的點算牆
        "ceiling_contact": 0.4,     # 有天花板時，牆頂與天花板的距離上限；null 表示不檢查
        "max_walls": 64,
        "ransac_iters": 300,
    },
    "objects": {
        "cluster_voxel": 0.08,
        "min_points": 30,
        "min_height": 0.08,
        "floor_contact": 0.15,      # 底部離地這個距離內視為落地
        "margin": 0.06,
        "unknown": "mesh",          # 沒對上目錄的叢集：mesh（併入殘餘網格）、box（外接盒）、drop
        "catalog": [],
    },
    "mesh": {
        "voxel": 0.05,
        "min_points": 1,
        "merge_faces": True,        # 同平面相鄰的體素面合併成矩形，三角形數大幅減少，形狀不變
        "outlier_voxel": 0.1,       # 零星點判定：以這個體素做 26 連通
        "outlier_min_points": 10,   # 連通後少於這個點數（體素後）的小叢集不建模；0 表示關閉
        "collision": True,
    },
    "validate": {"tolerances": [0.05, 0.1], "sample_step": 0.03},
    "preview": {"azimuth_deg": -55.0, "elevation_deg": 38.0, "width": 900, "height": 640},
    "export": {"formats": ["urdf", "sdf", "usd"], "frame": "scene", "mesh_uri": "relative"},
}


def _merge(base, over, path=""):
    for k, v in over.items():
        if k not in base:
            raise KeyError(f"unknown config key: {path}{k}")
        if isinstance(base[k], dict):
            if v is None:                   # 只有區段名、欄位全被註解掉：沿用預設
                continue
            if not isinstance(v, dict):
                raise TypeError(f"config key {path}{k} must be a mapping, got {type(v).__name__}")
            _merge(base[k], v, f"{path}{k}.")
        else:
            base[k] = v


def load_config(path=None, overrides=None):
    cfg = copy.deepcopy(DEFAULTS)
    if path:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        _merge(cfg, data)
    if overrides:
        _merge(cfg, overrides)
    for e in cfg["objects"]["catalog"]:
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", str(e.get("class", ""))):
            raise ValueError(f"catalog class must be an identifier: {e.get('class')!r}")
        if len(e.get("size", [])) != 3:
            raise ValueError(f"catalog {e['class']}: size must be [length, width, height]")
        if e["size"][0] < e["size"][1]:
            raise ValueError(f"catalog {e['class']}: size[0] (length) must be >= size[1] (width)")
    return cfg


def config_sha256(cfg):
    return hashlib.sha256(json.dumps(cfg, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
