"""點雲讀檔：PCD（ascii、binary、binary_compressed）與 PLY 頂點（ascii、binary_little_endian）。

只取 x、y、z 與 intensity（有的話）。非有限值的點丟掉。
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_PCD_TYPES = {
    ("F", 4): "<f4", ("F", 8): "<f8",
    ("I", 1): "<i1", ("I", 2): "<i2", ("I", 4): "<i4", ("I", 8): "<i8",
    ("U", 1): "<u1", ("U", 2): "<u2", ("U", 4): "<u4", ("U", 8): "<u8",
}


@dataclass
class Cloud:
    xyz: np.ndarray            # (N, 3) float64
    intensity: np.ndarray | None
    source: str
    sha256: str
    raw_points: int             # 檔內點數（含非有限值）


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def lzf_decompress(data: bytes, out_len: int) -> bytes:
    """LZF 解壓（PCL binary_compressed 用的格式，liblzf 的 lzf_d.c）。"""
    out = bytearray(out_len)
    ip = op = 0
    n = len(data)
    while ip < n:
        ctrl = data[ip]
        ip += 1
        if ctrl < 32:                       # 字面值：ctrl + 1 個位元組
            ln = ctrl + 1
            if op + ln > out_len or ip + ln > n:
                raise ValueError("LZF literal run past buffer end")
            out[op:op + ln] = data[ip:ip + ln]
            ip += ln
            op += ln
        else:                               # 回參：長度 (ctrl >> 5) + 2，距離 ((ctrl & 31) << 8) + next + 1
            ln = ctrl >> 5
            if ln == 7:
                ln += data[ip]
                ip += 1
            ref = op - ((ctrl & 0x1F) << 8) - data[ip] - 1
            ip += 1
            ln += 2
            if ref < 0 or op + ln > out_len:
                raise ValueError("LZF back reference outside buffer")
            if ref + ln <= op:
                out[op:op + ln] = out[ref:ref + ln]
            else:                           # 重疊時逐位元組複製
                for k in range(ln):
                    out[op + k] = out[ref + k]
            op += ln
    if op != out_len:
        raise ValueError(f"LZF size mismatch: {op} != {out_len}")
    return bytes(out)


def _parse_pcd_header(f):
    hdr = {}
    while True:
        line = f.readline()
        if not line:
            raise ValueError("PCD: no DATA line")
        text = line.decode("ascii", "replace").strip()
        if not text or text.startswith("#"):
            continue
        key, *vals = text.split()
        hdr[key.upper()] = vals
        if key.upper() == "DATA":
            return hdr


def read_pcd(path: Path):
    with open(path, "rb") as f:
        hdr = _parse_pcd_header(f)
        fields = hdr["FIELDS"]
        sizes = [int(s) for s in hdr["SIZE"]]
        types = hdr["TYPE"]
        counts = [int(c) for c in hdr.get("COUNT", ["1"] * len(fields))]
        npts = int(hdr["POINTS"][0]) if "POINTS" in hdr else int(hdr["WIDTH"][0]) * int(hdr["HEIGHT"][0])
        mode = hdr["DATA"][0].lower()
        dtype = np.dtype([(f"{name}_{i}" if name == "_" else name, _PCD_TYPES[(t, s)], (c,) if c > 1 else ())
                          for i, (name, s, t, c) in enumerate(zip(fields, sizes, types, counts))])
        if mode == "ascii":
            rows = np.loadtxt(f, dtype=np.float64, ndmin=2)
            cols, k = {}, 0
            for name, c in zip(fields, counts):
                cols[name] = rows[:, k] if c == 1 else rows[:, k:k + c]
                k += c
        elif mode == "binary":
            arr = np.fromfile(f, dtype=dtype, count=npts)
            if len(arr) != npts:
                raise ValueError("PCD binary: fewer points than header")
            cols = {name: arr[name] for name in dtype.names}
        elif mode == "binary_compressed":
            csize, usize = np.frombuffer(f.read(8), dtype="<u4")
            raw = lzf_decompress(f.read(int(csize)), int(usize))
            cols, off = {}, 0                # 解壓後是逐欄連續（每欄 npts 筆）
            for name in dtype.names:
                sub = dtype[name]
                nbytes = sub.itemsize * npts
                cols[name] = np.frombuffer(raw, dtype=sub.base, count=npts * max(1, int(np.prod(sub.shape))),
                                           offset=off).reshape((npts,) + sub.shape)
                off += nbytes
        else:
            raise ValueError(f"PCD DATA {mode} not supported")
    for k in ("x", "y", "z"):
        if k not in cols:
            raise ValueError(f"PCD: field {k} missing")
    xyz = np.stack([np.asarray(cols[k], dtype=np.float64) for k in ("x", "y", "z")], axis=1)
    inten = None
    for k in ("intensity", "reflectivity", "i"):
        if k in cols:
            inten = np.asarray(cols[k], dtype=np.float64).reshape(-1)
            break
    return xyz, inten


_PLY_TYPES = {"char": "i1", "uchar": "u1", "short": "i2", "ushort": "u2", "int": "i4", "uint": "u4",
              "float": "f4", "double": "f8", "int8": "i1", "uint8": "u1", "int16": "i2", "uint16": "u2",
              "int32": "i4", "uint32": "u4", "float32": "f4", "float64": "f8"}


def read_ply(path: Path):
    with open(path, "rb") as f:
        if f.readline().strip() != b"ply":
            raise ValueError("not a PLY file")
        fmt, elements, cur = None, [], None
        while True:
            parts = f.readline().decode("ascii").split()
            if not parts:
                continue
            if parts[0] == "format":
                fmt = parts[1]
            elif parts[0] == "element":
                cur = [parts[1], int(parts[2]), []]
                elements.append(cur)
            elif parts[0] == "property":
                if parts[1] == "list":
                    cur[2].append((parts[4], "list"))
                else:
                    cur[2].append((parts[2], _PLY_TYPES[parts[1]]))
            elif parts[0] == "end_header":
                break
        if not elements or elements[0][0] != "vertex":
            raise ValueError("PLY: first element must be vertex")
        _, nv, props = elements[0]
        if any(t == "list" for _, t in props):
            raise ValueError("PLY: list property in vertex")
        if fmt == "ascii":
            rows = np.loadtxt(f, dtype=np.float64, max_rows=nv, ndmin=2)
            cols = {name: rows[:, i] for i, (name, _) in enumerate(props)}
        elif fmt == "binary_little_endian":
            arr = np.fromfile(f, dtype=np.dtype([(n, "<" + t) for n, t in props]), count=nv)
            cols = {n: arr[n] for n, _ in props}
        else:
            raise ValueError(f"PLY format {fmt} not supported")
    xyz = np.stack([np.asarray(cols[k], dtype=np.float64) for k in ("x", "y", "z")], axis=1)
    inten = next((np.asarray(cols[k], dtype=np.float64) for k in ("intensity", "reflectivity") if k in cols), None)
    return xyz, inten


def read_cloud(path) -> Cloud:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pcd":
        xyz, inten = read_pcd(path)
    elif suffix == ".ply":
        xyz, inten = read_ply(path)
    else:
        raise ValueError(f"unsupported point cloud suffix: {suffix}")
    raw = len(xyz)
    keep = np.isfinite(xyz).all(axis=1)
    if inten is not None:
        inten = inten[keep]
    return Cloud(xyz=xyz[keep], intensity=inten, source=path.name, sha256=sha256_file(path), raw_points=raw)


def write_pcd(path, xyz, intensity=None):
    """binary PCD（float32）。合成資料與測試用。"""
    xyz = np.asarray(xyz, dtype="<f4")
    fields = "x y z" + (" intensity" if intensity is not None else "")
    n = len(xyz)
    k = 4 if intensity is not None else 3
    head = (f"# .PCD v0.7 - Point Cloud Data file format\nVERSION 0.7\nFIELDS {fields}\n"
            f"SIZE {' '.join(['4'] * k)}\nTYPE {' '.join(['F'] * k)}\nCOUNT {' '.join(['1'] * k)}\n"
            f"WIDTH {n}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {n}\nDATA binary\n")
    body = xyz if intensity is None else np.concatenate([xyz, np.asarray(intensity, "<f4")[:, None]], axis=1)
    with open(path, "wb") as f:
        f.write(head.encode("ascii"))
        f.write(np.ascontiguousarray(body, dtype="<f4").tobytes())
