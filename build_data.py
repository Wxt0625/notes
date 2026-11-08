# -*- coding: utf-8 -*-
"""
从「最终数据整合/CSV」生成单文件网页 index.html。

用法：python build_data.py（可在任意目录运行，路径以本脚本所在目录为基准）
输入：<脚本目录>\\CSV\\*.csv
输出：<脚本目录>\\index.html（数据内嵌，可离线打开、可直接发布）

数据口径：
  1. 只保留「状态 = ok」且五个坐标齐全、坐标未越界的记录；
  2. 角色按数据文件夹（CSV 文件名去掉末尾数字）归类，显示名取该组「监管者名字」众数，
     避免观战视频标题识别串角色带来的噪声；
  3. 坐标为 (行, 列)，从 1 开始；绝大多数地图 3x3，湖景村 / 月亮河公园为 3x4。
"""
import collections
import csv
import json
import os
import re

BASE = os.path.dirname(os.path.abspath(__file__))
CSV_DIR = os.path.join(BASE, "CSV")
TEMPLATE = os.path.join(BASE, "template.html")
OUTPUT = os.path.join(BASE, "index.html")

# 3x4 地图（其余按 3x3 处理）
COLS4 = {"湖景村", "月亮河公园"}
# 同一角色的多个批次文件夹合并
GROUP_OVERRIDE = {"伞": "宿伞"}

MAP_ORDER = (
    "军工厂", "圣心医院", "红教堂", "湖景村", "月亮河公园",
    "里奥的回忆", "永眠镇", "唐人街", "不归林",
)
HUNTER_ORDER = (
    "厂长", "小丑", "鹿头", "杰克", "蜘蛛", "红蝶", "黄衣之主", "宿伞之魂",
    "摄影师", "疯眼", "梦之女巫", "爱哭鬼", "孽蜥", "红夫人", "26号守卫", "使徒",
    "小提琴家", "雕刻家", "博士", "破轮", "渔女", "蜡像师", "噩梦", "记录员",
    "隐士", "守夜人", "歌剧演员", "愚人金", "时空之影", "跛脚羊", "喧嚣", "杂货商",
    "台球手", "女王蜂", "牙医",
)

S_X = ["求生者%d_x" % i for i in range(1, 5)]
S_Y = ["求生者%d_y" % i for i in range(1, 5)]


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
        by_group[r["_group"]][(r.get("监管者名字") or "").strip()] += 1
    return {g: c.most_common(1)[0][0] for g, c in by_group.items()}


def main():
    rows = load_rows()
    names = display_names(rows)

    maps, hunters = [], []
    records = []
    dropped = collections.Counter()

    for r in rows:
        if (r.get("状态") or "").strip() != "ok":
            dropped["状态非 ok"] += 1
            continue
        m = (r.get("地图") or "").strip()
        if not m or m == "未识别":
            dropped["地图未识别"] += 1
            continue
        cols = 4 if m in COLS4 else 3
        try:
            s = [int(r[x]) * 10 + int(r[y]) for x, y in zip(S_X, S_Y)]
            h = int(r["监管者_x"]) * 10 + int(r["监管者_y"])
        except (ValueError, TypeError):
            dropped["坐标非数字"] += 1
            continue
        coords = s + [h]
        if any(not (1 <= v // 10 <= 3 and 1 <= v % 10 <= cols) for v in coords):
            dropped["坐标越界（疑似识别误差）"] += 1
            continue
        hname = names[r["_group"]]
        if m not in maps:
            maps.append(m)
        if hname not in hunters:
            hunters.append(hname)
        reviewed = 1 if (r.get("人工已审核") or "").strip() == "是" else 0
        solo = 1 if (r.get("视频分类") or "").strip() == "单对局本人录像" else 0
        records.append([
            maps.index(m),
            hunters.index(hname),
            s[0], s[1], s[2], s[3],
            h,
            reviewed | (solo << 1),
            (r.get("视频文件") or "").strip(),
        ])

    # 按指定顺序显示，尚未列出的新地图和角色追加到末尾。
    maps_sorted = [m for m in MAP_ORDER if m in maps] + sorted(set(maps) - set(MAP_ORDER))
    hunters_sorted = [h for h in HUNTER_ORDER if h in hunters] + sorted(set(hunters) - set(HUNTER_ORDER))
    # 按名称表重排索引
    mi = {m: i for i, m in enumerate(maps_sorted)}
    hi = {h: i for i, h in enumerate(hunters_sorted)}
    for rec in records:
        rec[0] = mi[maps[rec[0]]]
        rec[1] = hi[hunters[rec[1]]]

    payload = {
        "maps": maps_sorted,
        "hunters": hunters_sorted,
        "cols": {m: (4 if m in COLS4 else 3) for m in maps_sorted},
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


if __name__ == "__main__":
    main()
