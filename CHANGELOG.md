# 變更紀錄

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
