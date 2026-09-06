# CLAUDE.md

台北捷運 Minecraft 1:1 重建。專案背景、資料來源與各階段的設計決策見 `README.md`
—— 那份文件是這個專案的真相來源，這份只講「在這裡工作要遵守什麼」。

## 硬性規則

- **Python 一律用 `./.venv/bin/python`**，絕不用系統 python。要裝套件用
  `./.venv/bin/pip`。（venv 是 3.9.6，別用 `X | Y` 這種 3.10+ 的型別語法。）
- **所有程式註解、docstring 與印出來的訊息都用繁體中文（台灣）**，與既有風格一致。
- **不要動 `out/`**。裡面是 1 GB 的既有存檔，重跑 `build_world` 要 20 分鐘以上。
  要測試就 `--out` 指到暫存目錄。
- 暫存檔放 scratchpad，不要寫進專案目錄。
- 任何 HTTP 請求都不要帶個人資料（姓名、email）。

## 架構

Clean Architecture。**相依方向一律由外往內，內層不得引用外層**：

```
mrt/
  config.py         專案路徑與世界垂直範圍。所有層都可以引用
  domain/           純規則，零 I/O：線形、鐵軌形狀、建築幾何、隧道分層、高程取樣
  ports/            內層對外層開的介面：BlockSink（逐格）、ChunkSink（整段批次）
  application/      用例：把 domain 算出來的東西寫進 BlockSink
  adapters/         外部資料進來：OSM (osm/)、DEM (dem/)、投影 (projection.py)
  infrastructure/   外部技術細節：Anvil 存檔寫入 (mcworld)、Overpass HTTP (overpass)

cli/                組合根。唯一看得到全部實作的地方，決定要把方塊寫進哪個 World
tools/              驗證與檢視：獨立讀回存檔，不信生成器的自述
tests/              不需要產生世界就能跑的測試
```

各層可以引用誰，定義在 `tests/test_architecture.py` 的 `ALLOWED`：

| 層 | 可引用 |
|---|---|
| `ports` | 只有標準函式庫 |
| `domain` | `domain`, `ports` |
| `application` | `domain`, `ports`, `application` |
| `infrastructure` | `ports`, `infrastructure` |
| `adapters` | `domain`, `ports`, `infrastructure`, `adapters` |

**改完一定要跑 `./.venv/bin/python tests/run_all.py`。** 目錄名稱擋不住任何人，
真正讓分層站得住的是 `test_architecture.py` —— 它會 parse 每個模組的 import
把違規揪出來。

### 這樣切的理由

- 生成器早就把世界當參數收（`def build_station(w, ...)`），只呼叫 `w.set()`。
  介面本來就存在，`ports/block_sink.py` 只是把它講出來。所以測試可以塞
  `DictSink` 進去，不必產生存檔。
- 線形算式（`domain/alignment.py`）和斷面砌法（`application/build_line.py`）
  變動的理由不同：斷面長怎樣是美術決定，線形算得對不對是工程決定。
- `domain/tunnel_layers.py` 曾經 `import build_world`（而且沒用到）。
  那個循環相依已經拿掉。

## 常用指令

```bash
# 資料管線（依序）
./.venv/bin/python -m mrt.adapters.osm.fetch_network      # OSM 路線幾何
./.venv/bin/python -m mrt.adapters.osm.fetch_stations     # 車站節點
./.venv/bin/python -m mrt.adapters.osm.fetch_way_tags     # way 標籤
./.venv/bin/python -m mrt.adapters.osm.fetch_branch       # 非標準代號的支線
./.venv/bin/python -m mrt.adapters.osm.fetch_details      # 出入口／站體／月台樓層
./.venv/bin/python -m mrt.adapters.projection             # 投影到 MC 座標
./.venv/bin/python -m mrt.adapters.dem.make_heightmap     # DEM -> 高程網格

# 生成
./.venv/bin/python -m cli.build_world                     # 全網 + 地形
./.venv/bin/python -m cli.build_world --rails             # 順便鋪鐵軌
./.venv/bin/python -m cli.build_line --lines BR           # 只蓋幾條線（快，不含地形）

# 測試與驗證
./.venv/bin/python tests/run_all.py                       # 全部單元測試
./.venv/bin/python tools/verify_render.py <存檔> out.png  # 讀回算俯視圖
./.venv/bin/python tools/verify_rails.py [存檔]           # 讀回驗證鐵軌連通性
./.venv/bin/python tools/slice_world.py 忠孝復興          # ASCII 剖面
```

## 驗證的態度

**不相信生成器的自述，一律從磁碟獨立讀回來比對。** `tools/` 底下每一支都是
這個原則的產物，README 的「驗證」一節列了它們各自抓到過什麼。

`verify_render.py` 有個坑：終端輸出只列前 20 種方塊，新加的材質排不進去就
看不到「未列入配色」的提示 —— 要直接掃圖上有沒有洋紅像素才算數
（洋紅會被高度陰影調暗，判斷條件是 `g=0 且 r=b`，不是 `r>200`）。
