# 合成倉庫

`pcd2scene synth` 產生的倉庫點雲（`warehouse.pcd`）、真值（`truth.json`）與物件目錄（`catalog.yaml`），
用來驗證地面、牆與目錄物件的還原。內容見 [synth.py](../../src/pcd2scene/synth.py) 開頭的說明。

```bash
harness/run.sh demo-synth
```

驗收規格：[accept.json](accept.json)。`compare.pass` 表示真值地面四角還原後離 z = 0 在 3 cm 內，每面牆與每個物件都在真值的 0.2 m、3 度內，牆長差 0.4 m 內，貨架的格數相同、層板高度差 0.05 m 內。
