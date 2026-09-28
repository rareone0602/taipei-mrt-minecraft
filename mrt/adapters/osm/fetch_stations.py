#!/usr/bin/env python3
"""Fetch the metro station nodes -> data/stations.json.

The nodes carry Chinese and English names, codes and level/depth hints.
"""
import json, os

from mrt import config
from mrt.infrastructure.overpass import BBOX, query

Q = f"""[out:json][timeout:300];
(
  node["railway"="station"]["station"="subway"]({BBOX});
  node["railway"="station"]["subway"="yes"]({BBOX});
  node["railway"="station"]["station"="light_rail"]({BBOX});
);
out body;"""


def main():
    d = query(Q, label="stations")
    if d is None:
        print("Failed"); return
    os.makedirs(config.DATA, exist_ok=True)
    json.dump(d, open(config.STATIONS_JSON, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"Station nodes: {len(d['elements'])}")


if __name__ == "__main__":
    main()
