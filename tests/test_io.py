import struct

import numpy as np
import pytest

from pcd2scene.io_pcd import lzf_decompress, read_cloud, write_pcd


def lzf_literal_only(data: bytes) -> bytes:
    """最簡單的 LZF 編碼：全部是字面值區段（每段最多 32 位元組）。"""
    out = bytearray()
    for i in range(0, len(data), 32):
        chunk = data[i:i + 32]
        out.append(len(chunk) - 1)
        out += chunk
    return bytes(out)


def test_lzf_back_reference():
    # "abcabcabc"：字面值 "abc"，再回參 6 個位元組、距離 3（重疊複製）
    comp = bytes([2]) + b"abc" + bytes([(4 << 5) | 0, 2])
    assert lzf_decompress(comp, 9) == b"abcabcabc"


def test_lzf_long_back_reference():
    comp = bytes([0]) + b"x" + bytes([(7 << 5) | 0, 3, 0])   # 長度 7 + 3 + 2 = 12
    assert lzf_decompress(comp, 13) == b"x" * 13


def test_lzf_rejects_bad_reference():
    with pytest.raises(ValueError):
        lzf_decompress(bytes([(1 << 5) | 0, 5]), 3)


def _header(n, mode, fields="x y z intensity"):
    k = len(fields.split())
    return (f"VERSION 0.7\nFIELDS {fields}\nSIZE {' '.join(['4'] * k)}\nTYPE {' '.join(['F'] * k)}\n"
            f"COUNT {' '.join(['1'] * k)}\nWIDTH {n}\nHEIGHT 1\nVIEWPOINT 0 0 0 1 0 0 0\nPOINTS {n}\nDATA {mode}\n").encode()


def test_pcd_three_encodings_agree(tmp_path):
    rng = np.random.default_rng(1)
    xyz = rng.normal(size=(50, 3)).astype("<f4")
    inten = rng.random(50).astype("<f4")
    xyz[3] = np.nan
    write_pcd(tmp_path / "b.pcd", xyz, inten)
    rows = "\n".join(" ".join(repr(float(v)) for v in (*p, i)) for p, i in zip(xyz, inten))
    (tmp_path / "a.pcd").write_bytes(_header(50, "ascii") + rows.encode() + b"\n")
    soa = b"".join(np.ascontiguousarray(c, "<f4").tobytes() for c in (xyz[:, 0], xyz[:, 1], xyz[:, 2], inten))
    comp = lzf_literal_only(soa)
    (tmp_path / "c.pcd").write_bytes(_header(50, "binary_compressed") + struct.pack("<II", len(comp), len(soa)) + comp)
    clouds = [read_cloud(tmp_path / f"{m}.pcd") for m in "abc"]
    for c in clouds:
        assert c.raw_points == 50 and len(c.xyz) == 49
        np.testing.assert_allclose(c.xyz, clouds[1].xyz, atol=1e-6)
        np.testing.assert_allclose(c.intensity, clouds[1].intensity, atol=1e-6)


def test_ply_binary(tmp_path):
    xyz = np.arange(12, dtype="<f4").reshape(4, 3)
    head = b"ply\nformat binary_little_endian 1.0\nelement vertex 4\nproperty float x\nproperty float y\n" \
           b"property float z\nend_header\n"
    (tmp_path / "p.ply").write_bytes(head + xyz.tobytes())
    np.testing.assert_allclose(read_cloud(tmp_path / "p.ply").xyz, xyz)
