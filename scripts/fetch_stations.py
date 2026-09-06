#!/usr/bin/env python3
"""抓取捷運車站節點 (含中英文名、代碼、樓層/深度提示) -> data/stations.json"""
import json, subprocess, time, os

MIRRORS = ["https://overpass.kumi.systems/api/interpreter",
           "https://overpass-api.de/api/interpreter",
           "https://overpass.private.coffee/api/interpreter"]
BBOX = "24.85,121.15,25.32,121.75"
Q = f"""[out:json][timeout:300];
(
  node["railway"="station"]["station"="subway"]({BBOX});
  node["railway"="station"]["subway"="yes"]({BBOX});
  node["railway"="station"]["station"="light_rail"]({BBOX});
);
out body;"""

def main():
    for i in range(9):
        url = MIRRORS[i % len(MIRRORS)]
        p = subprocess.run(["curl","-sS","--max-time","300","-X","POST",
                            "--data-urlencode",f"data={Q}",url],capture_output=True,text=True)
        if p.returncode == 0 and p.stdout.strip():
            try:
                d = json.loads(p.stdout); break
            except json.JSONDecodeError:
                print(f"  截斷 @ {url.split('/')[2]}")
        time.sleep(4+4*i)
    else:
        print("失敗"); return
    os.makedirs("data", exist_ok=True)
    json.dump(d, open("data/stations.json","w"), ensure_ascii=False)
    print(f"車站節點: {len(d['elements'])}")

if __name__ == "__main__":
    main()
