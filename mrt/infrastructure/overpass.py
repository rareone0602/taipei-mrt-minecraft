#!/usr/bin/env python3
"""Overpass API 客戶端：鏡像輪替、重試、快取。

五支 fetch_*.py 原本各自帶一份幾乎相同的鏡像清單與重試迴圈（重試次數
6~9、逾時 180~500 秒、有的檢查 stdout 開頭是不是 "{"、有的沒有）。
合成這一份之後差異用參數表示。

用 curl 子行程而不是 urllib/requests：sandbox 擋掉 **/*.pem 的讀取，
Python 的 SSL 模組載入 certifi 的 CA bundle 會直接失敗。
"""
import json
import os
import subprocess
import time

MIRRORS = [
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# 全台北盆地 + 桃園機捷西段
BBOX = "24.85,121.15,25.32,121.75"

# pyproj 會把 CURL_CA_BUNDLE 指到 /dev/null（見 adapters/projection.py），
# 那會讓 curl 驗不過憑證 —— 傳給子行程前先拿掉。
CURL_ENV = {k: v for k, v in os.environ.items() if k != "CURL_CA_BUNDLE"}

DEFAULT_CACHE = os.environ.get("OVERPASS_CACHE")


def host(url):
    return url.split("/")[2]


def query(q, label="query", tries=9, timeout=300, backoff=4):
    """送出一次 Overpass 查詢，回傳解析好的 dict；全部失敗回 None。

    只有 json.loads 成功才算數 —— 鏡像過載時會回 200 加一段截斷的 JSON，
    光看 returncode 會把半截資料當成功寫進 data/。
    """
    for i in range(tries):
        url = MIRRORS[i % len(MIRRORS)]
        p = subprocess.run(
            ["curl", "-sS", "--max-time", str(timeout), "-X", "POST",
             "--data-urlencode", f"data={q}", url],
            capture_output=True, text=True, env=CURL_ENV)
        if p.returncode == 0 and p.stdout.strip().startswith("{"):
            try:
                return json.loads(p.stdout)
            except json.JSONDecodeError:
                print(f"    {label}: 回應截斷/非 JSON ({len(p.stdout)}B) @ {host(url)}")
        else:
            err = (p.stderr or "").strip()[:80]
            print(f"    {label}: curl rc={p.returncode} @ {host(url)} {err}")
        time.sleep(backoff + backoff * i)
    return None


def query_cached(name, q, cache_dir=None, refresh=False, **kw):
    """同 query()，但先看快取。抓細部資料時一輪要打十幾次，重跑不該再打 API。"""
    cache_dir = cache_dir or DEFAULT_CACHE
    if not cache_dir:
        return query(q, label=name, **kw)

    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{name}.json")
    if os.path.exists(path) and not refresh:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"{name:<14} 快取毀損，重抓")
        else:
            print(f"{name:<14} 使用快取 {len(d['elements']):>6} 個元素  {path}")
            return d

    d = query(q, label=name, **kw)
    if d is not None:
        json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"{name:<14} 取得    {len(d['elements']):>6} 個元素")
    else:
        print(f"{name:<14} 失敗，這份資料會是空的")
    return d
