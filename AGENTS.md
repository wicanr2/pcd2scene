# 給 AI agent 的工作說明

在乾淨環境（CI runner、別台主機、沒有對話記憶的 session）照下列步驟可以重現所有結果，不需要額外背景。

## 一個指令驗證全部

```bash
harness/run.sh all            # 自動選 docker（daemon 可用時）或 native
harness/run.sh --native all   # 沒有 docker：需要 Python 3.11 以上與 venv
```

結束碼：0 全部通過；1 測試或驗收失敗；2 環境不符（缺 docker 或 Python 3.11、缺下載工具、未知命令）。每一步的結果寫在 `out/harness-summary.json`，例如：

```json
{"mode": "docker", "commit": "...", "steps": {"doctor": "ok", "setup": "ok", "test": "pass", "demo-synth": "pass", "demo-office": "pass", "demo-room": "pass", "demo-room2": "pass", "check-formats": "pass"}}
```

native 模式沒有 `check-formats`（需要 docker 映像裡的 `check_urdf` 與 `gz sdf`），記為 `skipped`。

可用環境變數調整：

| 變數 | 預設 | 意義 |
| --- | --- | --- |
| `P2S_MODE` | auto | `docker`、`native` 或 `auto` |
| `P2S_OUT` | `out/` | 輸出目錄 |
| `P2S_DATA` | `data/` | 下載資料的快取目錄 |
| `P2S_CPUS`、`P2S_MEMORY` | CPU 數的一半（1 到 4）、4g | docker 容器的資源上限 |

## 各步驟

| 命令 | 做什麼 | 輸出 | 需要網路 |
| --- | --- | --- | --- |
| `doctor` | 檢查 docker 或 Python、sha256sum、下載工具 | 終端機 | 否 |
| `setup` | docker：建 `pcd2scene:<雜湊>` 映像；native：建 `.venv` 並裝 `requirements.lock` | 映像或 `.venv/` | 是（第一次） |
| `test` | `pytest tests/`：讀檔、設定檔合併、幾何、合成倉庫與辦公室對真值、三種格式結構與 JSON Schema、三種格式讀回一致、各步驟圖、輸出可重現 | 終端機 | 否 |
| `demo-synth` | 產生合成倉庫 → 還原（`--stages`）→ `compare` 對真值 → `accept` | `out/synth_warehouse/data/`、`out/synth_warehouse/scene/` | 否 |
| `demo-office` | 同上，合成辦公室 | `out/synth_office/data/`、`out/synth_office/scene/` | 否 |
| `demo-room` | 下載 PCL `room_scan1.pcd`（釘 commit 與 SHA-256）→ 還原（`--stages`）→ `accept` | `data/room_scan1.pcd`、`out/room_scan/scene/` | 是（下載一次，存在 `data/`） |
| `demo-room2` | 下載 PCL `room_scan2.pcd` → 還原 → `accept` | `data/room_scan2.pcd`、`out/room_scan2/scene/` | 是（同上） |
| `check-formats` | `check_urdf`、`gz sdf -k` 檢查各示範的輸出 | 終端機 | 是（第一次建檢查映像） |

docker 模式的容器一律 `--rm`、`--network none`、限制 CPU 與記憶體，原始碼唯讀掛載。下載在主機端做。

## 看結果

- `out/<示範>/scene/preview.png`：左輸入點雲、右還原場景。
- `out/<示範>/scene/overview.svg`：俯視圖，牆與物件標了類別。
- `out/<示範>/scene/accept.json`：每條驗收規則的數值與結果。
- `out/<示範>/scene/report.json`：覆蓋率與距離統計，定義見 [docs/spec.md](docs/spec.md)。
- `out/<示範>/scene/stages/`：每個步驟的圖與 `stages.json`，對照 [docs/tutorial.md](docs/tutorial.md) 與各範例的 README。

各指令的輸入、輸出、log 與結束碼見 [docs/commands.md](docs/commands.md)。

## 修改時的規則

- 改完程式先跑 `harness/run.sh all`，全部通過才提交。
- 輸出必須可重現：同一份輸入與設定要逐位元相同（`tests/test_pipeline.py::test_build_is_deterministic`）。亂數一律從設定的 `seed` 建立。
- `scene.json` 的欄位改動要同步 [schema/scene.schema.json](schema/scene.schema.json) 與 [docs/spec.md](docs/spec.md)，並依規格的版本規則處理 `version`。
- 套件版本只改 `requirements.txt`，再用 `harness/run.sh lock` 重產 `requirements.lock`，不要手改 lock。
- `out/`、`data/`、`.venv/` 不進版控。示範資料只下載，不放進 repo。
- 新增示範：在 `examples/<名稱>/` 放 `config.yaml`、`accept.json`、`README.md`，資料來源要能公開取得並釘版本與雜湊，再在 `harness/run.sh` 加一個命令。
- 驗收門檻來自實測值加餘裕；調門檻要在提交說明寫出新舊實測值。

## 程式位置

| 檔案 | 內容 |
| --- | --- |
| `src/pcd2scene/cli.py` | 命令列（[docs/commands.md](docs/commands.md)） |
| `src/pcd2scene/config.py` | 預設設定與 YAML 合併（[docs/config.md](docs/config.md)） |
| `src/pcd2scene/io_pcd.py` | PCD、PLY 讀檔，LZF 解壓 |
| `src/pcd2scene/reconstruct.py` | 還原流程（[docs/pipeline.md](docs/pipeline.md)） |
| `src/pcd2scene/models.py` | 目錄物件的參數化模型 |
| `src/pcd2scene/export.py` | URDF、SDF、USD |
| `src/pcd2scene/validate.py`、`accept.py`、`evaluate.py` | 品質指標、驗收、對真值 |
| `src/pcd2scene/synth.py` | 合成倉庫、辦公室與真值 |
| `src/pcd2scene/render.py`、`overview.py` | 預覽圖與俯視圖 |
| `src/pcd2scene/stages.py` | 各步驟的圖（`build --stages`） |
| `src/pcd2scene/viewer.py` | 讀回 URDF、SDF、USD 畫圖（`pcd2scene view`） |
