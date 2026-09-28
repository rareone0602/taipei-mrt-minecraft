#!/usr/bin/env python3
"""Overpass API client: mirror rotation, retries and caching.

The five fetch_*.py scripts each used to carry a nearly identical mirror list
and retry loop (6 to 9 retries, timeouts of 180 to 500 seconds, some checking
whether stdout starts with "{" and some not). They are merged here, and the
differences are expressed as parameters.

This uses a curl subprocess rather than urllib/requests: the sandbox blocks
reads of **/*.pem, so Python's SSL module fails outright when it loads the
certifi CA bundle.
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

# The whole Taipei Basin plus the western section of the Taoyuan Airport MRT.
BBOX = "24.85,121.15,25.32,121.75"

# The pyproj setup points CURL_CA_BUNDLE at /dev/null (see adapters/projection.py),
# which makes curl fail certificate verification, so it is removed before the
# environment is passed to the subprocess.
CURL_ENV = {k: v for k, v in os.environ.items() if k != "CURL_CA_BUNDLE"}

DEFAULT_CACHE = os.environ.get("OVERPASS_CACHE")

# overpass-api.de answers curl's default User-Agent with 406 Not Acceptable
# (since 2026). Report the project name only, with no personal data (name, email).
USER_AGENT = "taipei-mrt-minecraft/1.0 (OpenStreetMap data build script)"


def host(url):
    return url.split("/")[2]


def query(q, label="query", tries=9, timeout=300, backoff=4):
    """Send one Overpass query and return the parsed dict, or None if every attempt fails.

    Only a successful json.loads counts: an overloaded mirror returns 200 with
    truncated JSON, and checking the return code alone would write the partial
    data into data/ as a success.
    """
    for i in range(tries):
        url = MIRRORS[i % len(MIRRORS)]
        p = subprocess.run(
            ["curl", "-sS", "--max-time", str(timeout), "-A", USER_AGENT, "-X", "POST",
             "--data-urlencode", f"data={q}", url],
            capture_output=True, text=True, env=CURL_ENV)
        if p.returncode == 0 and p.stdout.strip().startswith("{"):
            try:
                return json.loads(p.stdout)
            except json.JSONDecodeError:
                print(f"    {label}: response truncated or not JSON ({len(p.stdout)}B) @ {host(url)}")
        else:
            err = (p.stderr or "").strip()[:80]
            print(f"    {label}: curl rc={p.returncode} @ {host(url)} {err}")
        time.sleep(backoff + backoff * i)
    return None


def query_cached(name, q, cache_dir=None, refresh=False, **kw):
    """Same as query(), but check the cache first.

    Fetching the station details makes a dozen or more queries per run, and a
    rerun should not call the API again.
    """
    cache_dir = cache_dir or DEFAULT_CACHE
    if not cache_dir:
        return query(q, label=name, **kw)

    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, f"{name}.json")
    if os.path.exists(path) and not refresh:
        try:
            d = json.load(open(path, encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"{name:<14} cache corrupt, fetching again")
        else:
            print(f"{name:<14} from cache {len(d['elements']):>6} elements  {path}")
            return d

    d = query(q, label=name, **kw)
    if d is not None:
        json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"{name:<14} fetched    {len(d['elements']):>6} elements")
    else:
        print(f"{name:<14} failed; this data will be empty")
    return d
