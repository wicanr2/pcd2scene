# PCL 房間掃描

Point Cloud Library 資料庫的 `tutorials/room_scan1.pcd`（BSD-3-Clause，commit `084fa0e`）：一間約 7 m x 4.6 m 的辦公室，
一側開向走廊，11 萬 2586 點，`binary_compressed` 編碼。檔案不放在本 repo，`harness/run.sh demo-room` 執行時下載並核對 SHA-256
`52c373a6…`。

```bash
harness/run.sh demo-room
```

設定 [config.yaml](config.yaml) 只做三件事：裁掉窗外遠處的稀疏點、不放物件目錄（家具彼此相連，沒有固定尺寸）、
把預覽相機轉到開口那一側。驗收規格 [accept.json](accept.json)：一塊地面、至少三面牆、天花板高 2.7 到 3.2 m、
地面傾角 2 度內、覆蓋率在 0.05 m 內 0.9 以上且 0.1 m 內 0.99 以上。
