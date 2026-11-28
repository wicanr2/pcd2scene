# 變更紀錄

## 未發布

- 殘餘網格：同一平面上相鄰的體素面合併成矩形（`mesh.merge_faces`，預設開）。形狀不變，三角形數：合成倉庫 20,732 → 9,580、合成辦公室 9,708 → 5,674、PCL 房間 66,468 → 38,012、room_scan2 79,620 → 52,762（含下一項的效果）。
- 殘餘點的離群濾波：10 cm 體素 26 連通後點數不到 10 的小叢集標成 `outlier`，不建模，也不算進覆蓋率（`mesh.outlier_voxel`、`mesh.outlier_min_points`，預設開，設 0 關閉）。`scene.json` 的 `labels` 多一種值 `outlier`，殘餘元素的 `stats` 多一個 `outlier_points`；只增加選用欄位，規格版本維持 1.0。
- 驗證：網格表面改成依 `validate.sample_step` 在三角形上均勻取樣，原本只取頂點與重心，合併後的大三角形會取樣不足。覆蓋率（5 cm）：合成倉庫 99.97% → 99.90%、PCL 房間 93.07% → 92.86%、room_scan2 90.13% → 89.90%；10 cm 內都維持 100%，驗收門檻不變。
- 文件：新增 [docs/related-work.md](docs/related-work.md)，比較 pointcloud2gazebo、usd-convert-asset、bag_to_gazebo_world、Open3D、OpenUSD；README 加上各專案的優缺點。
- 文件：更正 PCL 房間範例第 8 步的說明。殘餘網格裡排成弧形的點列在離地約 2.58 m 處，是天花板下方另一層水平結構的掃描線，不是地面上的零星點。
- 文件：新增 [docs/commands.md](docs/commands.md)，逐一說明每個指令的輸入、輸出、範例輸出、log 與結束碼；指令與檔案關係圖 `docs/images/flow.svg`、點的歸屬圖 `docs/images/point_labels.svg`。
- 文件：合成辦公室與 PCL 房間的範例頁改成逐步圖解（原始點雲到 URDF、USD 的 11 張圖，每步列出輸入與輸出）；`room_scan2` 加上調整 `walls.min_fill` 前後的對照圖；教學的步驟表加上輸入、輸出欄。
- 修正：設定檔某個區段的欄位全被註解掉（例如只剩 `walls:`）時，`build` 會因區段變成 null 而失敗；現在沿用預設值。區段寫成非 mapping 的值時明確報錯。
- CI：`actions/checkout` v7.0.1、`actions/setup-python` v7.1.0、`actions/upload-artifact` v7.0.2，以 commit SHA 固定，三者都在 Node.js 24 上執行。

## 0.2.0（2026-11-27）

- `build --stages`：把每個步驟的中間結果畫成圖（`stages/01_input.png` 到 `11_usd.png`）與 `stages/stages.json`。
- `pcd2scene view`：直接讀 `scene.urdf`、`scene.sdf`、`scene.usda` 畫成 PNG。
- `synth --layout office`：10 m x 7 m 辦公室，有天花板、辦公桌、櫃子與書架；`compare` 加天花板高度與依版面的地面範圍。
- 新示範 `synth_office` 與 `room_scan2`（PCL 同一房間的另一次掃描，示範 `input.transform` 與依候選調整 `walls.min_fill`）。
- 新文件 [docs/tutorial.md](docs/tutorial.md)：逐步說明每個步驟的輸入、處理與輸出圖。

## 0.1.0（2026-11-27）

- 第一版：PCD／PLY 讀檔（含 binary_compressed）、地面與天花板、牆、目錄物件（box、table、rack、mesh）、殘餘體素網格。
- 輸出 `scene.json`（規格 1.0）、URDF、SDF 1.9、USD，以及 `report.json`、`overview.svg`、`preview.png`。
- `harness/run.sh`：docker 與 native 兩種模式；合成倉庫與 PCL 房間掃描兩個示範附驗收規格。
