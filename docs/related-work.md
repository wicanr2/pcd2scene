# 相關專案比較

點雲轉成模擬場景的開源專案，分成完整工具與函式庫兩類。三個工具的內容都依原始碼核對過，版本與日期是 2026-11-28 查詢的結果。

| 專案 | 讀碼版本 | 授權 |
| --- | --- | --- |
| [pointcloud2gazebo](https://github.com/CyberAgentAILab/pointcloud2gazebo) | main `7dbe689`（2023-12-12） | BSD-3-Clause |
| [usd-convert-asset](https://github.com/NVIDIA-Omniverse/usd-convert-asset) | v2.0.0（2026-11） | 程式 Apache-2.0、文件 CC-BY-4.0；FBX SDK 另有第三方授權 |
| [bag_to_gazebo_world](https://github.com/gglaspell/bag_to_gazebo_world) | main `1547971`（2026-05-26，已封存） | MIT |
| [Open3D](https://github.com/isl-org/Open3D) | v0.20.0（2026-09） | MIT |
| [OpenUSD](https://github.com/PixarAnimationStudios/OpenUSD) | pcd2scene 使用 `usd-core` 26.11 | Tomorrow Open Source Technology License 1.0 |

## 工具比較

| | pcd2scene | pointcloud2gazebo | usd-convert-asset | bag_to_gazebo_world |
| --- | --- | --- | --- | --- |
| 輸入 | 已對位的 PCD（含 binary_compressed）、PLY | Open3D 能讀的點雲檔（PCD、PLY） | PLY、OBJ、STL、FBX、glTF；不收 PCD | ROS 2 bag 的 PointCloud2（只取 xyz），可加里程計 |
| 處理 | 地面與天花板轉正、牆、地面板、分群、比對物件目錄、殘餘網格 | 體素、高度裁切、半徑離群濾波、alpha shape | 格式轉換；點雲不重建表面 | 逐幀 ICP、pose graph、可選的迴路閉合、離群濾波、DBSCAN 只留最大群、Poisson |
| 輸出 | URDF、SDF 1.9、USD | 一個 STL 加 Gazebo Classic 的 world | USD | STL 加 Gazebo Classic 的 world |
| 語意 | 地面、牆、天花板與目錄物件各自成為元素，有類別與尺寸 | 無，整個場景一塊網格 | 無 | 無，整個場景一塊網格 |
| 碰撞 | 牆與地面是方塊，物件用參數化模型，殘餘用網格且可關閉 | 碰撞與外觀共用同一個 STL；摩擦係數 1.2 | 不產生物理屬性 | 碰撞與外觀共用同一個 STL |
| 可重現 | 固定 seed，同一輸入與設定的輸出逐位元相同 | 未提供 | 未說明 | 相依套件不鎖版 |
| 測試 | 單元測試、CI、示範資料的驗收規格 | 無 | 有測試，沒有 CI | 無 |
| 維護 | 持續開發 | 2 個 commit，2023 年後沒有更新 | NVIDIA 持續發版，不收外部 PR | 4 個 commit，作者已改到 [bellhop](https://github.com/gglaspell/bellhop) 開發 |

### pointcloud2gazebo

流程（`pointcloud2gazebo.py`、`config/` 下的設定）：5 cm 體素、z 範圍裁切、半徑離群濾波（0.1 m 內至少 16 點）、alpha shape（範例設定 0.15，程式預設 0.1），輸出一個 STL，放進手寫的靜態 Gazebo Classic model（`models/pointcloud2gazebo/model.sdf`，`mu` 1.2）。

- 優點：流程短，容易讀懂與修改。alpha shape 的網格比體素表面平滑。
- 缺點：
  - 結果對 `alpha` 與點密度敏感，密度不均時容易破洞或黏連。
  - 擺放位置寫死在 world 檔，只支援 Gazebo Classic。
  - 輸入要先是對位好的地圖，沒有 rosbag 支援（issue #1）。
  - 停止維護，沒有測試。

### usd-convert-asset

把常見網格格式轉成 USD 的命令列工具與函式庫，也包裝成 agent skill。PLY 點雲轉成 `UsdGeom.Points`，點寬固定 0.01（`source/library/exporters/usd/usd_exporter.cpp` 註明是經驗值），顏色只取第一組。

- 優點：官方維護，網格格式的支援面廣，不需要 Omniverse Kit 或 GPU。
- 缺點：
  - 點雲不重建表面，也不產生碰撞與物理屬性。
  - 自帶一份 OpenUSD，README 警告不要和其他 OpenUSD 或 `usd-core` 在同一個 Python 行程裡混用。
  - 限 Python `>=3.12.4,<3.13`。
  - 不收 PCD。

### bag_to_gazebo_world

從 ROS 2 bag 直接產生 Gazebo world：

1. 對位：逐幀點對面 ICP，接 pose graph 最佳化，可選 FPFH 加 RANSAC 的迴路閉合。
2. 選用的 `level_floor`：用最大平面把地面轉平。
3. 清理：半徑與統計離群濾波，DBSCAN 只留最大的一群。
4. 重建：Poisson（depth 9），依密度修剪低支撐的區域，刪掉離輸入點超過 0.15 m 的頂點，再做 quadric 減面。
5. 輸出 STL 與 Gazebo Classic 的 world，碰撞與外觀共用網格。

- 優點：從原始 bag 一路做到 world。Poisson 之後的密度修剪、距離修剪與減面是完整的後處理，可以壓住 Poisson 在沒有點的地方鼓出的假表面。
- 缺點：
  - 逐幀 ICP 的初值是單位矩陣，移動快或特徵少時容易漂移。
  - DBSCAN 只留最大群，和主體不相連的結構會被丟掉。
  - 相依套件不鎖版，已封存。讀碼時懷疑有兩處變換方向寫反，沒有實際執行驗證。

## 函式庫

- **Open3D**：表面重建（Poisson、ball pivoting、alpha shape）、離群濾波、ICP 都很成熟。代價是相依很重：Linux 完整 wheel 約 401 MB，`open3d-cpu` 約 105 MB，還會帶進 dash、flask 等套件。Poisson 的結果依法向量估計而定，不保證跨版本逐位元相同。
- **OpenUSD**：pcd2scene 已經透過 `usd-core` 用 `pxr` 直接寫 USD，包括 `UsdGeom.Mesh`、`UsdPhysics` 的碰撞 API。`UsdGeom.Points` 也在同一個套件裡，不需要額外工具。

## 已納入 pcd2scene 的

| 項目 | 來源想法 | pcd2scene 的作法 |
| --- | --- | --- |
| 殘餘點的離群濾波 | pointcloud2gazebo 的半徑濾波、bag_to_gazebo_world 的 DBSCAN | 用 10 cm 體素做 26 連通，點數不到 10 的小叢集標成 outlier。用連通而不用固定半徑，因為真實掃描遠處稀疏但連續的表面會被固定半徑整片刪掉。不加相依套件。設定見 [config.md](config.md) 的 `mesh.outlier_*` |
| 減少殘餘網格的三角形 | bag_to_gazebo_world 的減面 | 同一平面上相鄰的體素面合併成矩形（`mesh.merge_faces`）。形狀與逐面輸出完全相同，結果仍逐位元可重現。PCL 房間掃描的殘餘網格從 66,468 個三角形降到 38,012 個，其中離群濾波與合併各佔一部分 |

## 可以再考慮的

| 項目 | 來源 | 作法與代價 |
| --- | --- | --- |
| 選用的平滑網格 | Open3D、bag_to_gazebo_world | `mesh.method: voxel \| poisson \| alpha`，Open3D 當選用相依，預設維持 voxel。要連同密度修剪、距離修剪與減面一起做。單次掃描的法向量方向容易估錯，結果也不保證逐位元相同 |
| USD 點雲檢查層 | usd-convert-asset 的 `UsdGeom.Points` | 選用輸出輸入點，依歸屬（floor、wall、object、residual、outlier）上色，在 Isaac Sim 裡疊在場景上檢查對位。用 `pxr` 直接寫 |
| 物理材質 | pointcloud2gazebo 的摩擦係數 | 地面與牆加摩擦係數：SDF 用 `<surface><friction>`，USD 用 `UsdPhysics.MaterialAPI`。輪式機器人與地面的接觸會用到 |

## 不納入的

- **bag 讀取與多幀對位**：這是 SLAM 的工作。pcd2scene 的輸入假設是已對位的地圖，先用 SLAM 工具產生地圖再交給 pcd2scene。
- **usd-convert-asset 當相依**：它自帶的 OpenUSD 會和 `usd-core` 衝突，Python 版本範圍太窄，還牽涉 FBX SDK 的授權。
- **Gazebo Classic 的 world 格式**：pcd2scene 輸出 SDF 1.9，對應新版 Gazebo。
