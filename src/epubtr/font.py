"""字体子集化：只保留书里用到的字，控制体积。"""

from __future__ import annotations

from pathlib import Path


def subset_font(src: Path, chars: str, out: Path) -> int:
    """把 src 裁剪到只含 chars 里的字符，写入 out，返回字节数。"""
    from fontTools import subset

    options = subset.Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True
    options.recalc_bounds = True
    options.drop_tables += ["DSIG"]
    font = subset.load_font(str(src), options)
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(text=chars)
    subsetter.subset(font)
    out.parent.mkdir(parents=True, exist_ok=True)
    subset.save_font(font, str(out), options)
    return out.stat().st_size
