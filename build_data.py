# -*- coding: utf-8 -*-
"""
从「最终数据整合/CSV」生成单文件网页 index.html。

用法：python build_data.py（可在任意目录运行，路径以本脚本所在目录为基准）
      python build_data.py --toy（同时生成 dist/dwrgwxt-toy.zip）
输入：<脚本目录>\\CSV\\*.csv
输出：<脚本目录>\\index.html（数据内嵌，可离线打开、可直接发布）

数据口径：
  1. 只保留「状态 = ok」「筛选分类 = 正常或已人工审核」，且五个坐标齐全合法的记录
     （合法格见 valid_cells，随 payload.cells 下发前端）；
  2. 单角色 CSV 按文件名归类，显示名取该组「监管者名字」众数；混合补充表按每行角色归类，
     已核实的个别错分记录单独修正；
  3. 坐标为 (行, 列)，从 1 开始；绝大多数地图 3x3，湖景村 / 月亮河公园为完整 3x4，
     永眠镇为 3x3 主体 + 右上角额外一格 (1,4)（第 4 列仅此一格有效）。
  4. 五个落点不得重复；同一 BV 号有时间点时舍弃无时间点的记录，同一时间点只录入一次，
     数据冲突时整组排除。
"""
import argparse
import collections
import csv
import json
import os
from pathlib import Path
import re
from uuid import uuid4
import zipfile

BASE = os.path.dirname(os.path.abspath(__file__))
CSV_DIR = os.path.join(BASE, "CSV")
TEMPLATE = os.path.join(BASE, "template.html")
OUTPUT = os.path.join(BASE, "index.html")

# 页面按 4 列排版的地图；湖景村 / 月亮河公园是完整 3x4，永眠镇仅右上角多一格
COLS4 = {"湖景村", "月亮河公园", "永眠镇"}
# 不规则分区：这些地图第 4 列只有列出的格子有效，其余 (2,4)/(3,4) 等视为越界
EXTRA_CELLS = {"永眠镇": {14}}
# 档案附录的屠夫落点名称，格号仍按行*10+列编码
GRID3_LANDING_LABELS = {
    11: "左上", 12: "中上", 13: "右上",
    21: "左中", 22: "中间", 23: "右中",
    31: "左下", 32: "中下", 33: "右下",
}
MAP_LANDING_LABELS = {
    "永眠镇": {**GRID3_LANDING_LABELS, 14: "墓地"},
    "月亮河公园": {
        11: "马戏团", 12: "人皇桥", 13: "死木马", 14: "起点站",
        21: "左中", 22: "三站", 23: "二站", 24: "右中",
        31: "终点站", 32: "活木马", 33: "鬼屋", 34: "鬼板",
    },
    "湖景村": {
        11: "玉米地", 13: "海厕", 14: "海边",
        21: "小船", 22: "中场左", 23: "中场",
        33: "大石头", 34: "右下",
    },
}
# 同一角色的多个批次文件夹合并
GROUP_OVERRIDE = {"伞": "宿伞"}
MIXED_FILES = {"补充数据11.21.csv", "漏项补充数据.csv"}
HUNTER_OVERRIDE = {("孽蜥.csv", "928939d7b74819af"): "心兽"}

MAP_ORDER = (
    "军工厂", "圣心医院", "红教堂", "湖景村", "月亮河公园",
    "里奥的回忆", "永眠镇", "唐人街", "不归林",
)
HUNTER_ORDER = (
    "厂长", "小丑", "鹿头", "杰克", "蜘蛛", "红蝶", "黄衣之主", "宿伞之魂",
    "摄影师", "疯眼", "梦之女巫", "爱哭鬼", "孽蜥", "红夫人", "26号守卫", "使徒",
    "小提琴家", "雕刻家", "博士", "破轮", "渔女", "蜡像师", "噩梦", "记录员",
    "隐士", "守夜人", "歌剧演员", "愚人金", "时空之影", "跛脚羊", "喧嚣", "杂货商",
    "台球手", "女王蜂", "牙医", "心兽",
)

S_X = ["求生者%d_x" % i for i in range(1, 5)]
S_Y = ["求生者%d_y" % i for i in range(1, 5)]


def valid_cells(m):
    """每张图的合法格集合（行*10+列）。不规则分区以 3x3 主体为底，只补上额外存在的格子。"""
    if m in EXTRA_CELLS:
        return {r * 10 + c for r in range(1, 4) for c in range(1, 4)} | EXTRA_CELLS[m]
    cols = 4 if m in COLS4 else 3
    return {r * 10 + c for r in range(1, 4) for c in range(1, cols + 1)}


def timestamp_seconds(time):
    if not re.fullmatch(r"(?:[0-9]+:)?[0-9]+:[0-5][0-9]", time):
        return None
    seconds = 0
    for part in time.split(":"):
        seconds = seconds * 60 + int(part)
    return seconds


def load_rows():
    rows = []
    for name in sorted(os.listdir(CSV_DIR)):
        if not name.lower().endswith(".csv"):
            continue
        stem = os.path.splitext(name)[0]
        group = re.sub(r"\d+$", "", stem)
        group = GROUP_OVERRIDE.get(group, group)
        with open(os.path.join(CSV_DIR, name), encoding="utf-8-sig", newline="") as fh:
            for r in csv.DictReader(fh):
                r["_group"] = group
                r["_file"] = name
                rows.append(r)
    return rows


def display_names(rows):
    by_group = collections.defaultdict(collections.Counter)
    for r in rows:
        if r["_file"] not in MIXED_FILES and (r["_file"], r.get("记录ID")) not in HUNTER_OVERRIDE:
            by_group[r["_group"]][(r.get("监管者名字") or "").strip()] += 1
    return {g: c.most_common(1)[0][0] for g, c in by_group.items()}


def write_toy_package(template, data_js):
    root = Path(BASE)
    output = root / "dist" / "dwrgwxt-toy.zip"
    output.parent.mkdir(exist_ok=True)
    head = (
        '<script src="toy/site-data.js"></script>\n'
        '<script defer src="https://s1.hdslb.com/bfs/seed/toy/app/sdk/toy-sdk.js"></script>\n'
        '<script defer src="toy/video-links.js"></script>\n'
    )
    html = template.replace("__DATA__", "window.SITE_DATA").replace("</head>", head + "</head>", 1)
    staging = output.with_name(f".{output.stem}-{uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(staging, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("index.html", html)
            archive.writestr("toy/site-data.js", "window.SITE_DATA = " + data_js + ";\n")
            archive.write(root / "announcements.js", "announcements.js")
            archive.write(root / "toy" / "video-links.js", "toy/video-links.js")
            for path in sorted((root / "assets").rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root).as_posix())
        staging.replace(output)
    finally:
        staging.unlink(missing_ok=True)
    return output


def main(build_toy=False):
    rows = load_rows()
    names = display_names(rows)

    dropped = collections.Counter()
    by_source = collections.defaultdict(list)

    for row_number, r in enumerate(rows):
        if (r.get("状态") or "").strip() != "ok":
            dropped["状态非 ok"] += 1
            continue
        if (r.get("筛选分类") or "").strip() not in {"正常", "已人工审核"}:
            dropped["筛选分类非正常或已人工审核"] += 1
            continue
        m = (r.get("地图") or "").strip()
        if not m or m == "未识别":
            dropped["地图未识别"] += 1
            continue
        valid = valid_cells(m)
        try:
            s = [int(r[x]) * 10 + int(r[y]) for x, y in zip(S_X, S_Y)]
            h = int(r["监管者_x"]) * 10 + int(r["监管者_y"])
        except (ValueError, TypeError):
            dropped["坐标非数字"] += 1
            continue
        coords = s + [h]
        if any(v not in valid for v in coords):
            dropped["坐标越界（疑似识别误差）"] += 1
            continue
        if len(set(coords)) != len(coords):
            dropped["同局坐标重复"] += 1
            continue
        location = (r["_file"], r.get("记录ID"))
        if r["_file"] in MIXED_FILES:
            hname = (r.get("监管者名字") or "").strip()
        else:
            hname = HUNTER_OVERRIDE.get(location) or names[r["_group"]]
        if not hname:
            dropped["监管者未识别"] += 1
            continue
        bv = (r.get("BV号") or "").strip()
        time = (r.get("时间点") or "").strip()
        seconds = timestamp_seconds(time)
        source = (bv, seconds if seconds is not None else time) if bv else (None, row_number)
        reviewed = 1 if (r.get("人工已审核") or "").strip() == "是" else 0
        solo = 1 if (r.get("视频分类") or "").strip() == "单对局本人录像" else 0
        by_source[source].append([
            m, hname, *s,
            h,
            reviewed | (solo << 1),
            (r.get("视频文件") or "").strip(),
            bv,
            time,
            seconds,
        ])

    records = []
    timed_videos = {bv for bv, time in by_source if bv and time != ""}
    for (bv, time), group in by_source.items():
        if bv in timed_videos and time == "":
            dropped["同视频已有时间点"] += len(group)
            continue
        if len(group) > 1:
            matches = {(r[0], r[1], tuple(sorted(r[2:6])), r[6]) for r in group}
            if len(matches) > 1:
                dropped["同源对局数据冲突"] += len(group)
                continue
            dropped["视频来源重复"] += len(group) - 1
        records.append(group[0])

    # 按指定顺序显示，尚未列出的新地图和角色追加到末尾。
    maps = {r[0] for r in records}
    hunters = {r[1] for r in records}
    maps_sorted = [m for m in MAP_ORDER if m in maps] + sorted(maps - set(MAP_ORDER))
    hunters_sorted = [h for h in HUNTER_ORDER if h in hunters] + sorted(hunters - set(HUNTER_ORDER))
    # 按名称表重排索引
    mi = {m: i for i, m in enumerate(maps_sorted)}
    hi = {h: i for i, h in enumerate(hunters_sorted)}
    for rec in records:
        rec[0] = mi[rec[0]]
        rec[1] = hi[rec[1]]

    payload = {
        "maps": maps_sorted,
        "hunters": hunters_sorted,
        "cols": {m: (4 if m in COLS4 else 3) for m in maps_sorted},
        "cells": {m: sorted(valid_cells(m)) for m in maps_sorted},
        "landingLabels": {
            m: MAP_LANDING_LABELS.get(m, {} if m in COLS4 else GRID3_LANDING_LABELS)
            for m in maps_sorted
        },
        "records": records,
        "meta": {
            "raw": len(rows),
            "kept": len(records),
            "dropped": dict(dropped),
            "reviewed": sum(1 for r in records if r[7] & 1),
            "solo": sum(1 for r in records if r[7] & 2),
        },
    }

    data_js = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    tpl = open(TEMPLATE, encoding="utf-8").read()
    assert "__DATA__" in tpl, "模板缺少 __DATA__ 占位符"
    html = tpl.replace("__DATA__", data_js)
    with open(OUTPUT, "w", encoding="utf-8") as fh:
        fh.write(html)

    print("原始记录 %d → 保留 %d，剔除：" % (len(rows), len(records)), dict(dropped))
    print("地图 %d 张：" % len(maps_sorted), " / ".join(maps_sorted))
    print("监管者 %d 名：" % len(hunters_sorted), " / ".join(hunters_sorted))
    print("已人工审核 %d，本人录像 %d" % (payload["meta"]["reviewed"], payload["meta"]["solo"]))
    print("输出：%s（%.1f KB）" % (OUTPUT, os.path.getsize(OUTPUT) / 1024))
    if build_toy:
        print("Toy 发布包：", write_toy_package(tpl, data_js))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="从 CSV 生成庄园选点档案网页。")
    parser.add_argument("--toy", action="store_true", help="同时生成 B 站 Toy 上传 ZIP")
    main(build_toy=parser.parse_args().toy)
