#!/usr/bin/env python3
"""BlockSink：生成器唯一需要知道的「世界」介面。

domain 與 application 兩層不該知道 Anvil 區域檔、nbtlib、或 26.2 的存檔佈局
長什麼樣 —— 它們只需要「把某個方塊放到 (x, y, z)」。所有蓋東西的函式都收一個
BlockSink，由 cli 層決定實際塞進去的是誰。

實作在 infrastructure/mcworld.py 的 World；測試則塞一個 dict 就好
（application/landmarks.py 的自我測試正是這樣跑的，不必產生存檔）。

原本每支生成器都 `from mcworld import World`，只為了 main() 自己開存檔；
真正蓋東西的函式早就是收 w 當第一個參數，等於介面已經存在，只是沒講出來。
"""
try:                                    # Protocol 在 3.8+，這裡只當型別註解用
    from typing import Protocol, runtime_checkable
except ImportError:                     # pragma: no cover
    Protocol = object

    def runtime_checkable(c):
        return c


@runtime_checkable
class BlockSink(Protocol):
    """能收方塊的東西。"""

    def set(self, x, y, z, block):
        """把 (x, y, z) 設成 block（如 "minecraft:stone"，可帶方塊狀態）。

        超出目前處理範圍的座標由實作自行丟棄 —— 串流式生成靠這個行為做裁切，
        呼叫端不必先判斷方塊落在哪個 region。
        """


@runtime_checkable
class ChunkSink(Protocol):
    """整段（16x16x16）批次寫入。

    滿地形的世界有上億個方塊，逐格呼叫 set() 跑不完 —— 地形生成改用 numpy
    一次算出整個 section 的編碼陣列再交出去。這是效能上不得不開的第二個口，
    不是另一種抽象。
    """

    def set_section(self, sy, codes, names):
        """sy 是 section 索引（y >> 4）；codes 是 16x16x16 的索引陣列，
        names 是索引對應的方塊名稱清單。"""


class DictSink:
    """把方塊收進 dict 的 BlockSink，給測試與幾何驗算用。

    不做任何範圍裁切：測試要看的就是生成器算出來的完整結果。
    """

    def __init__(self):
        self.blocks = {}
        self.signs = {}                     # (x, y, z) -> 四行文字

    def set(self, x, y, z, block):
        self.blocks[(int(x), int(y), int(z))] = block

    def get(self, x, y, z, default="minecraft:air"):
        return self.blocks.get((int(x), int(y), int(z)), default)

    def sign(self, x, y, z, lines, facing=(0, 1), wood="oak"):
        """告示牌：方塊照放，文字另外記在 signs 裡，測試可以查牌上寫什麼。

        infrastructure 的 World 也有同名方法（那邊才真的寫 NBT）；生成器
        放站名牌時呼叫的是這個介面，測試的 sink 不能少了它。
        """
        self.set(x, y, z, "minecraft:%s_sign" % wood)
        self.signs[(int(x), int(y), int(z))] = [str(t) for t in list(lines)[:4]]

    def __len__(self):
        return len(self.blocks)

    def bbox(self):
        """回傳 (x0, z0, x1, z1)；空的話回 None。"""
        if not self.blocks:
            return None
        xs = [k[0] for k in self.blocks]
        zs = [k[2] for k in self.blocks]
        return min(xs), min(zs), max(xs), max(zs)
