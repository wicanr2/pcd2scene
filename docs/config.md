# 設定

`pcd2scene build CLOUD -c config.yaml` 讀 YAML，逐層覆蓋 [config.py](../src/pcd2scene/config.py) 的預設值。拼錯的欄位會直接報錯，不會被默默忽略；區段底下的欄位全被註解掉（只剩 `walls:`）時沿用該區段的預設值。合併後的完整設定寫在輸出目錄的 `config.resolved.json`，它的 SHA-256 記在 `scene.json` 的 `config_sha256`。

## 欄位

| 欄位 | 預設 | 意義 |
| --- | --- | --- |
| `seed` | 0 | RANSAC 亂數種子 |
| `input.transform` | null | 讀檔後先套用的 4x4 矩陣（列優先的巢狀清單） |
| `input.crop` | null | `[xmin, ymin, zmin, xmax, ymax, zmax]`，套用 transform 之後的座標 |
| `preprocess.voxel` | 0.03 | 體素平均的邊長 |
| `preprocess.min_points` | 1 | 體素內少於這個點數就丟掉 |
| `floor.max_tilt_deg` | 10 | 水平面法向量與 +z 的最大夾角 |
| `floor.inlier` | 0.03 | 平面 RANSAC 的內點距離 |
| `floor.band` | 0.05 | 離地面這個距離內的點歸地面 |
| `floor.min_fraction` | 0.02 | 水平面至少要有這個比例的點 |
| `floor.max_planes` | 4 | 最多找幾個水平面 |
| `floor.ransac_iters` | 400 | |
| `floor.mode` | level | `level` 轉正並移到 z = 0；`shift` 只做 z 平移 |
| `floor.cell` | 0.2 | 地面與天花板範圍的格點邊長 |
| `floor.fill_holes` | 2 | 格點閉運算次數 |
| `floor.thickness` | 0.1 | 地面板厚度（往 z 負方向） |
| `ceiling.detect` | true | 是否找天花板 |
| `ceiling.min_height` | 1.8 | 天花板至少比地面高這麼多 |
| `ceiling.band` | 0.08 | |
| `ceiling.export` | false | 是否輸出天花板到 URDF、SDF、USD |
| `ceiling.thickness` | 0.1 | |
| `walls.cell`、`walls.zbin` | 0.05、0.1 | 平面格子與高度格 |
| `walls.min_height` | 1.8 | 牆頂最低高度 |
| `walls.min_length` | 1.5 | 最短牆長。貨架框架深度通常在 1.2 m 以下 |
| `walls.min_fill` | 0.33 | 牆面填滿率門檻，見 [pipeline.md](pipeline.md#3-牆) |
| `walls.inlier` | 0.05 | 直線內點距離 |
| `walls.max_gap` | 0.4 | 同一面牆允許的最大間隙 |
| `walls.thickness` | 0.1 | 只看到一面時的牆厚 |
| `walls.margin` | 0.06 | 牆盒外這個距離內的點歸牆 |
| `walls.ceiling_contact` | 0.4 | 有天花板時，牆頂與天花板的最大距離；null 表示不檢查 |
| `walls.max_walls`、`walls.ransac_iters` | 64、300 | |
| `objects.cluster_voxel` | 0.08 | 分群體素；兩個物件距離小於約兩倍這個值會併成一群 |
| `objects.min_points` | 30 | 叢集最少點數（體素後） |
| `objects.min_height` | 0.08 | 叢集最矮高度 |
| `objects.floor_contact` | 0.15 | 底部離地這個距離內視為落地 |
| `objects.margin` | 0.06 | 物件盒外這個距離內的點歸該物件 |
| `objects.unknown` | mesh | 沒對上目錄的叢集：`mesh`、`box`、`drop` |
| `objects.catalog` | [] | 物件目錄，見下節 |
| `mesh.voxel` | 0.05 | 殘餘網格的體素邊長 |
| `mesh.min_points` | 1 | |
| `mesh.collision` | true | 殘餘網格是否當碰撞體 |
| `validate.tolerances` | [0.05, 0.1] | 覆蓋率的距離門檻 |
| `validate.sample_step` | 0.03 | 場景表面取樣間距 |
| `preview.*` | -55、38、900、640 | 預覽相機的方位角、仰角（度）與影像大小；`--stages` 的 3D 圖沿用同一組角度 |
| `export.formats` | [urdf, sdf, usd] | |
| `export.frame` | scene | `scene` 或 `input`，見 [spec.md](spec.md#單位與座標) |
| `export.mesh_uri` | relative | `relative`、`file`、`package:<名稱>` |

## 物件目錄

```yaml
objects:
  catalog:
    - class: rack                  # 識別字，會成為元素名稱的前綴
      size: [2.7, 1.1, 3.0]        # 單元長、寬、高；長 >= 寬
      tolerance: [0.3, 0.15, 0.25] # 長、寬、高的容許誤差；省略時各為 15%
      array: {pitch: 2.7, max_units: 64}   # 沿長邊重複的單元；省略表示單一物件
      on_floor: true               # 預設 true：只比對落地的叢集
      model:
        type: rack
        levels: auto               # 或 [1.0, 2.0]：橫樑頂面高度
        upright: [0.09, 0.07]      # 立柱截面
        beam: [0.1, 0.05]          # 橫樑高、深
        brace: [0.04, 0.6]         # 框架橫撐截面與間距；null 表示不要
        deck: false                # 每層是否加層板
    - class: table
      size: [1.6, 0.8, 0.75]
      model: {type: table, top_thickness: 0.04, leg: 0.05, leg_inset: 0.05}
    - class: pallet
      size: [1.2, 1.0, 0.15]
      model: {type: box}
    - class: charger
      size: [0.6, 0.4, 0.5]
      model: {type: mesh, file: assets/charger.stl, scale: [1, 1, 1]}
```

模型類型：

| type | 零件 |
| --- | --- |
| `box` | 一個盒子，`n` 格時長度為總長 |
| `table` | 桌面板加四支腳 |
| `rack` | 每個框架兩支立柱加橫撐、每格每層前後兩支橫樑，可選層板 |
| `mesh` | 外部二進位 STL，相對路徑以設定檔所在目錄為準，會複製到輸出的 `meshes/`。網格原點要在佔地中心的底部，x 沿長邊 |

比對規則：寬與高都在容許誤差內，長度與 `(n - 1) x pitch + 單元長` 的差也在容許誤差內，取正規化誤差總和最小的類別。
