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
- **`demo/` 只放成品**。原始螢幕錄影 `demo/raw-*.mov`（928 MB）與中間檔
  `demo/.work/` 都在 `.gitignore` 裡。剪接點、字幕、抓圖的秒數全部寫在
  `demo/make_demo.py`，改素材要改那支腳本再重跑
  （`./.venv/bin/python demo/make_demo.py`），不要手工改成品。
- 任何 HTTP 請求都不要帶個人資料（姓名、email）。

## 架構

Clean Architecture。**相依方向一律由外往內，內層不得引用外層**：

```
mrt/
  config.py         專案路徑與世界垂直範圍。所有層都可以引用
  domain/           純規則，零 I/O：線形、鐵軌形狀、建築幾何、隧道分層、高程取樣、
                    地下街動線 (concourse)、真實出入口與轉乘通道的擺放與避讓 (exits)、
                    疊式車站與袋狀軌 (stacked)、行走可達性 (walk)、
                    搭乘系統的路網與上車位置 (network)
  ports/            內層對外層開的介面：BlockSink（逐格）、ChunkSink（整段批次）、
                    SignSink（告示牌：文字元件、發光、點擊指令、開對話框）
  application/      用例：把 domain 算出來的東西寫進 BlockSink；站內標誌 (signage)、
                    資料包規格 (ride_plan)、出生點 (spawn)
  adapters/         外部資料進來：OSM (osm/)、DEM (dem/)、投影 (projection.py)
  infrastructure/   外部技術細節：Anvil 存檔寫入 (mcworld)、讀回 (savereader)、
                    Overpass HTTP (overpass)、高度圖 (heightmap)、資料包 (datapack)

cli/                組合根。唯一看得到全部實作的地方，決定要把方塊寫進哪個 World。
                    `cli.build_world.plan_segments()` 只規劃不蓋，工具與試算腳本
                    靠它拿到跟生成器一模一樣的路段
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
./.venv/bin/python -m mrt.adapters.osm.fetch_indoor       # 地下人行動線（地下街）
./.venv/bin/python -m mrt.adapters.osm.fetch_sidings      # 袋狀軌／橫渡線／機廠線
./.venv/bin/python -m mrt.adapters.projection             # 投影到 MC 座標
./.venv/bin/python -m mrt.adapters.dem.make_heightmap     # DEM -> 高程網格

# 生成
./.venv/bin/python -m cli.build_world                     # 全網 + 地形
./.venv/bin/python -m cli.build_world --rails             # 順便鋪鐵軌
./.venv/bin/python -m cli.build_line --lines BR           # 只蓋幾條線（快，不含地形）
./.venv/bin/python -m cli.build_world --out /tmp/w \
    --bbox -900 -1400 400 250                             # 只產生台北車站一帶（十幾秒）

# 測試與驗證
./.venv/bin/python tests/run_all.py                       # 全部單元測試
./.venv/bin/python tools/verify_render.py <存檔> out.png  # 讀回算俯視圖
./.venv/bin/python tools/verify_rails.py [存檔]           # 讀回驗證鐵軌連通性
./.venv/bin/python tools/verify_exits.py <存檔>           # 讀回每座出入口，從街上走到月台
./.venv/bin/python tools/verify_concourse.py <存檔> --stations 台北車站 北門 中山 雙連
./.venv/bin/python tools/verify_exits.py <存檔> \
    --levels 府中 西門 中正紀念堂 古亭 東門                 # 疊式站要走得到兩層月台
./.venv/bin/python tools/verify_tracks.py <存檔> --station 西門 --expect 4 --levels 2
./.venv/bin/python tools/verify_tracks.py <存檔> --pocket 大安 信義安和 --expect 3
                                                          # 讀回每一刀有幾股鐵軌、各在哪個高度
./.venv/bin/python tools/verify_spawn.py <存檔> [--all]   # 讀回出生點與區塊高度圖，照遊戲的邏輯找一次出生點
./.venv/bin/python tools/verify_rides.py <存檔>           # 讀回每面搭車告示牌與資料包的傳送目的地
./.venv/bin/python tools/check_datapack.py <存檔>         # 資料包交給真的 26.2（無頭 GameTest 伺服器）載入執行
./.venv/bin/python tools/slice_world.py 忠孝復興          # ASCII 剖面
```

驗證的規則有兩條，別搞混：`verify_concourse` 是「不出地面」（腳要比當地地表低
兩格，逐格看地形），`verify_exits` 是「不踩土」（腳下只准是人造方塊）。
後者更嚴，出入口亭本身就在地面上，用前者驗不了它。`verify_exits` 對轉乘站
另外要求所有出入口在同一個連通分量裡（轉乘通道通不通）。

**穿堂層的高度只有一個定義**：`alignment.station_kind` / `LEVEL_DY`
（地下 +7、橋下 −6、月台上方 +8）。蓋車站的、擺出入口井的、接轉乘通道的、
驗證的都從那裡拿，別在別處再算一次 —— 差一格就是一整站走不通。
疊式車站（`domain/stacked.py`：府中、西門、中正紀念堂、古亭、東門）也守這一條：
上層就是原本的島式站，下層整層複製到 `LEVEL_H` 格底下，穿堂仍在 +7。
要改層距只能改 `LEVEL_H`。

**共用站體的兩條線在 `assign_bands` 裡是自己人**（`shared=`），而且規劃完
一定要看 `check_clearance` 的那一行：帶號沒衝突不代表箱涵沒交疊。
西門的釘樁曾經把板南線嚇到帶 2，台北車站的板南線因此撞進淡水信義線的站體，
帶號驗算完全沒發現。**「是自己人」的半徑（`stacked.ALLY_M`）只能貼著
「真的是同一座結構」的長度**（半座站體 + `SPLIT_M`，約 350 m）：原本設 500 m，
古亭以南並行 500 m、中線只差 7～13 m 的松山新店線與中和新蘆線就被判成不必
分層，兩座箱涵在同一個深度上重疊了 400 m。

**工具挑線形幾何一律過 `alignment.select_variants`。** OSM 同一條線常有上下行
兩個 relation，淡水信義線在大安一帶差 19 m；工具自己挑最近的一份就會挑到
生成器沒蓋的那一份，然後回報一個不存在的問題。

**上車位置只有一個定義**：`network.plan_berths`（`cli.build_world` 算一次）。月台上的
搭車告示牌（`signage`）與資料包的傳送目的地（`ride_plan`）都吃同一份 `berths`，
函式 id 只從 `network.ride_fn / turn_fn / go_fn / MENU_DIALOG` 來、命名空間只從
`config.DATAPACK_NS` 來 —— 牌子寫的指令跟資料包的檔名是同一份約定的兩端。
每個 ride/turn/go 函式恰好一行 `tp @s x y z yaw pitch`，`verify_rides` 靠它讀回。

**告示牌的兩條地雷**：`verify_exits` 靠「第一行以『出口』開頭、第二行是站名」認出入口亭，
別的牌子第一行不准以「出口」開頭；黃色混凝土是月台警示帶（兩支驗證器都靠它認月台），
路線色帶不准用它。點擊動作只放第一行 —— 遊戲對每一行的 click_event 都會執行一次。

**遊戲本身可以當驗證器。** 裝好的 26.2 client jar 附一個無頭 GameTest 伺服器
（`net.minecraft.gametest.Main`，用 launcher 附的 java），在沙盒裡跑得起來（一般伺服器要
開 port，跑不了）：`check_datapack` 用它載入資料包、執行每個傳送函式再讀回落點；
`heightmap.py` 的打包與方塊分類也是拿它存出來的區塊逐位元比過的（告示牌、旗幟、壓力板
在高度圖上算「擋」，跟直覺相反）。它沒有玩家：右鍵點牌、對話框畫面要進遊戲才驗得到。
格式問題別憑記憶：`net.minecraft.data.Main --reports` 會吐出完整的指令樹與登錄表。

## 授權

程式碼 GPL-3.0（`LICENSE`），`data/` 是 ODbL 1.0（`LICENSE-DATA`，繼承自
OpenStreetMap）。兩者都是 copyleft。新增資料檔到 `data/` 時要確認來源條款，
並更新 `LICENSE-DATA` 的檔案清單 —— 那份清單目前逐檔列出，不是萬用比對。

## 驗證的態度

**不相信生成器的自述，一律從磁碟獨立讀回來比對。** `tools/` 底下每一支都是
這個原則的產物，README 的「驗證」一節列了它們各自抓到過什麼。

`verify_render.py` 有個坑：終端輸出只列前 20 種方塊，新加的材質排不進去就
看不到「未列入配色」的提示 —— 要直接掃圖上有沒有洋紅像素才算數
（洋紅會被高度陰影調暗，判斷條件是 `g=0 且 r=b`，不是 `r>200`）。

**驗證器自己也會騙人。** 三個真的發生過的例子：把「地下」定成一個全域的
y 上限，車站多加兩座、地面低 3 m，整條地下街就被判成地表，六十個出入口
各成一個分量；驗證器用出口編號當鍵，西門捷運站 1 號與西門地下街 1 號互相蓋掉，
壞的那一半根本不會出現在報表裡；讀回的高度只到出口牌上方 6 m，高架站的
月台在 14 m 上面，整批高架站被判成走不到月台。看到離奇的結果，先懷疑驗證器。

**單元測試過了不代表蓋出來能走。** 測試用的是直線，真實線形斜 45 度時
兩格寬的樓梯相鄰兩階只有斜角相接，走到一半就斷 —— 只有 `--bbox` 蓋一小塊、
`verify_exits` 讀回來走一遍才看得到。改了車站或樓梯的幾何，至少蓋一個
斜線的站（六張犁、淡水）驗過再說。

**`ShaftStair` 的 `g0` 是樓板、`y_to` 是站立面，兩扇門開在同一面牆上。**
井底那扇門的上限夾在井口平台之下，站立面落差不到 3 格門洞就矮到鑽不過去
（淡江大學就是這樣壞的）。街面與穿堂差 0～2 m 的出入口走 `exits.place_gate`
（平面出入口），別把 `MIN_RISE` 調回 2。

**井與通道要避開別條線，不只避開自己這一區的東西。** 地下街的連絡梯井從 y61 挖到
深層那條線的穿堂，中途一定經過淺層那幾條線的深度 —— 台北車站往淡水信義線的那座井
曾經把板南線月台挖掉十幾公尺，`out/` 的舊存檔裡還是那樣。`build_concourse.plan` 現在
收 `exits.index_segments` 的占用表；新增任何會垂直穿越的東西都要查它。

**改了生成器，要對照舊版存檔。** `git worktree add <暫存目錄> HEAD` 加一個
`data/heightmap.npy` 的 symlink 就能用舊程式蓋同一塊地，再逐格 diff
（`savereader.read_volume` 兩邊各讀一次）；共用幹線把十二座車站挖空、
樓梯頂端差一格，都是這樣才看出來哪些差異是刻意的、哪些是壞掉的。
