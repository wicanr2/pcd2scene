# 場景格式規格 1.0

pcd2scene 把點雲還原成一份中介表示 `scene.json`，再由它產生 URDF、SDF 與 USD。三種格式內容一致，因為都從同一份 `scene.json` 展開。機器可讀的定義在 [schema/scene.schema.json](../schema/scene.schema.json)，測試會用它驗證每一次輸出。

## 單位與座標

- 長度用公尺，角度用弧度，右手座標系。
- 輸入座標：讀進來的點雲座標，套用 `input.transform` 之後的座標也算輸入座標。
- 場景座標：地面平面在 z = 0，+z 朝上。`floor.mode: level`（預設）時，用把地面法向量轉到 +z 的最小旋轉把點雲轉正，再沿 z 平移；水平方向不另外旋轉，所以 x、y 軸大致沿用輸入座標。`floor.mode: shift` 只做 z 平移，不轉正。
- `frame.T_scene_from_input` 是 4x4 齊次矩陣，把原始點雲檔案裡的點（含 `input.transform`）轉到場景座標。匯出時選 `frame: input`，根節點會帶這個矩陣的反變換，幾何就回到原始點雲座標，可以直接疊在定位地圖上。

## scene.json

### 頂層欄位

| 欄位 | 內容 |
| --- | --- |
| `format` | 固定 `pcd2scene/scene` |
| `version` | 規格版本，目前 `1.0` |
| `units`、`up` | 固定 `m`、`+z` |
| `tool` | 產生它的工具名稱與版本 |
| `source` | 點雲檔名、SHA-256、各階段點數（原始、有限值、裁切後、體素後），以及每個點最後的歸屬統計 `labels` |
| `config_sha256` | 完整設定（預設值合併使用者 YAML 之後）的 SHA-256。同一份點雲加同一份設定，輸出逐位元相同 |
| `frame` | `T_scene_from_input`、`floor_plane`（輸入座標的地面平面 n·p + d = 0，n 朝上）、`mode` |
| `elements` | 場景元素清單 |

### 元素

每個元素是一個剛體，有位姿和一組零件。

| 欄位 | 內容 |
| --- | --- |
| `id` | 唯一名稱，符合 `[A-Za-z_][A-Za-z0-9_]*`，直接用作 URDF link、SDF link 與 USD prim 名稱 |
| `kind` | `floor`、`ceiling`、`wall`、`object`、`mesh` |
| `class` | 類別。地面、天花板、牆、殘餘網格與 kind 同名；目錄物件是目錄裡的類別名稱；沒對上目錄而輸出外接盒的叢集是 `unknown` |
| `pose` | `xyz` 與 `yaw`：元素座標原點在場景座標的位置，以及繞 z 的旋轉 |
| `parts` | 零件清單，座標在元素座標內 |
| `export` | 省略時為 true。`false` 的元素留在 `scene.json` 與驗證裡，不輸出到 URDF、SDF、USD（天花板預設如此） |
| `collision` | 只用在 `mesh` 元素。`false` 時網格只當 visual |
| `units` | 目錄物件的重複單元數，例如一排貨架的格數 |
| `stats`、`observed`、`model` | 統計與紀錄：點數、牆面填滿率、觀測到的長寬高、模型參數（例如自動偵測的層板高度） |

各種元素的原點：

| kind | 原點與方向 |
| --- | --- |
| `floor`、`ceiling` | 場景原點，`yaw` 是格點方向（對齊最長那面牆）；零件是格點分解出的矩形板 |
| `wall` | 牆底面中心，x 沿牆長方向；一個零件，盒心在 (0, 0, 高/2) |
| `object` | 佔地矩形中心、物件底部，x 沿長邊、y 沿短邊 |
| `mesh` | 場景原點；零件是 `meshes/` 下的網格 |

### 零件

| type | 欄位 |
| --- | --- |
| `box` | `size`：x、y、z 三邊長；`xyz`：盒心在元素座標的位置。零件不旋轉 |
| `mesh` | `file`：輸出目錄內的相對路徑，限 `meshes/*.stl`（二進位 STL）；`xyz`、`scale` |

## 輸出目錄

| 檔案 | 內容 |
| --- | --- |
| `scene.json` | 中介表示 |
| `meshes/*.stl` | 殘餘網格與目錄引用的外部網格 |
| `scene.urdf`、`scene.sdf`、`scene.usda` | 三種格式，網格以相對路徑引用 `meshes/` |
| `report.json` | 品質指標，見下節 |
| `overview.svg` | 俯視總覽：點的佔據格、地面、牆、物件與類別標籤 |
| `preview.png` | 同一相機下的輸入點雲與還原場景 |
| `config.resolved.json` | 合併後的完整設定 |
| `stages/` | 只在 `build --stages` 時產生：各步驟的圖 `01_input.png` 到 `11_usd.png` 與數字摘要 `stages.json`，見 [tutorial.md](tutorial.md) |

## 三種格式的對應

| scene.json | URDF | SDF 1.9 | USD |
| --- | --- | --- | --- |
| 整個場景 | `robot name="scene"`；`world` link 以 fixed joint 接 `scene_root`，joint origin 是匯出座標的根變換 | `world name="scene"` 內一個 `static` 的 `model name="scene"`，model pose 是根變換 | `/World`（default prim）下的 `/World/Scene` Xform，transform op 是根變換；`upAxis = Z`、`metersPerUnit = 1` |
| 元素 | 一個 link，以 fixed joint 接 `scene_root`，joint origin 是元素位姿 | 一個 link，pose 是元素位姿 | 一個 Xform，customData 記 `pcd2scene:class` 與 `pcd2scene:kind` |
| box 零件 | 一組同幾何的 visual 與 collision | 一組 collision 與 visual | `Cube`（size 1，transform 帶縮放），套 `PhysicsCollisionAPI` |
| mesh 零件 | `mesh filename`，路徑形式由 `export.mesh_uri` 決定 | `mesh uri` | `Mesh` prim（頂點寫進檔案），套 `PhysicsCollisionAPI` 與 `PhysicsMeshCollisionAPI`（approximation none） |
| 顏色 | 每個類別一個 material | material 的 ambient、diffuse | `displayColor` |

其他慣例：

- URDF 每個 link 帶 1 kg 的佔位慣量，並加 `<gazebo><static>true</static></gazebo>`。Gazebo 會丟掉沒有慣量的 link，這兩項讓它整個當靜態物體載入。
- `export.mesh_uri`：`relative`（預設，相對於輸出檔）、`file`（絕對 `file://` 路徑）、`package:<名稱>`（`package://<名稱>/meshes/...`，給 ROS 套件用）。
- 驗證工具：`check_urdf`（urdfdom）、`gz sdf -k`（sdformat14）、USD 的 `UsdValidation` 全部驗證器。`harness/run.sh check-formats` 與測試會跑這三項。

## 品質指標（report.json）

| 欄位 | 定義 |
| --- | --- |
| `coverage.<tol>` | 體素後的輸入點中，離最近場景表面不超過 tol 公尺的比例。地面以下、天花板以上、`drop` 掉的點與零星點（outlier）不算 |
| `distance_m` | 同一組距離的中位數、95 百分位與最大值 |
| `support.by_element` | 每個元素表面取樣點中，離最近輸入點不超過最大 tol 的比例。貼地的底面、靠牆的背面本來就掃不到，所以只當參考 |
| `elements` | 每個類別的元素數 |
| `labels` | 每個點最後的歸屬：floor、ceiling、wall、object、residual、outlier、below_floor、above_ceiling、dropped |

`coverage` 衡量點雲被解釋了多少；目錄物件用標準尺寸的參數化模型取代觀測，所以覆蓋率會略低於全部用網格。

## 版本規則

- 只增加選用欄位時，`version` 不變，舊的讀取端照常可用。
- 改變既有欄位的意義、單位或必填性時，主版號加一，並在 [CHANGELOG.md](../CHANGELOG.md) 說明轉換方式。
