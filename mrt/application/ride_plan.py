#!/usr/bin/env python3
"""搭乘系統的資料包規格：把路網（domain/network.py）變成一份純資料。

月台上的告示牌只負責「點了執行哪個函式」（mrt:ride/bl12_bl13、mrt:turn/bl01_m），
售票機的告示牌打開路線圖對話框（mrt:network）。這裡把那些 id 背後真正要做的事
寫成 Minecraft 指令與對話框 JSON：

  ride/*   坐一站：傳送到下一站同一個行車方向的月台、正對著繼續往前的那面牌，
           大標題是到站的站名（線色），副標題是站號、英文站名與路線，
           動作列提示「下一站」，再響一聲到站鈴
  turn/*   終點站到站側的牌：換到對面月台（往回開的那一側）的主位
  go/*     路線圖的站名按鈕：傳送到那一站有下一站那一側的主位
  sight/*  景點清單的按鈕與景點裡的告示牌：傳送到景點的觀景點（或 101 的觀景台）
  sys/*    載入、每 tick、首次進入、trigger 分派、進站提示（HUD）、世界初始設定

**約定**（tools/ 的讀回驗證器與 tools/check_datapack.py 靠它）：每個 ride/*、turn/*、
go/*、sight/* 函式恰好有一行 ``tp @s <x> <y> <z> <yaw> <pitch>``，座標是絕對的數字，
x、z 是站位方塊的中心（+0.5）、y 是腳所在的方塊。

這一層只產生 dict／list／字串，不碰檔案：寫檔在 infrastructure/datapack.py，
命名空間與資料夾名稱在 config（告示牌那一端也從那裡拿）。
"""
import json
import math

from mrt import config
from mrt.application.attractions.kit import sight_fn
from mrt.domain import alignment as AL
from mrt.domain import network as NW
from mrt.domain import stacked as SK

NS = config.DATAPACK_NS

# ---- 記分板與標籤（全部掛命名空間前綴，不跟別的資料包撞名）----
OBJ_GO = NS + ".go"          # trigger：路線圖的站名按鈕（/trigger mrt.go set <n>）
OBJ_MENU = NS + ".menu"      # trigger：打開路線圖（/trigger mrt.menu）
OBJ_STATE = NS + ".state"    # dummy：#setup 世界初始設定的版本、#notice 設定通知待送、#beat HUD 心跳
OBJ_AREA = NS + ".area"      # dummy：玩家上一輪在哪一站的範圍（進站提示只亮一次）
OBJ_HERE = NS + ".here"      # dummy：這一輪掃描時玩家在哪一站的範圍（0 = 不在任何車站）
TAG_JOINED = NS + ".joined"  # 玩家標籤：來過了（首次進入的傳送與歡迎訊息只做一次）

SETUP_VERSION = 1            # 世界初始設定改了就加一：舊世界 /reload 之後會再套一次
HUD_EVERY = 10               # 進站提示每幾 tick 掃一次（每秒兩次，全網約兩百個選擇器）
HOME = ("R", "台北車站")      # 首次進入的落腳處：淡水信義線台北車站（R10）的主位

# 視線：人眼高 1.62 格，瞄準告示牌方塊裡 0.6 格高的地方（牌面中間）。
# 傳送過去時準星正好落在牌上，再按一次右鍵就是下一站。
EYE_H, AIM_H = 1.62, 0.6

# 到站鈴：兩聲鐘琴疊在一起，相差一個完全四度（音高 1.0 與 1.335 = 2^(5/12)）
CHIME = ("minecraft:block.note_block.chime", 0.8, (1.0, 1.335))

# 世界初始設定：(規則, 設定值, 26.2 預設值, 說明)。26.2 的規則 id 是 snake_case，
# 清單取自遊戲產生的 game_rules.dat（見 tools/check_datapack.py 的遊戲內驗證）。
GAME_RULES = [
    ("spawn_monsters", "false", "true", "不生成敵對生物"),
    ("spawn_phantoms", "false", "true", "不生成夜魅"),
    ("spawn_patrols", "false", "true", "不生成災厄巡邏隊"),
    ("spawn_wandering_traders", "false", "true", "不生成流浪商人"),
    ("advance_time", "false", "true", "時間停在中午"),
    ("advance_weather", "false", "true", "天氣固定晴天"),
    ("keep_inventory", "true", "false", "死亡不掉落物品"),
    ("mob_griefing", "false", "true", "生物不破壞方塊"),
    ("respawn_radius", "0", "10", "重生不隨機偏移"),
]
NOON = 6000

ATTRIBUTION = "地圖資料 © OpenStreetMap contributors（ODbL 1.0）"
MENU_TITLE = "台北捷運路線圖"


# ---------- 小工具 ----------

def fid(path):
    """函式／對話框路徑 -> 完整 id（"ride/bl12_bl13" -> "mrt:ride/bl12_bl13"）。"""
    return "%s:%s" % (NS, path)


def text(obj):
    """文字元件 -> 指令裡的字面值。

    26.2 的指令吃 SNBT；JSON 是它的子集（雙引號鍵、true、\\n 跳脫都認得），
    所以直接 json.dumps。中文不跳脫，函式檔是 UTF-8。
    """
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def line_name(ref):
    return NW.LINE_NAMES.get(ref, (ref, ref))


def line_order(refs):
    """路線的顯示順序：照 LINE_NAMES（北捷的路線編號順序），沒列到的排最後。"""
    known = list(NW.LINE_NAMES)
    return sorted(refs, key=lambda r: (known.index(r) if r in known else len(known), r))


def aim(slot):
    """(x, y, z, yaw, pitch)：站在 slot 的站位中心、面向並瞄準那面告示牌。

    偏航角用站位到牌子的方塊中心算，不直接用 slot.yaw（月台門的法向）：
    斜 45 度的站，牌子取整之後不一定正好在法向上，差半格就可能瞄不到牌。
    """
    sx, sy, sz = slot.sign
    tx, ty, tz = slot.stand
    fx, fz = sx - tx, sz - tz
    dist = math.hypot(fx, fz)
    yaw = NW.yaw_of(fx, fz) if dist > 0 else slot.yaw
    pitch = round(math.degrees(math.atan2(EYE_H - AIM_H + (ty - sy), max(dist, 0.5))), 1)
    return tx + 0.5, ty, tz + 0.5, yaw, pitch


def tp_line(slot):
    """約定的那一行：tp @s <x> <y> <z> <yaw> <pitch>（絕對座標）。"""
    x, y, z, yaw, pitch = aim(slot)
    return "tp @s %.1f %d %.1f %.1f %.1f" % (x, y, z, yaw, pitch)


def chime_lines():
    snd, vol, pitches = CHIME
    return ["execute at @s run playsound %s player @s ~ ~ ~ %.2f %.3f" % (snd, vol, p)
            for p in pitches]


# ---------- 到站的畫面 ----------

def _station_en(net, ref, name):
    st = net.get((ref, name))
    return st.en if st is not None else name


def _terminals(net, ref, dr):
    """這個方向的終點站：("南港展覽館", "Nangang Exhibition Center")。"""
    zh = "／".join(dr.terminals)
    en = " / ".join(_station_en(net, ref, t) for t in dr.terminals)
    return zh, en


def arrival_lines(net, st, slot, colours):
    """到站：大標題站名、副標題站號與路線、動作列下一站。"""
    ref = st.ref
    c = colours.get(ref, "#FFFFFF")
    lz, le = line_name(ref)
    out = [
        "title @s times 5 50 15",
        "title @s subtitle " + text([
            {"text": st.code + " ", "color": c, "bold": True},
            {"text": "%s · %s %s" % (st.en, lz, le), "color": "white"}]),
        "title @s title " + text({"text": st.name, "color": c, "bold": True}),
    ]
    dr = slot.dest if slot is not None else None
    if dr is not None:
        tz_, te = _terminals(net, ref, dr)
        out.append("title @s actionbar " + text([
            {"text": "下一站 Next ", "color": "gray"},
            {"text": "%s %s" % (dr.next, _station_en(net, ref, dr.next)), "color": "white"},
            {"text": "　往 To %s %s" % (tz_, te), "color": "gray"}]))
    else:
        out.append("title @s actionbar " + text([
            {"text": "本站為終點站 Terminal station", "color": "yellow"},
            {"text": "　點月台上的告示牌換到對面月台 Click a sign to cross over", "color": "gray"}]))
    return out


def _fn_header(desc):
    return ["# " + desc, "# 自動產生（mrt/application/ride_plan.py），請改產生器、別手改"]


# ---------- 各種函式 ----------

def _ride_targets(net, berths):
    """{(路線, 起站名, 迄站名): (起站, 迄站, 下車 Slot)}。

    以 NW.rides 為準；月台上每一面牌指向的車程都得有函式，arrival 萬一找不到
    下車位置（那一側的牌全被地標擋掉）就退回迄站的 home_slot，免得點了
    「Unknown function」。
    """
    bidx = NW.berth_index(berths)
    got = {}
    for ref, st, to, slot, _dr in NW.rides(net, berths):
        got[(ref, st.name, to.name)] = (st, to, slot)
    for b in berths:
        for s in b.slots:
            if s.dest is None:
                continue
            key = (b.line, b.station.name, s.dest.next)
            to = net.get((b.line, s.dest.next))
            if key in got or to is None:
                continue
            slot = NW.home_slot(bidx, to)
            if slot is not None:
                got[key] = (b.station, to, slot)
    return got


def _turn_targets(berths):
    """[(Berth, 目的 Slot)]：終點站到站側（沒有下一站）的每個月台邊。"""
    bidx = NW.berth_index(berths)
    out = []
    for b in berths:
        if b.dests or not b.slots:
            continue
        opp = bidx.get((b.line, b.station.name, -b.d))
        if opp is not None and opp.slots and opp.dests:
            slot = opp.primary()
        else:
            slot = NW.home_slot(bidx, b.station)
        if slot is not None:
            out.append((b, slot))
    return out


def _stations_by_line(net, berths):
    """{路線: [Station]}，站號自然排序，只收有 home_slot 的（go 函式傳得過去的）。"""
    bidx = NW.berth_index(berths)
    out = {}
    for st in net.values():
        if st.box is None or NW.home_slot(bidx, st) is None:
            continue
        out.setdefault(st.ref, []).append(st)
    for ref in out:
        out[ref].sort(key=lambda s: NW.code_sort_key(s.code))
    return out


def _codes_by_name(net):
    """{站名: [(路線, 站號)]}：轉乘站在每條線上的站號（顯示用）。"""
    out = {}
    for st in net.values():
        if st.box is not None:
            out.setdefault(st.name, []).append((st.ref, st.code))
    order = {r: i for i, r in enumerate(line_order({r for v in out.values() for r, _ in v}))}
    for k in out:
        out[k].sort(key=lambda rc: (order[rc[0]], NW.code_sort_key(rc[1])))
    return out


# ---------- 進站提示（HUD）----------

AREA_HALF = AL.BOX_HALF + 1      # 站體半寬再多一格


def station_area(box):
    """站體的軸向外接盒 (x0, y0, z0, dx, dy, dz)，給 @a[x=,y=,z=,dx=,dy=,dz=] 用。

    水平：月台兩端（lo、hi）各往兩側 BOX_HALF+1 格的四個角。
    垂直（腳的高度）：地下站從月台（疊式站是下層月台）到穿堂（軌面 +7）；
    高架／平面站的穿堂可能在橋下（軌面 −6）或月台上方（軌面 +8），兩種都涵蓋。
    斜 45 度的站外接盒會比站體大一圈，進站提示早一點亮而已。
    """
    xs, zs = [], []
    for i in (box.lo, box.hi):
        for off in (-AREA_HALF, AREA_HALF):
            x, z = box.cell(i, off)
            xs.append(x)
            zs.append(z)
    ys = [int(box.ys[i]) for i in range(box.lo, box.hi + 1)]
    y_lo, y_hi = min(ys), max(ys)
    if box.kind == "side":
        y0 = y_lo + AL.LEVEL_DY["under"] - 1
        y1 = y_hi + AL.LEVEL_DY["over"] + 1
    else:
        y0 = y_lo + 1 - (SK.LEVEL_H if box.kind.startswith("stacked") else 0)
        y1 = y_hi + AL.LEVEL_DY["tunnel"] + 1
    x0, z0 = min(xs), min(zs)
    return x0, y0, z0, max(xs) - x0, y1 - y0, max(zs) - z0


def hud_text(name, en, codes, colours):
    """動作列：站號（各自的線色）＋站名＋英文站名。"""
    parts = []
    for ref, code in codes:
        parts.append({"text": "▌", "color": colours.get(ref, "#FFFFFF")})
        parts.append({"text": code + " ", "color": colours.get(ref, "#FFFFFF"), "bold": True})
    one = len({r for r, _ in codes}) == 1
    parts.append({"text": " " + name, "color": colours.get(codes[0][0], "#FFFFFF") if one else "white",
                  "bold": True})
    parts.append({"text": "  " + en, "color": "gray"})
    return parts


# ---------- 對話框 ----------

def _line_dialog(ref, stations, trig, codes_by_name, colours, near_sights=None):
    c = colours.get(ref, "#FFFFFF")
    lz, le = line_name(ref)
    actions = []
    for st in stations:
        xfer = [rc for rc in codes_by_name.get(st.name, ()) if rc[0] != ref]
        tip = [{"text": st.en}]
        if xfer:
            tip.append({"text": "\n轉乘 Transfer: ", "color": "gray"})
            for k, (r, code) in enumerate(xfer):
                tip.append({"text": ("、" if k else "") + code + " " + line_name(r)[0],
                            "color": colours.get(r, "#FFFFFF")})
        near = (near_sights or {}).get(st.name)
        if near:
            tip.append({"text": "\n★ 附近景點 Nearby: ", "color": SIGHT_COLOR})
            tip.append({"text": "、".join(near), "color": "white"})
        actions.append({
            "label": [{"text": st.code + " ", "color": c, "bold": True},
                      {"text": st.name, "color": "white"}],
            "tooltip": tip,
            "width": 130,
            "action": {"type": "minecraft:run_command",
                       "command": "trigger %s set %d" % (OBJ_GO, trig[(st.ref, st.name)])},
        })
    return {
        "type": "minecraft:multi_action",
        "title": [{"text": "▌", "color": c}, {"text": "%s %s" % (lz, le), "color": c, "bold": True}],
        "external_title": [{"text": "▌", "color": c}, {"text": "%s %s" % (lz, le)}],
        "body": [{"type": "minecraft:plain_message", "width": 400, "contents": [
            {"text": "點站名就傳送到那一站的月台（面向往下一站的告示牌）\n", "color": "white"},
            {"text": "Click a station to teleport to its platform.", "color": "gray"}]}],
        "columns": 3,
        "actions": actions,
        "exit_action": {"label": {"text": "← 返回路線圖 Back"}, "width": 200,
                        "action": {"type": "minecraft:show_dialog", "dialog": fid(NW.MENU_DIALOG)}},
    }


def _menu_dialog(refs, by_line, colours, n_sights=0):
    actions = []
    for ref in refs:
        c = colours.get(ref, "#FFFFFF")
        lz, le = line_name(ref)
        sts = by_line[ref]
        actions.append({
            "label": [{"text": "▌", "color": c}, {"text": lz + " ", "color": c, "bold": True},
                      {"text": le, "color": "white"}],
            "tooltip": [{"text": "%d 站 stations\n" % len(sts)},
                        {"text": "%s %s ↔ %s %s" % (sts[0].code, sts[0].name, sts[-1].code, sts[-1].name),
                         "color": "gray"}],
            "width": 200,
            "action": {"type": "minecraft:show_dialog", "dialog": fid(NW.line_dialog(ref))},
        })
    if n_sights:
        actions.append({
            "label": [{"text": "★ ", "color": SIGHT_COLOR}, {"text": "觀光景點 ", "color": SIGHT_COLOR, "bold": True},
                      {"text": "Attractions", "color": "white"}],
            "tooltip": [{"text": "%d 處景點：台北101、中正紀念堂、總統府……\n" % n_sights},
                        {"text": "傳送到景點前的觀景點 Teleport to a viewpoint", "color": "gray"}],
            "width": 200,
            "action": {"type": "minecraft:show_dialog", "dialog": fid(SIGHTS_DIALOG)},
        })
    return {
        "type": "minecraft:multi_action",
        "title": {"text": "台北捷運路線圖 Taipei Metro Route Map", "bold": True},
        "external_title": {"text": MENU_TITLE + " Route Map"},
        "body": [{"type": "minecraft:plain_message", "width": 400, "contents": [
            {"text": "選一條路線，再點站名就傳送到那一站的月台。\n", "color": "white"},
            {"text": "Pick a line, then a station to teleport there.\n\n", "color": "gray"},
            {"text": "在月台上右鍵點告示牌，就能坐到下一站。\n", "color": "white"},
            {"text": "Right-click a platform sign to ride to the next station.\n\n", "color": "gray"},
            {"text": ATTRIBUTION, "color": "dark_gray"}]}],
        "columns": 2,
        "actions": actions,
        "exit_action": {"label": {"text": "關閉 Close"}, "width": 200},
    }


# ---------- 觀光景點 ----------

SIGHT_COLOR = "#E0B040"      # 景點按鈕與標題的顏色（金色，跟各線的線色分開）
SIGHTS_DIALOG = "sights"     # 景點清單對話框（mrt:sights）


def sight_tp_line(sp):
    """景點傳送點的那一行（同 tp_line 的格式）：sp 是 attractions.Spot 的 dict。"""
    return "tp @s %.1f %d %.1f %.1f %.1f" % (sp["x"] + 0.5, sp["y"], sp["z"] + 0.5, sp["yaw"], sp["pitch"])


def sight_arrival_lines(e, sp):
    """到了景點：大標題景點名（或觀景台的名字）、副標題英文名、動作列一句事實與最近的站。"""
    main = not sp["key"]
    title = e["name_zh"] if main else sp["zh"]
    sub = e["name_en"] if main else sp["en"]
    bar = [{"text": " · ".join(e["facts"]) + ("　" if e["facts"] else ""), "color": "white"}]
    st = e.get("station")
    if st and main:
        bar.append({"text": "最近的捷運站 Nearest MRT: %s %s（%d m）" % (st[0], st[3], st[2]), "color": "gray"})
    return [
        "title @s times 5 60 20",
        "title @s subtitle " + text({"text": sub, "color": "white"}),
        "title @s title " + text({"text": title, "color": SIGHT_COLOR, "bold": True}),
        "title @s actionbar " + text(bar),
        "execute at @s run playsound minecraft:block.note_block.bell player @s ~ ~ ~ 0.7 1.0",
    ]


def _sight_dialog(entries, trig):
    actions = []
    for e in entries:
        st = e.get("station")
        tip = [{"text": e["name_en"]}]
        if e["facts"]:
            tip.append({"text": "\n" + " · ".join(e["facts"]), "color": "white"})
        if st:
            tip.append({"text": "\n最近的捷運站 %s（%d m）\nNearest MRT: %s" % (st[0], st[2], st[3]),
                        "color": "gray"})
        actions.append({
            "label": [{"text": "★ ", "color": SIGHT_COLOR}, {"text": e["name_zh"], "color": "white"}],
            "tooltip": tip,
            "width": 200,
            "action": {"type": "minecraft:run_command",
                       "command": "trigger %s set %d" % (OBJ_GO, trig[e["id"]])},
        })
    return {
        "type": "minecraft:multi_action",
        "title": [{"text": "★ ", "color": SIGHT_COLOR},
                  {"text": "觀光景點 Attractions", "color": SIGHT_COLOR, "bold": True}],
        "external_title": {"text": "觀光景點 Attractions"},
        "body": [{"type": "minecraft:plain_message", "width": 400, "contents": [
            {"text": "點景點就傳送到它前面的觀景點。建築的位置、方位與輪廓來自 OpenStreetMap。\n",
             "color": "white"},
            {"text": "Click to teleport to a viewpoint in front of the attraction.", "color": "gray"}]}],
        "columns": 2,
        "actions": actions,
        "exit_action": {"label": {"text": "← 返回路線圖 Back"}, "width": 200,
                        "action": {"type": "minecraft:show_dialog", "dialog": fid(NW.MENU_DIALOG)}},
    }


# ---------- 系統函式 ----------

def _setup_fns():
    """世界初始設定（只做一次）與設定通知。"""
    setup = _fn_header("世界初始設定：第一次載入才做（#setup 記版本），/reload 不會蓋掉玩家之後的調整")
    for rule, val, _default, _desc in GAME_RULES:
        setup.append("gamerule %s %s" % (rule, val))
    setup += [
        "time set %d" % NOON,
        "weather clear",
        "scoreboard players set #setup %s %d" % (OBJ_STATE, SETUP_VERSION),
        "scoreboard players set #notice %s 1" % OBJ_STATE,
        # 伺服器主控台看得到（開世界的當下通常還沒有玩家在線上）
        "say [台北捷運] 已套用世界初始設定：" + "、".join(
            "%s=%s" % (r, v) for r, v, _, _ in GAME_RULES)
        + "；時間定在中午、天氣晴。還原：/gamerule <規則> <原值>",
        # /reload 升版時玩家已經在線上：當場通知，不必等下一個新玩家
        "execute as @a run function %s" % fid("sys/notice"),
    ]
    notice = _fn_header("通知玩家世界初始設定改了哪些規則、怎麼還原（點指令會填進聊天欄）")
    msg = [{"text": "[台北捷運] 已套用世界初始設定 World settings applied\n", "color": "gold", "bold": True}]
    for rule, val, default, desc in GAME_RULES:
        cmd = "/gamerule %s %s" % (rule, default)
        msg.append({"text": " · %s（%s = %s）" % (desc, rule, val), "color": "white"})
        msg.append({"text": "  還原 " + cmd + "\n", "color": "gray",
                    "click_event": {"action": "suggest_command", "command": cmd},
                    "hover_event": {"action": "show_text", "value": "點一下填入聊天欄 Click to fill in"}})
    msg.append({"text": " · 時間定在中午、天氣晴（time set %d、weather clear）" % NOON, "color": "white"})
    notice += ["tellraw @s " + text(msg), "scoreboard players set #notice %s 0" % OBJ_STATE]
    return setup, notice


def _welcome_line(home, n_lines, n_stations):
    return [
        {"text": "\n歡迎來到 1:1 台北捷運！ Welcome to the 1:1 Taipei Metro!\n", "color": "gold", "bold": True},
        {"text": "整個路網照 OpenStreetMap 資料等比例重建：%d 條路線、%d 站，" % (n_lines, n_stations)
                 + "隧道、高架、車站與出入口都在真實位置。\n", "color": "white"},
        {"text": "The whole network, rebuilt at real scale from OpenStreetMap data.\n\n", "color": "gray"},
        {"text": "▶ 右鍵點月台上的告示牌就能坐到下一站（連點就連坐好幾站）\n", "color": "white"},
        {"text": "   Right-click a platform sign to ride to the next station.\n", "color": "gray"},
        # 暫停選單：#minecraft:pause_screen_additions 只有一個對話框時，遊戲直接用它的
        # external_title 當按鈕（PauseScreen.getCustomAdditions）；多於一個才收進「自訂選項...」
        {"text": "▶ 路線圖：按「快速動作」鍵（預設 G）、暫停選單裡的「%s」，或輸入 /trigger %s\n"
                 % (MENU_TITLE, OBJ_MENU), "color": "white"},
        {"text": "   Route map: Quick Actions key (G), the Route Map button in the pause menu, or /trigger %s\n"
                 % OBJ_MENU, "color": "gray"},
        {"text": "[ 打開路線圖 Open route map ]", "color": "aqua", "bold": True,
         "click_event": {"action": "show_dialog", "dialog": fid(NW.MENU_DIALOG)},
         "hover_event": {"action": "show_text", "value": "點一下打開路線圖 Click to open"}},
        {"text": "\n你現在在 %s %s 的月台。 You are on the platform at %s.\n" % (home.code, home.name, home.en),
         "color": "white"},
        {"text": ATTRIBUTION, "color": "dark_gray"},
    ]


# ---------- 組起來 ----------

def _areas(net):
    """({站名: 車站編號}, [(x0, y0, z0, dx, dy, dz, 車站編號)])。

    每座站體一個範圍；同名車站（轉乘站的幾座站體）共用一個編號，在轉乘通道
    走來走去不會一直重播站名。共用疊式站（西門）兩條線是同一座站體，只算一次。
    """
    group, areas, seen = {}, [], set()
    built = [s for s in net.values() if s.box is not None]
    rank = {r: i for i, r in enumerate(line_order({s.ref for s in built}))}
    for st in sorted(built, key=lambda s: (rank[s.ref], NW.code_sort_key(s.code))):
        g = group.setdefault(st.name, len(group) + 1)
        if id(st.box) in seen:
            continue
        seen.add(id(st.box))
        areas.append(station_area(st.box) + (g,))
    return group, areas


def build_spec(net, berths, colours, sights=None):
    """整份資料包規格（純資料）：

    functions     {路徑: [指令行]}             路徑不含命名空間，如 "ride/bl12_bl13"
    dialogs       {路徑: 對話框 dict}
    tags          {"function": {標籤 id: [函式 id]}, "dialog": {標籤 id: [對話框 id]}}
    description   pack.mcmeta 的說明（文字元件）
    triggers      {n: go／sight 函式路徑}       路線圖與景點清單按鈕的 trigger 值（1..N，連續不重複）
    areas         [(x0, y0, z0, dx, dy, dz, 車站編號)]  進站提示的範圍
    home          首次進入呼叫的 go 函式路徑
    warnings      [str]                        id 撞名之類的問題（有就該查）
    sights        [景點 dict]                   attractions.datapack_entries() 的結果（輸入也是它）
    """
    sights = list(sights or [])
    bidx = NW.berth_index(berths)
    fns, warnings = {}, []
    group, areas = _areas(net)
    codes_by_name = _codes_by_name(net)

    def put(path, lines):
        if path in fns:
            warnings.append("函式 id 撞名，保留第一個：" + path)
            return
        fns[path] = lines

    def landed(st):
        """傳送之後：先把「上一次所在的車站」記成目的地，進站提示就不會蓋掉
        到站畫面的動作列（大標題已經講過站名了）。"""
        return ["scoreboard players set @s %s %d" % (OBJ_AREA, group[st.name])]

    # ride/*
    for (ref, _a, _b), (st, to, slot) in sorted(
            _ride_targets(net, berths).items(),
            key=lambda kv: (NW.code_sort_key(kv[1][0].code), NW.code_sort_key(kv[1][1].code))):
        lz, le = line_name(ref)
        put(NW.ride_fn(st.code, to.code),
            _fn_header("%s %s %s → %s %s" % (lz, st.code, st.name, to.code, to.name))
            + [tp_line(slot)] + landed(to) + chime_lines() + arrival_lines(net, to, slot, colours))

    # turn/*
    for b, slot in _turn_targets(berths):
        st = b.station
        c = colours.get(st.ref, "#FFFFFF")
        dr = slot.dest
        if dr is not None:
            tz_, te = _terminals(net, st.ref, dr)
            title = [{"text": "往 " + tz_, "color": c, "bold": True}]
            sub = [{"text": "To " + te, "color": "white"}]
        else:
            title = [{"text": st.name, "color": c, "bold": True}]
            sub = [{"text": st.en, "color": "white"}]
        put(NW.turn_fn(st.code, b.d),
            _fn_header("%s %s 終點站：換到對面月台" % (st.code, st.name))
            + [tp_line(slot)] + landed(st) + chime_lines()
            + ["title @s times 5 40 15",
               "title @s subtitle " + text(sub),
               "title @s title " + text(title),
               "title @s actionbar " + text([
                   {"text": "本站終點，已換到對面月台 ", "color": "yellow"},
                   {"text": "Terminus — you crossed to the other platform", "color": "gray"}])])

    # go/*
    by_line = _stations_by_line(net, berths)
    refs = line_order(by_line)
    for ref in refs:
        for st in by_line[ref]:
            slot = NW.home_slot(bidx, st)
            put(NW.go_fn(st.code),
                _fn_header("傳送到 %s %s（%s）" % (st.code, st.name, line_name(ref)[0]))
                + [tp_line(slot)] + landed(st) + chime_lines() + arrival_lines(net, st, slot, colours))

    # 路線圖按鈕的 trigger 值：路線順序 × 站號順序，1..N
    trig, triggers = {}, {}
    for ref in refs:
        for st in by_line[ref]:
            n = len(trig) + 1
            trig[(st.ref, st.name)] = n
            triggers[n] = NW.go_fn(st.code)

    # sight/*：每座景點每個傳送點一個函式；預設觀景點排在站名按鈕之後編 trigger 值
    sight_trig = {}
    for e in sights:
        for sp in e["spots"]:
            put(sight_fn(e["id"], sp["key"]),
                _fn_header("景點 %s %s%s" % (e["name_zh"], e["name_en"], ("：" + sp["zh"]) if sp["key"] else ""))
                + [sight_tp_line(sp), "scoreboard players set @s %s 0" % OBJ_AREA]
                + sight_arrival_lines(e, sp))
        n = len(trig) + len(sight_trig) + 1
        sight_trig[e["id"]] = n
        triggers[n] = sight_fn(e["id"])

    near_sights = {}                 # 站名 -> [走得到的景點中文名]（站表按鈕的提示）
    for e in sights:
        st = e.get("station")
        if st:
            near_sights.setdefault(st[0], []).append(e["name_zh"])
    dialogs = {NW.MENU_DIALOG: _menu_dialog(refs, by_line, colours, n_sights=len(sights))}
    if sights:
        dialogs[SIGHTS_DIALOG] = _sight_dialog(sights, sight_trig)
    for ref in refs:
        dialogs[NW.line_dialog(ref)] = _line_dialog(ref, by_line[ref], trig, codes_by_name, colours,
                                                    near_sights)

    # 首次進入的落腳處
    home = net.get(HOME)
    if home is None or home.box is None or NW.home_slot(bidx, home) is None:
        home = by_line[refs[0]][0] if refs else None
        warnings.append("找不到 %s %s，首次進入改傳到 %s" % (HOME[0], HOME[1], home.code if home else "（無）"))

    setup, notice = _setup_fns()
    fns["sys/setup"] = setup
    fns["sys/notice"] = notice

    fns["sys/load"] = _fn_header("#minecraft:load：每次載入與 /reload 都會跑") + [
        "scoreboard objectives add %s dummy" % OBJ_STATE,
        "scoreboard objectives add %s trigger %s" % (OBJ_GO, text({"text": "捷運傳送 MRT teleport"})),
        "scoreboard objectives add %s trigger %s" % (OBJ_MENU, text({"text": "捷運路線圖 MRT map"})),
        "scoreboard objectives add %s dummy" % OBJ_AREA,
        "scoreboard objectives add %s dummy" % OBJ_HERE,
        "execute unless score #setup %s matches %d.. run function %s" % (OBJ_STATE, SETUP_VERSION, fid("sys/setup")),
        "schedule function %s %dt replace" % (fid("sys/hud"), HUD_EVERY),
    ]
    fns["sys/tick"] = _fn_header("#minecraft:tick：只放便宜的選擇器，重活在 sys/hud（每 %d tick）" % HUD_EVERY) + [
        "execute as @a[tag=!%s] run function %s" % (TAG_JOINED, fid("sys/join")),
        "execute as @a[scores={%s=1..}] run function %s" % (OBJ_GO, fid("sys/go")),
        "execute as @a[scores={%s=1..}] run function %s" % (OBJ_MENU, fid("sys/menu")),
    ]
    join = _fn_header("首次進入：傳送到 %s %s 的月台、歡迎訊息" % (home.code, home.name) if home else "首次進入")
    join += ["tag @s add " + TAG_JOINED,
             "scoreboard players enable @s " + OBJ_GO,
             "scoreboard players enable @s " + OBJ_MENU]
    if home is not None:
        n_st = sum(1 for s in net.values() if s.box is not None)
        join.append("function " + fid(NW.go_fn(home.code)))
        join.append("tellraw @s " + text(_welcome_line(home, len(refs), n_st)))
    join.append("execute if score #notice %s matches 1 run function %s" % (OBJ_STATE, fid("sys/notice")))
    fns["sys/join"] = join

    fns["sys/go"] = _fn_header("/trigger %s set <n>：路線圖的站名按鈕" % OBJ_GO) + [
        "function " + fid("sys/go_dispatch"),
        "scoreboard players set @s %s 0" % OBJ_GO,
        "scoreboard players enable @s " + OBJ_GO,
    ]
    fns["sys/go_dispatch"] = _fn_header("trigger 值 -> go 函式（值由 ride_plan.build_spec 依路線、站號順序編）") + [
        "execute if score @s %s matches %d run return run function %s" % (OBJ_GO, n, fid(path))
        for n, path in sorted(triggers.items())
    ] + ["tellraw @s " + text({"text": "[台北捷運] 沒有這個站的編號 Unknown station number", "color": "red"})]
    fns["sys/menu"] = _fn_header("/trigger %s：打開路線圖" % OBJ_MENU) + [
        "dialog show @s " + fid(NW.MENU_DIALOG),
        "scoreboard players set @s %s 0" % OBJ_MENU,
        "scoreboard players enable @s " + OBJ_MENU,
    ]

    # 進站提示：每 HUD_EVERY tick 掃一次所有站體範圍
    names = {g: n for n, g in group.items()}
    en_of = {}
    for st in net.values():
        en_of.setdefault(st.name, st.en)
    fns["sys/hud"] = _fn_header("進站提示：每 %d tick 掃一次，玩家進到車站範圍時動作列亮一次站名" % HUD_EVERY) + [
        "schedule function %s %dt replace" % (fid("sys/hud"), HUD_EVERY),
        "scoreboard players add #beat %s 1" % OBJ_STATE,
        "execute unless entity @a run return 0",
        "scoreboard players enable @a " + OBJ_GO,
        "scoreboard players enable @a " + OBJ_MENU,
        "scoreboard players set @a %s 0" % OBJ_HERE,
    ] + [
        "execute as @a[x=%d,y=%d,z=%d,dx=%d,dy=%d,dz=%d] run scoreboard players set @s %s %d"
        % (x0, y0, z0, dx, dy, dz, OBJ_HERE, g) for x0, y0, z0, dx, dy, dz, g in areas
    ] + [
        "execute as @a unless score @s %s = @s %s run function %s" % (OBJ_HERE, OBJ_AREA, fid("sys/hud_enter")),
    ]
    fns["sys/hud_enter"] = _fn_header("換了範圍：記下來，進到車站就亮站名（離開車站只記不亮）") + [
        "scoreboard players operation @s %s = @s %s" % (OBJ_AREA, OBJ_HERE),
    ] + [
        "execute if score @s %s matches %d run return run title @s actionbar %s"
        % (OBJ_HERE, g, text(hud_text(names[g], en_of[names[g]], codes_by_name[names[g]], colours)))
        for g in sorted(names)
    ]

    return {
        "description": [{"text": "台北捷運 1:1 搭乘系統", "color": "gold"},
                        {"text": "\nTaipei MRT ride system · © OpenStreetMap contributors", "color": "gray"}],
        "functions": fns,
        "dialogs": dialogs,
        "tags": {
            "function": {"minecraft:load": [fid("sys/load")], "minecraft:tick": [fid("sys/tick")]},
            "dialog": {"minecraft:quick_actions": [fid(NW.MENU_DIALOG)],
                       "minecraft:pause_screen_additions": [fid(NW.MENU_DIALOG)]},
        },
        "triggers": triggers,
        "areas": areas,
        "home": NW.go_fn(home.code) if home is not None else None,
        "sights": {e["id"]: [sight_fn(e["id"], sp["key"]) for sp in e["spots"]] for e in sights},
        "warnings": warnings,
    }
