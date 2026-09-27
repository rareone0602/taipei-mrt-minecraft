#!/usr/bin/env python3
"""讀回存檔裡的搭乘系統資料包，再交給真的 Minecraft 26.2 載入、執行一遍。

生成器說它寫了 593 個函式，不算數。這支工具分兩段：

一、從磁碟讀回（不需要遊戲）
  · pack.mcmeta 讀得懂、level.dat 的 DataPacks.Enabled 有列這個資料包
  · 每個 ride/*、turn/*、go/*、sight/* 恰好一行 ``tp @s x y z yaw pitch``（約定，見
    application/ride_plan.py），座標是數字
  · 函式裡提到的每個 ``function mrt:…``、對話框裡的每個 ``show_dialog``、
    兩個標籤裡的每個 id 都真的有檔案
  · 各線站表的按鈕：trigger 值 1..N 連續不重複，按鈕上的站號有對應的 go 函式
  · 存檔裡的告示牌（各站體附近）：點擊指令指向的函式與對話框都存在
  · 每個傳送落點（有蓋出來的範圍內）站得住（domain/walk 的規則），
    面向的方向 1～3 格內有告示牌

二、叫遊戲自己來（遊戲 jar 附的 GameTest 伺服器，無頭、不開連接埠）
  另外產生一個一次性的測試資料包 mrt_selftest（測試環境的 setup／teardown
  函式），跟 taipei_mrt 一起丟給 ``net.minecraft.gametest.Main``：
  · 伺服器載入兩個資料包時沒有任何函式／標籤／對話框的載入錯誤
  · 開服時 #minecraft:load 真的跑了：世界初始設定的九條規則、時間定在中午；
    再跑一次 sys/load（等於 /reload）不會蓋掉之後改過的規則
  · 每一個 ride/turn/go/sight 函式都在遊戲裡執行一次（召喚一個 marker 當 @s），
    執行完讀它的 Pos 與 Rotation，要跟函式檔裡那行 tp 一致
  · 各線站表的每一顆按鈕：把按鈕的 trigger 值設給 marker、跑 sys/go，
    marker 要落在「按鈕上那個站號」的 go 函式的位置 —— 按鈕、分派表、go 函式
    三者各自獨立產生，這樣才驗得到它們對得起來
  · 首次進入（sys/join）：上標籤、傳到 R10 台北車站
  · 進站提示：sys/hud 的範圍掃描原樣複製、只把 @a 換成 @s，每個傳送落點都要
    判到那一站、hud_enter 要跑過；它的 schedule 迴圈在 advance_time=false 之下
    還在跳（心跳記分）
  · 告示牌：把存檔裡搭車告示牌的方塊實體原封不動 setblock 回遊戲（存檔裡
    還沒有就用 World.sign 產生一面），讀回來 click_event 還在；每個對話框都
    做一面 show_dialog 的牌 —— 對話框 id 不存在的話遊戲解不開那段文字，
    所以牌子留得住 click_event 就代表對話框真的註冊了
  · 反向對照（驗證器自己也會騙人）：一個故意寫壞的函式，log 裡一定要看到
    它的載入錯誤；一面指向不存在對話框的牌，一定要留不住 click_event；
    沒傳送的 marker 不能被判成落點正確；沒有這個編號的按鈕值不能傳走人；
    高空中的 marker 不能被判成在任何一站

證明不了的：玩家真的右鍵點牌（GameTest 裡沒有玩家）、對話框畫面長什麼樣、
客戶端送出 /trigger 會不會跳確認視窗。這些要開真的遊戲看。

用法:
    ./.venv/bin/python tools/check_datapack.py <存檔> [--no-game] [--no-signs] [--keep 目錄]
"""
import argparse
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import nbtlib

from mrt import config

NS = config.DATAPACK_NS
TEST_NS = "mrt_selftest"
TP_RE = re.compile(r"^tp @s (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?) "
                   r"(-?\d+(?:\.\d+)?) (-?\d+(?:\.\d+)?)$")
FN_REF_RE = re.compile(r"\bfunction (%s:[a-z0-9_./-]+)" % NS)
DIALOG_REF_RE = re.compile(r'"dialog":"(%s:[a-z0-9_./-]+)"|dialog show \S+ (%s:[a-z0-9_./-]+)' % (NS, NS))
TRIG_RE = re.compile(r"^trigger (\S+) set (\d+)$")

MC_DIR = os.path.expanduser("~/Library/Application Support/minecraft")
VERSION = "26.2"


# ====================================================================== 讀回資料包

class Pack:
    def __init__(self, root):
        self.root = root
        self.mcmeta = json.load(open(os.path.join(root, "pack.mcmeta"), encoding="utf-8"))
        self.functions, self.dialogs, self.tags = {}, {}, {}
        data = os.path.join(root, "data")
        fdir = os.path.join(data, NS, "function")
        for fp in glob.glob(os.path.join(fdir, "**", "*.mcfunction"), recursive=True):
            path = os.path.relpath(fp, fdir)[:-len(".mcfunction")].replace(os.sep, "/")
            self.functions[path] = open(fp, encoding="utf-8").read().splitlines()
        ddir = os.path.join(data, NS, "dialog")
        for fp in glob.glob(os.path.join(ddir, "**", "*.json"), recursive=True):
            path = os.path.relpath(fp, ddir)[:-len(".json")].replace(os.sep, "/")
            self.dialogs[path] = json.load(open(fp, encoding="utf-8"))
        for fp in glob.glob(os.path.join(data, "*", "tags", "*", "**", "*.json"), recursive=True):
            rel = os.path.relpath(fp, data).split(os.sep)
            tns, kind, tpath = rel[0], rel[2], "/".join(rel[3:])[:-len(".json")]
            self.tags[(kind, "%s:%s" % (tns, tpath))] = json.load(open(fp, encoding="utf-8"))["values"]

    def tp(self, path):
        """函式裡約定的那一行 tp：(x, y, z, yaw, pitch)；不是恰好一行就 None。"""
        hits = [TP_RE.match(ln) for ln in self.functions.get(path, ()) if ln.startswith("tp ")]
        if len(hits) != 1 or hits[0] is None:
            return None
        return tuple(float(g) for g in hits[0].groups())


def line_buttons(pack):
    """[(對話框路徑, 按鈕上的站號, trigger 物件, trigger 值)]"""
    out = []
    for path, d in sorted(pack.dialogs.items()):
        if not path.startswith("line/"):
            continue
        for a in d.get("actions", ()):
            lab = a.get("label")
            code = (lab[0]["text"] if isinstance(lab, list) else lab.get("text", "")).strip()
            m = TRIG_RE.match(a.get("action", {}).get("command", ""))
            out.append((path, code, m.group(1) if m else None, int(m.group(2)) if m else None))
    return out


SIGHT_NAME_RE = re.compile(r"^# 景點 (\S+)")
TP_KINDS = ("ride", "turn", "go", "sight")


def sight_buttons(pack):
    """景點清單的按鈕：[(景點中文名, trigger 物件, trigger 值, 對應的 sight 函式)]。

    按鈕上只有名字；函式靠 sight/<id> 檔頭那行「# 景點 <中文名> ...」對回來 ——
    對話框與函式是 ride_plan 各自產生的，對得起來才代表按鈕會送人到那座景點。"""
    by_name = {}
    for path, lines in pack.functions.items():
        if path.startswith("sight/") and lines:
            m = SIGHT_NAME_RE.match(lines[0])
            if m and "：" not in lines[0]:
                by_name[m.group(1)] = path
    out = []
    d = pack.dialogs.get("sights")
    for a in (d or {}).get("actions", ()):
        lab = a.get("label")
        name = (lab[-1]["text"] if isinstance(lab, list) else lab.get("text", "")).strip()
        m = TRIG_RE.match(a.get("action", {}).get("command", ""))
        out.append((name, m.group(1) if m else None, int(m.group(2)) if m else None, by_name.get(name)))
    return out


def fn_code(code):
    return "".join(ch for ch in code.lower() if ch.isalnum() or ch == "_")


def game_data_version(mc_dir, version):
    """遊戲 jar 裡 version.json 的資料包版本 (主, 次)；找不到 jar 就 None。"""
    import zipfile
    jar = os.path.join(mc_dir, "versions", version, version + ".jar")
    if not os.path.exists(jar):
        return None
    with zipfile.ZipFile(jar) as z:
        pv = json.loads(z.read("version.json"))["pack_version"]
    return pv["data_major"], pv["data_minor"]


def format_range(fmt):
    """pack.mcmeta 的 min_format／max_format -> ((主, 次), (主, 次))。

    規則照遊戲的 PackFormat：寫成整數時，下限是 (n, 0)、上限是 (n, 任意次版本)。
    """
    def one(v, top):
        if isinstance(v, int):
            return (v, 1 << 31) if top else (v, 0)
        return (int(v[0]), int(v[1]) if len(v) > 1 else (1 << 31 if top else 0))
    return one(fmt["min_format"], False), one(fmt["max_format"], True)


def static_checks(save, pack, problems, say, game_version=None):
    """第一段：從磁碟讀回的檢查。problems 收問題字串。

    game_version 是遊戲的資料包版本 (主, 次)：GameTest 伺服器對版本範圍不符的資料包
    照樣載入、一聲不吭（實測過），所以範圍對不對只能在這裡拿 version.json 比。
    """
    fmt = pack.mcmeta.get("pack", {})
    say(f"pack.mcmeta：min_format={fmt.get('min_format')} max_format={fmt.get('max_format')}")
    if "min_format" not in fmt or "max_format" not in fmt:
        problems.append("pack.mcmeta 缺 min_format／max_format（26.2 用這兩個欄位）")
    elif game_version is not None:
        lo, hi = format_range(fmt)
        if lo <= tuple(game_version) <= hi:
            say(f"  遊戲的資料包版本 {game_version[0]}.{game_version[1]}（jar 裡的 version.json）落在範圍內")
        else:
            problems.append(f"pack.mcmeta 的範圍 {fmt['min_format']}～{fmt['max_format']} 不含遊戲的資料包版本 "
                            f"{game_version[0]}.{game_version[1]}")

    lvl = nbtlib.load(os.path.join(save, "level.dat"))
    enabled = [str(s) for s in lvl["Data"]["DataPacks"]["Enabled"]]
    want = "file/" + os.path.basename(pack.root)
    say(f"level.dat DataPacks.Enabled = {enabled}")
    if want not in enabled:
        problems.append(f"level.dat 的 DataPacks.Enabled 沒有 {want}")

    kinds = {k: 0 for k in TP_KINDS}
    for path in sorted(pack.functions):
        top = path.split("/")[0]
        if top in kinds:
            kinds[top] += 1
            n_tp = sum(1 for ln in pack.functions[path] if ln.startswith("tp "))
            if n_tp != 1 or pack.tp(path) is None:
                problems.append(f"{path}：tp 行應該恰好一行、絕對座標（實際 {n_tp} 行）")
    say("函式 %d 個：ride %d、turn %d、go %d、sight %d、其他 %d" % (
        len(pack.functions), kinds["ride"], kinds["turn"], kinds["go"], kinds["sight"],
        len(pack.functions) - sum(kinds.values())))

    fn_ids = {"%s:%s" % (NS, p) for p in pack.functions}
    dlg_ids = {"%s:%s" % (NS, p) for p in pack.dialogs}
    blob_dialogs = json.dumps(pack.dialogs, ensure_ascii=False, separators=(",", ":"))
    missing = set()
    for path, lines in pack.functions.items():
        for ln in lines:
            for ref in FN_REF_RE.findall(ln):
                if ref not in fn_ids:
                    missing.add(f"{path} 呼叫的函式 {ref}")
            for a, b in DIALOG_REF_RE.findall(ln):
                if (a or b) not in dlg_ids:
                    missing.add(f"{path} 打開的對話框 {a or b}")
    for a, b in DIALOG_REF_RE.findall(blob_dialogs):
        if (a or b) not in dlg_ids:
            missing.add(f"對話框裡 show_dialog 的 {a or b}")
    for (kind, tag), values in pack.tags.items():
        pool = fn_ids if kind == "function" else dlg_ids
        for v in values:
            if v.startswith(NS + ":") and v not in pool:
                missing.add(f"標籤 #{tag} 的 {v}")
    for m in sorted(missing):
        problems.append("不存在：" + m)
    for kind, tag in (("function", "minecraft:load"), ("function", "minecraft:tick"),
                      ("dialog", "minecraft:quick_actions"),
                      ("dialog", "minecraft:pause_screen_additions")):
        if not pack.tags.get((kind, tag)):
            problems.append(f"沒有 #{tag}（{kind} 標籤）")

    btn = line_buttons(pack)
    sbtn = sight_buttons(pack)
    vals = [n for _, _, _, n in btn] + [n for _, _, n, _ in sbtn]
    say(f"對話框 {len(pack.dialogs)} 個；各線站表共 {len(btn)} 顆按鈕、景點清單 {len(sbtn)} 顆")
    if any(v is None for v in vals):
        problems.append("有站表／景點按鈕不是 /trigger <物件> set <n>")
    elif sorted(vals) != list(range(1, len(vals) + 1)):
        problems.append("站表與景點按鈕的 trigger 值不是 1..N 連續不重複")
    for name, _, _, path in sbtn:
        if path is None:
            problems.append(f"景點清單的按鈕 {name} 沒有對應的 sight 函式")
    for path, code, _, _ in btn:
        if ("go/" + fn_code(code)) not in pack.functions:
            problems.append(f"{path} 的按鈕 {code} 沒有對應的 go 函式")
    return btn


# ====================================================================== 讀回告示牌

def _region_chunks(save):
    rdir = config.region_dir(save)
    return rdir, sorted(glob.glob(os.path.join(rdir, "r.*.*.mca")))


def scan_signs(save, targets, radius=48):
    """讀回各 tp 目的地附近（±radius 格）的告示牌方塊實體。

    搭車告示牌都立在月台門那一排，離主位頂多三四十公尺；tp 的目的地就是
    主位，所以掃它們附近就涵蓋全部的牌，不必把 1 GB 的存檔整個解一遍。
    回傳 [(x, y, z, 原始 Compound)]。
    """
    want = {}
    for x, _, z in targets:
        for cx in range((int(x) - radius) >> 4, ((int(x) + radius) >> 4) + 1):
            for cz in range((int(z) - radius) >> 4, ((int(z) + radius) >> 4) + 1):
                want.setdefault((cx >> 5, cz >> 5), set()).add((cx, cz))
    rdir = config.region_dir(save)
    out = []
    for (rx, rz), chunks in sorted(want.items()):
        p = os.path.join(rdir, f"r.{rx}.{rz}.mca")
        if not os.path.exists(p):
            continue
        raw = open(p, "rb").read()
        for cx, cz in sorted(chunks):
            i = (cx & 31) + (cz & 31) * 32
            off = int.from_bytes(raw[i * 4:i * 4 + 3], "big")
            if off == 0:
                continue
            q = off * 4096
            ln = int.from_bytes(raw[q:q + 4], "big")
            blob = raw[q + 5:q + 4 + ln]
            root = nbtlib.File.parse(io.BytesIO(zlib.decompress(blob) if raw[q + 4] == 2 else blob))
            root = root[""] if "" in root else root
            for be in root.get("block_entities", ()):
                if str(be.get("id", "")) in ("minecraft:sign", "minecraft:hanging_sign"):
                    out.append((int(be["x"]), int(be["y"]), int(be["z"]), be))
    return out


def click_of(be):
    for m in be.get("front_text", {}).get("messages", ()):
        if isinstance(m, dict) and "click_event" in m:
            return {str(k): str(v) for k, v in m["click_event"].items()}
    return None


def sign_checks(save, pack, problems, say):
    """存檔裡的告示牌點下去會去哪裡：每個函式、對話框都要存在。回傳挑給遊戲測的樣本。"""
    targets = [pack.tp(p)[:3] for p in pack.functions
               if p.split("/")[0] in ("ride", "turn", "go") and pack.tp(p)]
    t0 = time.time()
    signs = scan_signs(save, targets)
    clicks = [(x, y, z, be, click_of(be)) for x, y, z, be in signs]
    with_click = [c for c in clicks if c[4] is not None]
    say(f"告示牌：tp 目的地附近讀回 {len(signs)} 面，{len(with_click)} 面有點擊動作"
        f"（{time.time() - t0:.0f}s）")
    fn_ids = {"%s:%s" % (NS, p) for p in pack.functions}
    dlg_ids = {"%s:%s" % (NS, p) for p in pack.dialogs}
    n_run = n_dlg = 0
    bad = []
    samples = {}
    for x, y, z, be, ck in with_click:
        act = ck.get("action")
        if act == "run_command":
            n_run += 1
            cmd = ck.get("command", "").lstrip("/")
            m = re.match(r"^function (\S+)$", cmd)
            if not m or m.group(1) not in fn_ids:
                bad.append(f"({x},{y},{z}) run_command {cmd!r}")
            else:
                kind = m.group(1).split(":")[1].split("/")[0]
                samples.setdefault(kind, (x, y, z, be))
        elif act == "show_dialog":
            n_dlg += 1
            if ck.get("dialog") not in dlg_ids:
                bad.append(f"({x},{y},{z}) show_dialog {ck.get('dialog')!r}")
            else:
                samples.setdefault("dialog", (x, y, z, be))
    say(f"  run_command {n_run} 面、show_dialog {n_dlg} 面；指向不存在的 {len(bad)} 面")
    for b in bad[:20]:
        problems.append("告示牌的點擊指向不存在的東西：" + b)
    return samples


def _chunk_table(save):
    """{(cx, cz)} 存檔裡真的有寫出來的 chunk（只讀每個 region 檔的表頭）。"""
    have = set()
    for p in glob.glob(os.path.join(config.region_dir(save), "r.*.*.mca")):
        _, rx, rz, _ = os.path.basename(p).split(".")
        head = open(p, "rb").read(4096)
        for i in range(1024):
            if int.from_bytes(head[i * 4:i * 4 + 3], "big"):
                have.add((int(rx) * 32 + i % 32, int(rz) * 32 + i // 32))
    return have


def landing_checks(save, pack, problems, say):
    """每個 ride/turn/go 的落點：蓋出來的範圍內要站得住（domain/walk 的規則），
    面向的那個方向 1～3 格內要有告示牌（或還沒換成牌的月台門玻璃）。

    --bbox 只蓋一小塊的世界，落點所在的 chunk 沒寫出來就跳過（那一站沒蓋）。
    """
    import math
    from mrt.domain import walk
    from mrt.infrastructure.savereader import read_volume
    have = _chunk_table(save)
    targets = []
    for path in sorted(pack.functions):
        if path.split("/")[0] in ("ride", "turn", "go") and pack.tp(path):
            x, y, z, yaw, _ = pack.tp(path)
            x, y, z = int(math.floor(x)), int(y), int(math.floor(z))
            if (x >> 4, z >> 4) in have:
                targets.append((path, x, y, z, yaw))
    cells = {}
    for t in targets:
        cells.setdefault((t[1] >> 7, t[3] >> 7), []).append(t)
    n_ok = n_sign = n_pane = 0
    bad = []
    for grp in cells.values():
        xs, ys, zs = [t[1] for t in grp], [t[2] for t in grp], [t[3] for t in grp]
        vol = read_volume(save, min(xs) - 4, min(ys) - 1, min(zs) - 4,
                          max(xs) + 4, max(ys) + 2, max(zs) + 4, verbose=False)
        for path, x, y, z, yaw in grp:
            if walk.standable(vol.get, x, y, z):
                n_ok += 1
            else:
                bad.append("%s 的落點 (%d,%d,%d) 站不住：腳 %s／頭 %s／腳下 %s" % (
                    path, x, y, z, vol.get(x, y, z), vol.get(x, y + 1, z), vol.get(x, y - 1, z)))
            fx, fz = -math.sin(math.radians(yaw)), math.cos(math.radians(yaw))
            ahead = [vol.get(x + int(round(k * fx)), y, z + int(round(k * fz))) for k in (1, 2, 3)]
            if any("sign" in b for b in ahead):
                n_sign += 1
            elif any("pane" in b for b in ahead):
                n_pane += 1
    say(f"傳送落點：{len(targets)} 個落在有蓋出來的範圍，站得住 {n_ok} 個；"
        f"面前 3 格內有告示牌 {n_sign} 個、只有月台門玻璃 {n_pane} 個")
    problems.extend(bad[:20])
    if len(bad) > 20:
        problems.append("……站不住的落點還有 %d 個" % (len(bad) - 20))


# ====================================================================== 遊戲內測試

def find_java(mc_dir, version):
    v = json.load(open(os.path.join(mc_dir, "versions", version, version + ".json"), encoding="utf-8"))
    comp = v.get("javaVersion", {}).get("component", "")
    for pat in ("runtime/%s/*/%s/jre.bundle/Contents/Home/bin/java" % (comp, comp),
                "runtime/%s/*/%s/bin/java" % (comp, comp)):
        hits = sorted(glob.glob(os.path.join(mc_dir, pat)))
        if hits:
            return hits[0]
    return shutil.which("java")


def game_classpath(mc_dir, version):
    """啟動器的版本檔 -> classpath（伺服器用不到原生函式庫，只收 jar）。"""
    v = json.load(open(os.path.join(mc_dir, "versions", version, version + ".json"), encoding="utf-8"))
    cp = []
    for lib in v["libraries"]:
        ok = True
        for r in lib.get("rules", ()):
            hit = "os" not in r or r["os"].get("name") == "osx"
            if r["action"] == "allow":
                ok = hit
            elif hit:
                ok = False
        art = lib.get("downloads", {}).get("artifact")
        if ok and art:
            p = os.path.join(mc_dir, "libraries", art["path"])
            if os.path.exists(p):
                cp.append(p)
    cp.append(os.path.join(mc_dir, "versions", version, version + ".jar"))
    return ":".join(cp)


def _snbt(tag):
    return tag.snbt()


def pos_check(name, tp, report=True):
    """marker 執行完之後的 Pos／Rotation 要等於 tp 那一行（x、y、z 乘 10 取整，角度容許 ±0.1°）。
    結果在 #hit（1 = 對）；report=False 不印 FAIL（反向對照自己判）。"""
    x, y, z, yaw, pitch = tp
    r = int(round(yaw * 10))
    shift = 3600 if 2 <= (r % 3600) <= 3597 else 5400        # 別讓容許範圍跨過 0°
    er = (r + shift) % 3600
    ep = int(round(pitch * 10))
    return [
        "scoreboard players set #hit mrt_t 0",
        "execute store result score #x mrt_t run data get entity @s Pos[0] 10",
        "execute store result score #y mrt_t run data get entity @s Pos[1] 10",
        "execute store result score #z mrt_t run data get entity @s Pos[2] 10",
        "execute store result score #r mrt_t run data get entity @s Rotation[0] 10",
        "execute store result score #p mrt_t run data get entity @s Rotation[1] 10",
        "scoreboard players add #r mrt_t %d" % shift,
        "scoreboard players operation #r mrt_t %= #c3600 mrt_t",
        "execute if score #x mrt_t matches %d if score #y mrt_t matches %d if score #z mrt_t matches %d "
        "if score #r mrt_t matches %d..%d if score #p mrt_t matches %d..%d run scoreboard players set #hit mrt_t 1"
        % (int(round(x * 10)), int(round(y * 10)), int(round(z * 10)), er - 1, er + 1, ep - 1, ep + 1),
    ] + (["execute if score #hit mrt_t matches 0 run say MRTCHK FAIL %s expected %.1f %d %.1f %.1f %.1f"
          % (name, x, y, z, yaw, pitch)] if report else [])


def ok_fail(name, cond, want=True):
    """cond 是一段 execute 的 if 條件（不含 if）：成立就 ok、不成立就 FAIL（want=False 反過來）。"""
    yes, no = ("if", "unless") if want else ("unless", "if")
    return ["execute %s %s run say MRTCHK ok %s" % (yes, cond, name),
            "execute %s %s run say MRTCHK FAIL %s" % (no, cond, name)]


def build_selftest(pack, btn, samples, out_dir, rules):
    """產生 mrt_selftest 資料包。回傳 (預期的具名檢查, {計數名稱: 預期值}, 函式檔數)。"""
    from mrt.infrastructure import datapack as DP
    root = os.path.join(out_dir, TEST_NS)
    fdir = os.path.join(root, "data", TEST_NS, "function")
    files = {}
    expect = []

    def fn(path, lines):
        files[path] = lines

    # ---- 測試環境與測試個體 ----
    meta = {"pack": {"description": "taipei_mrt 的一次性遊戲內測試（tools/check_datapack.py 產生）",
                     "min_format": DP.PACK_MIN_FORMAT, "max_format": DP.PACK_MAX_FORMAT}}
    env = {"type": "minecraft:function", "setup": TEST_NS + ":setup", "teardown": TEST_NS + ":teardown"}
    inst = {"type": "minecraft:function", "function": "minecraft:always_pass",
            "environment": TEST_NS + ":env", "structure": "minecraft:empty",
            "max_ticks": 1, "setup_ticks": 100, "required": True}

    probes = [p for p in sorted(pack.functions) if p.split("/")[0] in TP_KINDS]
    setup = ["say MRTCHK begin",
             "scoreboard objectives add mrt_t dummy",
             "scoreboard players set #c3600 mrt_t 3600",
             "scoreboard players set #ok mrt_t 0",
             "scoreboard players set #tok mrt_t 0",
             "forceload add 0 0",
             # 進站提示的檢查要一口氣掃幾百次、每次一百多個選擇器
             "gamerule max_command_sequence_length 2000000"]
    # 進站提示的檢查在 teardown 做（新的一次執行，上面調高的指令上限才生效）
    hud_targets = []
    for path in probes:
        tp = pack.tp(path)
        g = next((int(ln.split()[-1]) for ln in pack.functions[path]
                  if ln.startswith("scoreboard players set @s %s.area " % NS)), None)
        if tp is not None and g is not None:
            hud_targets.append((path, tp, g))
    # 1. 開服時 #minecraft:load 跑過了嗎（這時我們還什麼都沒呼叫）
    setup += ok_fail("load_ran_at_startup", "score #setup %s.state matches 1.." % NS)
    expect.append("load_ran_at_startup")
    setup.append("execute store result score #beat0 mrt_t run scoreboard players get #beat %s.state" % NS)
    # 2. 記分板物件都建了
    for obj in ("state", "go", "menu", "area", "here"):
        setup.append("execute store success score #v mrt_t run scoreboard players set #probe %s.%s 0" % (NS, obj))
        setup += ok_fail("objective_%s" % obj, "score #v mrt_t matches 1")
        expect.append("objective_%s" % obj)
    # 3. 世界初始設定
    for rule, val in rules:
        want = {"true": 1, "false": 0}.get(val, None)
        want = int(val) if want is None else want
        setup.append("execute store result score #v mrt_t run gamerule %s" % rule)
        setup += ok_fail("rule_%s=%s" % (rule, val), "score #v mrt_t matches %d" % want)
        expect.append("rule_%s=%s" % (rule, val))
    setup.append("execute store result score #v mrt_t run time query time")
    setup += ok_fail("time_noon", "score #v mrt_t matches 6000")
    expect.append("time_noon")
    # 4. /reload（再跑一次 sys/load）不能蓋掉之後改過的規則
    setup += ["gamerule keep_inventory false",
              "function %s:sys/load" % NS,
              "execute store result score #v mrt_t run gamerule keep_inventory"]
    setup += ok_fail("reload_keeps_player_rules", "score #v mrt_t matches 0")
    setup.append("gamerule keep_inventory true")
    expect.append("reload_keeps_player_rules")
    # 5. 每一個 ride/turn/go 都在遊戲裡跑一次
    for k, path in enumerate(probes):
        setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:p/%d" % (TEST_NS, k))
        fn("p/%d" % k, ["function %s:%s" % (NS, path)] + pos_check(path, pack.tp(path))
           + ["scoreboard players operation #ok mrt_t += #hit mrt_t", "kill @s"])
    # 6. 站表的每一顆按鈕：trigger 值 -> sys/go -> 按鈕上那個站號的 go 函式的位置
    for path, code, obj, n in btn:
        tp = pack.tp("go/" + fn_code(code))
        if tp is None or obj is None:
            continue
        setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:t/%d" % (TEST_NS, n))
        fn("t/%d" % n, ["scoreboard players set @s %s %d" % (obj, n),
                        "function %s:sys/go" % NS]
           + pos_check("button_%s_%s" % (path.replace("/", "_"), code), tp)
           + ["execute unless score @s %s matches 0 run scoreboard players set #hit mrt_t 0" % obj,
              "execute unless score @s %s matches 0 run say MRTCHK FAIL trigger_not_reset_%d" % (obj, n),
              "scoreboard players operation #tok mrt_t += #hit mrt_t", "kill @s"])
    # 6b. 景點清單的每一顆按鈕：trigger 值 -> sys/go -> 那座景點的 sight 函式的位置
    for name, obj, n, path in sight_buttons(pack):
        tp = pack.tp(path) if path else None
        if tp is None or obj is None:
            continue
        setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:t/%d" % (TEST_NS, n))
        fn("t/%d" % n, ["scoreboard players set @s %s %d" % (obj, n),
                        "function %s:sys/go" % NS]
           + pos_check("button_sight_%s" % path.split("/")[-1], tp)
           + ["execute unless score @s %s matches 0 run scoreboard players set #hit mrt_t 0" % obj,
              "execute unless score @s %s matches 0 run say MRTCHK FAIL trigger_not_reset_%d" % (obj, n),
              "scoreboard players operation #tok mrt_t += #hit mrt_t", "kill @s"])
    # 反向對照：沒有執行任何傳送的 marker，不能被判成落在某個 go 函式的位置
    first_go = next((p for p in probes if p.startswith("go/")), None)
    if first_go:
        setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:neg_tp" % TEST_NS)
        fn("neg_tp", pos_check("negative_control_tp", pack.tp(first_go), report=False)
           + ok_fail("negative_control_tp", "score #hit mrt_t matches 0") + ["kill @s"])
        expect.append("negative_control_tp")
    # 反向對照：沒有這個編號的 trigger 值 -> 不動、歸零
    objs = {obj for _, _, obj, _ in btn if obj}
    if len(objs) == 1:
        obj = objs.pop()
        setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:neg_trig" % TEST_NS)
        n_all = len(btn) + len(sight_buttons(pack))       # 景點按鈕排在站名按鈕後面
        fn("neg_trig", ["scoreboard players set @s %s %d" % (obj, n_all + 1), "function %s:sys/go" % NS]
           + ok_fail("trigger_unknown_value_stays", "entity @s[x=0.5,y=100,z=0.5,distance=..0.01]")
           + ok_fail("trigger_unknown_value_reset", "score @s %s matches 0" % obj) + ["kill @s"])
        expect += ["trigger_unknown_value_stays", "trigger_unknown_value_reset"]
    # 7. 首次進入
    home = None
    for ln in pack.functions.get("sys/join", ()):
        m = re.match(r"^function %s:(go/\S+)$" % NS, ln)
        if m:
            home = m.group(1)
    setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:join" % TEST_NS)
    join = ["function %s:sys/join" % NS]
    join += ok_fail("join_tag", "entity @s[tag=%s.joined]" % NS)
    expect.append("join_tag")
    if home and pack.tp(home):
        join += pos_check("join_home_" + home.replace("/", "_"), pack.tp(home))
        join += ["execute if score #hit mrt_t matches 1 run say MRTCHK ok join_home_%s" % home.replace("/", "_")]
        expect.append("join_home_" + home.replace("/", "_"))
    fn("join", join + ["kill @s"])
    # 8. /trigger mrt.menu：分派之後歸零（dialog show 對 marker 會失敗，不影響）
    setup.append("execute positioned 0 100 0 summon minecraft:marker run function %s:menu" % TEST_NS)
    fn("menu", ["scoreboard players set @s %s.menu 1" % NS, "function %s:sys/menu" % NS]
       + ok_fail("menu_trigger_reset", "score @s %s.menu matches 0" % NS) + ["kill @s"])
    expect.append("menu_trigger_reset")
    # 9. 計數
    setup += ["execute store result storage %s:r tp int 1 run scoreboard players get #ok mrt_t" % TEST_NS,
              "execute store result storage %s:r trig int 1 run scoreboard players get #tok mrt_t" % TEST_NS,
              "function %s:report with storage %s:r" % (TEST_NS, TEST_NS)]
    fn("report", ["$say MRTCHK count tp=$(tp) trig=$(trig)"])
    fn("setup", setup)

    # ---- teardown：setup_ticks（100 tick）之後。區塊載入了、schedule 跳過幾次了 ----
    td = ["say MRTCHK teardown",
          "execute store result score #beat1 mrt_t run scoreboard players get #beat %s.state" % NS,
          "scoreboard players operation #beat1 mrt_t -= #beat0 mrt_t"]
    td += ok_fail("hud_heartbeat", "score #beat1 mrt_t matches 2..")
    expect.append("hud_heartbeat")
    td += ok_fail("chunk_loaded", "loaded 0 100 0")
    expect.append("chunk_loaded")
    td.append("fill 0 99 0 15 99 15 minecraft:stone")
    sign_list = []                       # (名稱, 方塊狀態, 方塊實體 Compound, 預期留得住)
    for kind, (x, y, z, be, state, src) in sorted(samples.items()):
        sign_list.append(("sign_%s_%s" % (kind, src), state, be, True))
    for path in sorted(pack.dialogs):
        sign_list.append(("dialog_sign_%s" % path.replace("/", "_"), "minecraft:oak_sign[rotation=0]",
                          _dialog_sign("%s:%s" % (NS, path)), True))
    sign_list.append(("negative_control_unknown_dialog", "minecraft:oak_sign[rotation=0]",
                      _dialog_sign("%s:no_such_dialog" % NS), False))
    for i, (name, state, be, keep) in enumerate(sign_list):
        x, y, z = 1 + (i % 7) * 2, 100, 2 + (i // 7) * 2
        body = nbtlib.tag.Compound({k: v for k, v in be.items() if k not in ("id", "x", "y", "z", "keepPacked")})
        m = re.search(r"facing=(\w+)", state)
        if m and "wall" in state:
            dx, dz = {"south": (0, -1), "north": (0, 1), "east": (-1, 0), "west": (1, 0)}[m.group(1)]
            td.append("setblock %d %d %d minecraft:stone" % (x + dx, y, z + dz))
        td.append("setblock %d %d %d %s%s" % (x, y, z, state, _snbt(body)))
        ck = None
        for msg in be["front_text"]["messages"]:
            if isinstance(msg, dict) and "click_event" in msg:
                ck = msg["click_event"]
        pattern = "{is_waxed:1b,front_text:{messages:[{click_event:%s}]}}" % _snbt(ck)
        td += ok_fail(name, "data block %d %d %d %s" % (x, y, z, pattern), want=keep)
        expect.append(name)
    # 進站提示：把 sys/hud 的掃描原樣複製一份，只把 @a 換成 @s（GameTest 裡沒有玩家；
    # @s 帶範圍參數時是拿執行者自己的座標去比，不必載入區塊）。每個傳送目的地
    # tp 一個 marker 過去、清掉它的 mrt.area、掃一次：它要落在那一站的範圍
    # （mrt.here = 函式裡記的車站編號），而且 hud_enter 要跑過（mrt.area 跟著更新）
    scan = []
    for ln in pack.functions.get("sys/hud", ()):
        if ("%s.here" % NS) in ln or "sys/hud_enter" in ln:
            scan.append(ln.replace("@a[", "@s[").replace("@a ", "@s "))
    fn("hud_scan", scan)
    td.append("scoreboard players set #hok mrt_t 0")
    for k, (path, tp, g) in enumerate(hud_targets):
        td.append("execute positioned 0 100 0 summon minecraft:marker run function %s:h/%d" % (TEST_NS, k))
        fn("h/%d" % k, ["tp @s %.1f %d %.1f" % tp[:3],
                        "scoreboard players reset @s %s.area" % NS,
                        "function %s:hud_scan" % TEST_NS,
                        "execute if score @s %s.here matches %d if score @s %s.area matches %d "
                        "run scoreboard players add #hok mrt_t 1" % (NS, g, NS, g),
                        "execute unless score @s %s.here matches %d run say MRTCHK FAIL hud_area_%s"
                        % (NS, g, path.replace("/", "_")),
                        "kill @s"])
    # 反向對照：站外（y=300 的高空）不能被判成在任何一站
    td.append("execute positioned 0 300 0 summon minecraft:marker run function %s:h_neg" % TEST_NS)
    fn("h_neg", ["function %s:hud_scan" % TEST_NS]
       + ok_fail("negative_control_hud_outside", "score @s %s.here matches 0" % NS) + ["kill @s"])
    expect.append("negative_control_hud_outside")
    td += ["execute store result storage %s:r hud int 1 run scoreboard players get #hok mrt_t" % TEST_NS,
           "function %s:report_hud with storage %s:r" % (TEST_NS, TEST_NS)]
    fn("report_hud", ["$say MRTCHK count hud=$(hud)"])
    td.append("forceload remove 0 0")
    fn("teardown", td)
    # 反向對照：故意寫壞的函式，log 裡一定要看到它的載入錯誤
    fn("broken", ["this_is_not_a_command 1 2 3"])

    os.makedirs(root, exist_ok=True)
    json.dump(meta, open(os.path.join(root, "pack.mcmeta"), "w", encoding="utf-8"), ensure_ascii=False)
    for sub, obj in (("test_environment/env.json", env), ("test_instance/datapack.json", inst)):
        p = os.path.join(root, "data", TEST_NS, sub)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        json.dump(obj, open(p, "w", encoding="utf-8"))
    for path, lines in files.items():
        p = os.path.join(fdir, path + ".mcfunction")
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    n_btn = sum(1 for path, code, obj, n in btn if pack.tp("go/" + fn_code(code)) and obj)
    n_btn += sum(1 for name, obj, n, path in sight_buttons(pack) if path and pack.tp(path) and obj)
    return expect, {"tp": len(probes), "trig": n_btn, "hud": len(hud_targets)}, len(files)


def _dialog_sign(dialog):
    from nbtlib.tag import Byte, Compound, List, String
    msgs = [Compound({"text": String("路線圖"),
                      "click_event": Compound({"action": String("show_dialog"), "dialog": String(dialog)})})]
    msgs += [Compound({"text": String("")}) for _ in range(3)]
    return Compound({"is_waxed": Byte(1),
                     "front_text": Compound({"messages": List[Compound](msgs), "color": String("black"),
                                             "has_glowing_text": Byte(0)}),
                     "back_text": Compound({"messages": List[Compound]([Compound({"text": String("")})] * 4),
                                            "color": String("black"), "has_glowing_text": Byte(0)})})


def synth_samples(pack):
    """存檔裡還沒有搭車告示牌時，用生成器自己的 World.sign 做三面（跟蓋世界同一段程式）。"""
    from mrt.infrastructure.mcworld import World
    w = World(tempfile.mkdtemp(prefix="mrt_sign_"))
    ride = next(p for p in sorted(pack.functions) if p.startswith("ride/"))
    turn = next((p for p in sorted(pack.functions) if p.startswith("turn/")), None)
    specs = [("ride", "standing", (0, 1), dict(command="function %s:%s" % (NS, ride)),
              [{"text": "往 下一站", "color": "#007EC7", "bold": True}, "Next station", "", "右鍵搭車"]),
             ("dialog", "wall", (0, 1), dict(dialog="%s:network" % NS),
              [{"text": "路線圖", "bold": True}, "Route map", "", ""])]
    if turn:
        specs.append(("turn", "wall", (1, 0), dict(command="function %s:%s" % (NS, turn)),
                      [{"text": "本站終點", "color": "#FF0000"}, "Terminal", "", ""]))
    out = {}
    for i, (kind, sk, facing, click, lines) in enumerate(specs):
        x, y, z = 3 + i * 2, 70, 3
        w.sign(x, y, z, lines, facing=facing, kind=sk, **click)
        c = w.chunks[(x >> 4, z >> 4)]
        a = c.sections[y >> 4]
        state = c.pal[a[(y & 15) * 256 + (z & 15) * 16 + (x & 15)]]
        out[kind] = (x, y, z, c.bes[(x, y, z)], state, "worldsign")
    return out


def run_game(java, cp, work, timeout):
    """跑 GameTest 伺服器；回傳 (結束碼, log 文字)。"""
    cmd = [java, "-Xmx2G", "-cp", cp, "net.minecraft.gametest.Main",
           "--universe", os.path.join(work, "universe"), "--packs", os.path.join(work, "packs"),
           "--report", os.path.join(work, "report.xml"), "--tests", TEST_NS + ":*"]
    t0 = time.time()
    p = subprocess.run(cmd, cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       timeout=timeout)
    log = p.stdout.decode("utf-8", "replace")
    open(os.path.join(work, "server.log"), "w", encoding="utf-8").write(log)
    return p.returncode, log, time.time() - t0


# log 的一筆紀錄以「[時:分:秒] [執行緒/等級]:」開頭，例外堆疊的後續行屬於同一筆
REC_RE = re.compile(r"^\[\d\d:\d\d:\d\d\] \[([^\]]+)/(INFO|WARN|ERROR|FATAL|DEBUG)\]: ")
# 跟資料包無關、GameTest 伺服器自己會講的警告
BENIGN_RE = re.compile(r"Can't keep up!")
# 兩個反向對照各自該留下的紀錄
CTL_FUNCTION = "Failed to load function %s:broken" % TEST_NS
CTL_DIALOG = "Failed to get element ResourceKey[minecraft:dialog / %s:no_such_dialog]" % NS


COUNT_NAMES = {"tp": "傳送函式在遊戲裡落到約定的位置與朝向",
               "trig": "站表與景點按鈕經 trigger 分派落到按鈕上那一站／那座景點",
               "hud": "進站提示檢查：傳送目的地落在那一站的範圍、hud_enter 有跑"}


def records(log):
    """log -> [(等級, 整筆文字)]；開頭 JVM 自己印的 WARNING 不算紀錄。"""
    out = []
    for ln in log.splitlines():
        m = REC_RE.match(ln)
        if m:
            out.append([m.group(2), ln])
        elif out:
            out[-1][1] += "\n" + ln
    return out


def analyse(log, expect, counts, problems, say):
    lines = log.splitlines()
    for pk in (config.DATAPACK_NAME, TEST_NS):
        if not any(("Included folder pack" in ln and pk in ln) for ln in lines):
            problems.append(f"遊戲沒有收進資料包 {pk}（log 裡沒有 Included folder pack）")
    if not any("Started game test server" in ln for ln in lines):
        problems.append("GameTest 伺服器沒有啟動成功（多半是資料包載入失敗，見下面的錯誤）")
    # 一律嚴格：WARN 以上的紀錄除了兩個反向對照與白名單，全部算問題
    bad, ctl_fn, ctl_dlg = [], 0, 0
    for level, rec in records(log):
        if level not in ("WARN", "ERROR", "FATAL"):
            continue
        if CTL_FUNCTION in rec:
            ctl_fn += 1
        elif CTL_DIALOG in rec:
            ctl_dlg += 1
        elif not BENIGN_RE.search(rec):
            bad.append(rec)
    if ctl_fn == 1:
        say(f"反向對照：log 裡恰好一筆「{CTL_FUNCTION}」—— 函式載入錯誤抓得到")
    else:
        problems.append(f"反向對照失敗：故意寫壞的 {TEST_NS}:broken 留下 {ctl_fn} 筆載入錯誤（應該 1 筆），"
                        "這支工具的 log 比對不可靠")
    if ctl_dlg == 1:
        say("反向對照：指向不存在對話框的牌，遊戲解不開（log 裡恰好一筆 Failed to get element）")
    else:
        problems.append(f"反向對照失敗：不存在的對話框留下 {ctl_dlg} 筆解碼錯誤（應該 1 筆）")
    for rec in bad[:15]:
        head = rec.splitlines()
        problems.append("log 裡的警告／錯誤：" + " / ".join(h.strip() for h in head[:3])[:400])
    ok = {}
    fails = []
    count = None
    for ln in lines:
        m = re.search(r"MRTCHK (ok|FAIL|count) ?(.*)$", ln)
        if not m:
            continue
        if m.group(1) == "count":
            count = dict(count or {}, **dict(kv.split("=") for kv in m.group(2).split()))
        elif m.group(1) == "ok":
            ok[m.group(2).split()[0]] = True
        else:
            fails.append(m.group(2))
    for f in fails:
        problems.append("遊戲內檢查失敗：" + f)
    missing = [e for e in expect if e not in ok and not any(f.split()[0] == e for f in fails)]
    for e in missing:
        problems.append("遊戲內檢查沒有跑到：" + e)
    say(f"遊戲內檢查：{len(ok)} 項通過、{len(fails)} 項失敗、{len(missing)} 項沒跑到")
    if count is None:
        problems.append("遊戲內沒有回報計數（setup 函式沒跑完？）")
    else:
        for k, v in counts.items():
            got = int(count.get(k, -1))
            say("  %s：%d/%d" % (COUNT_NAMES.get(k, k), got, v))
            if got != v:
                problems.append(f"遊戲內 {k}：只有 {got}/{v} 個對")
    passed = any("All" in ln and "required tests passed" in ln for ln in lines)
    if not passed:
        problems.append("GameTest 沒有回報「All required tests passed」")
    return ok, fails


def main():
    ap = argparse.ArgumentParser(description="讀回並在真的遊戲裡驗證搭乘系統資料包")
    ap.add_argument("save")
    ap.add_argument("--no-game", action="store_true", help="只做讀回檢查，不開遊戲")
    ap.add_argument("--no-signs", action="store_true", help="不讀回存檔裡的告示牌")
    ap.add_argument("--keep", help="遊戲內測試的工作目錄（預設用暫存目錄，失敗時保留）")
    ap.add_argument("--mc-dir", default=MC_DIR)
    ap.add_argument("--version", default=VERSION)
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()
    say = print
    problems = []

    root = os.path.join(a.save, "datapacks", config.DATAPACK_NAME)
    if not os.path.isdir(root):
        print(f"✗ 找不到資料包 {root}")
        return 1
    pack = Pack(root)
    say(f"== 一、從磁碟讀回 {root}")
    btn = static_checks(a.save, pack, problems, say, game_data_version(a.mc_dir, a.version))
    samples = {}
    if not a.no_signs:
        for kind, (x, y, z, be) in sign_checks(a.save, pack, problems, say).items():
            from mrt.infrastructure.savereader import read_volume
            state = read_volume(a.save, x, y, z, x, y, z, verbose=False).get(x, y, z)
            samples[kind] = (x, y, z, be, state, "save")
    landing_checks(a.save, pack, problems, say)
    if not a.no_game:
        say("\n== 二、交給 Minecraft %s 的 GameTest 伺服器" % a.version)
        synth = {k: v for k, v in synth_samples(pack).items() if k not in samples}
        if synth:
            say("存檔裡沒有 %s 的告示牌可以取樣，這幾種改用 World.sign 產生的牌" % "／".join(sorted(synth)))
            samples.update(synth)
        java = find_java(a.mc_dir, a.version)
        if not java or not os.path.exists(os.path.join(a.mc_dir, "versions", a.version, a.version + ".jar")):
            print(f"✗ 找不到 Minecraft {a.version} 或它的 Java（--mc-dir {a.mc_dir}）；只做讀回可以加 --no-game")
            return 1
        cp = game_classpath(a.mc_dir, a.version)
        work = a.keep or tempfile.mkdtemp(prefix="mrt_dpcheck_")
        shutil.rmtree(os.path.join(work, "packs"), ignore_errors=True)
        shutil.rmtree(os.path.join(work, "universe"), ignore_errors=True)
        os.makedirs(os.path.join(work, "packs"))
        shutil.copytree(root, os.path.join(work, "packs", config.DATAPACK_NAME))
        from mrt.application import ride_plan as RP
        rules = [(r, v) for r, v, _, _ in RP.GAME_RULES]
        expect, counts, nfile = build_selftest(pack, btn, samples, os.path.join(work, "packs"), rules)
        say(f"測試資料包 {TEST_NS}：{nfile} 個函式、{len(expect)} 項具名檢查，"
            f"外加 {counts['tp']} 個傳送函式、{counts['trig']} 顆站表按鈕、{counts['hud']} 個進站提示落點")
        say(f"java：{java}\n工作目錄：{work}")
        try:
            code, log, dt = run_game(java, cp, work, a.timeout)
        except subprocess.TimeoutExpired:
            problems.append(f"遊戲在 {a.timeout}s 內沒有結束")
            code, log, dt = -1, "", a.timeout
        say(f"GameTest 伺服器結束碼 {code}（{dt:.0f}s），log 在 {os.path.join(work, 'server.log')}")
        for ln in log.splitlines():
            if "Included folder pack" in ln or "GAME TESTS COMPLETE" in ln \
                    or "required tests" in ln or "[台北捷運]" in ln or "MRTCHK count" in ln:
                say("  | " + ln.strip()[:240])
        if code != 0:
            problems.append(f"GameTest 伺服器結束碼 {code}（不是 0）")
        analyse(log, expect, counts, problems, say)
        if not problems and not a.keep:
            shutil.rmtree(work, ignore_errors=True)

    print()
    if problems:
        print(f"✗ {len(problems)} 個問題：")
        for p in problems[:60]:
            print("  - " + p)
        return 1
    print("✓ 資料包讀回" + ("檢查全部通過（沒有開遊戲）" if a.no_game else "與遊戲內驗證全部通過"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
