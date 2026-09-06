"""台北捷運 Minecraft 1:1 重建。

層次（相依方向一律由外往內，內層不得引用外層）：

    domain/          純規則：線形、鐵軌形狀、幾何、隧道分層、高程取樣
    ports/           內層對外層開的介面（BlockSink）
    application/     用例：把 domain 算出來的東西寫進 BlockSink
    adapters/        外部資料進來：OSM、DEM、投影
    infrastructure/  外部技術細節：Anvil 存檔寫入、Overpass HTTP

    cli/             組合根：決定實際用哪個實作，只有這一層看得到全部
    tools/           驗證與檢視（獨立讀回存檔，不信生成器的自述）
"""
