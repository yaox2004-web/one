#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主力行为阶段识别引擎 (phases.py) —— 2026量化时代 v4·ATR自适应版
=================================================
v4 新增：ATR(14) 波动率自适应
  1. ATR计算：TR = max(高-低, |高-昨收|, |低-昨收|)，14日均值
  2. 长阴短柱：从固定5% → 1.5×ATR(14)（高波动股门槛高，低波动股门槛低）
  3. 高波动标记：ATR/股价 > 5% 标"量化对倒嫌疑"
  4. 保留v3全部现代化参数（倍量1.8/窗口20/平量8%等）
"""
import gc
import os
import warnings

import numpy as np
import pandas as pd

import json
import os
import warnings

import numpy as np
import pandas as pd

from data_fetcher import (
    ANALYSIS_DIR,
    KLINE_DIR,
    load_kline_json,
    to_tx,
    FUND_FLOW_AVAILABLE,
)

# ============ 全局配置 ============
PHASE_LOG_PATH = os.path.join(ANALYSIS_DIR, "phase_log.csv")

STOCKS = {
    "601138": "工业富联",
    "300476": "胜宏科技",
    "603516": "淳中科技",
    "300394": "天孚通信",
}

STOCKS_30 = {
    "002371": "北方华创", "603986": "兆易创新", "300308": "中际旭创",
    "601899": "紫金矿业", "300750": "宁德时代", "688981": "中芯国际",
    "002202": "金风科技", "600183": "生益科技", "600584": "长电科技",
    "601288": "农业银行",
    "000002": "万科A", "002304": "洋河股份", "000568": "泸州老窖",
    "601012": "隆基绿能", "600809": "山西汾酒", "300760": "迈瑞医疗",
    "000858": "五粮液", "601633": "长城汽车", "601888": "中国中免",
    "600436": "片仔癀",
    "600309": "万华化学", "600028": "中国石化", "002415": "海康威视",
    "601668": "中国建筑", "600585": "海螺水泥", "600104": "上汽集团",
    "002027": "分众传媒", "002352": "顺丰控股", "600276": "恒瑞医药",
    "603288": "海天味业",
}

SELF43_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "self43.txt")

def load_self43():
    if not os.path.exists(SELF43_PATH):
        warnings.warn(f"[load_self43] 未找到 {SELF43_PATH}，回退 STOCKS_30")
        return dict(STOCKS_30)
    stocks = {}
    with open(SELF43_PATH, encoding="utf-8") as f:
        for line in f:
            code = line.strip()
            if not code or code.startswith("#"):
                continue
            code = code.zfill(6)
            tx = to_tx(code)
            candidates = [
                os.path.join(KLINE_DIR, tx[:2], f"{tx}.json"),
                os.path.join(KLINE_DIR, f"{tx}.json"),
            ]
            name = ""
            for path in candidates:
                if os.path.exists(path):
                    try:
                        with open(path, encoding="utf-8") as jf:
                            name = json.load(jf).get("name", "") or ""
                    except Exception:
                        name = ""
                    break
            stocks[code] = name
    if not stocks:
        warnings.warn("[load_self43] self43.txt 无有效代码，回退 STOCKS_30")
        return dict(STOCKS_30)
    return stocks

STOCKS_GROUP = {
    "大牛股": list(STOCKS_30.keys())[:10],
    "大熊股": list(STOCKS_30.keys())[10:20],
    "横盘股": list(STOCKS_30.keys())[20:30],
}

PHASE_BUILD = "建仓"
PHASE_WASH = "洗盘"
PHASE_PULL = "拉升"
PHASE_DIST = "出货"
PHASE_NONE = "无明显迹象"
PHASES = [PHASE_BUILD, PHASE_WASH, PHASE_PULL, PHASE_DIST]

CONFIRM_DAYS = 3

# ============ v4新增：ATR参数 ============
ATR_PERIOD = 14          # ATR周期（默认14日）
ATR_LONG_DOWN_MULT = 1.5  # 长阴跌幅阈值 = 1.5×ATR（原固定5%）
ATR_HIGH_VOL_PCT = 5.0    # ATR/股价 > 5% = 高波动（量化对倒嫌疑）

# ============ 位置分类 ============
POS_HIGH_PCT = 0.80
POS_AODI_PCT = 0.15
POS_LOW_PCT = 0.40
POS_WINDOW = 120

# ============ 量柱识别阈值 ============
BEILIANG_RATIO = 1.8
GAOLIANG_WINDOW = 20
DILIANG_WINDOW = 20
PINGLIANG_TOL = 0.08
PINGLIANG_MIN = 2
TILIANG_MIN = 2

COND_BUILD = 5
COND_WASH = 4
COND_PULL = 5
COND_DIST = 6
MIN_COND = 2

# ============ 日内基因参数 ============
# v4: 长阴跌幅改为ATR自适应，不再用固定百分比
FASHAO_RATIO = 3.0
FASHAO_HIGH_RATIO = 2.0
FASHAO_WINDOW = 20
BEIFENG_WINDOW = 10
MA20_TOL = 0.03

# ============ 工具：位置分类 ============
def classify_position(close, lo120, hi120):
    if hi120 <= lo120 or lo120 <= 0:
        return "中位"
    if close > hi120:
        return "过峰"
    pos_pct = (close - lo120) / (hi120 - lo120)
    if pos_pct > POS_HIGH_PCT:
        return "高位"
    if pos_pct < POS_AODI_PCT:
        return "凹底"
    if pos_pct < POS_LOW_PCT:
        return "低位"
    return "中位"

# ============ v4新增：ATR计算 ============
def compute_atr(df, period=ATR_PERIOD):
    """
    ATR(14) 真实波幅均值。
    TR = max(当日最高-当日最低, |当日最高-昨收|, |当日最低-昨收|)
    ATR = TR的N日简单移动平均
    返回 df 新增列：TR / ATR14 / ATR_pct
    """
    high = df["最高"]
    low = df["最低"]
    close = df["收盘"]
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    df["TR"] = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    df["ATR14"] = df["TR"].rolling(period, min_periods=1).mean()
    df["ATR_pct"] = df["ATR14"] / close * 100
    return df

# ============ 一、量柱六元素识别 ============
def identify_volume_columns(df):
    df = df.copy()
    n = len(df)
    vol = df["成交量"].values
    close = df["收盘"].values
    low = df["最低"].values

    prev_vol = df["成交量"].shift(1)
    df["beiliang"] = (df["成交量"] >= prev_vol * BEILIANG_RATIO).fillna(False)

    df["gaoliang"] = df["成交量"].rolling(GAOLIANG_WINDOW, min_periods=1).apply(
        lambda x: len(x) > 1 and x[-1] == x.max(), raw=True).fillna(0).astype(bool)
    df["diliang"] = df["成交量"].rolling(DILIANG_WINDOW, min_periods=1).apply(
        lambda x: len(x) > 1 and x[-1] == x.min(), raw=True).fillna(0).astype(bool)

    df["pingliang"] = np.zeros(n, dtype=bool)
    cnt = 0
    for i in range(n):
        if i >= 1 and vol[i] > 0 and abs(vol[i] - vol[i - 1]) / vol[i - 1] <= PINGLIANG_TOL:
            cnt += 1
        else:
            cnt = 0
        df.at[i, "pingliang"] = cnt >= PINGLIANG_MIN - 1
    df["pingliang"] = df["pingliang"].astype(bool)

    df["suoliang"] = (df["成交量"] < prev_vol).fillna(False)

    df["tiliang"] = np.zeros(n, dtype=bool)
    run = 0
    for i in range(1, n):
        if vol[i] > vol[i - 1]:
            run += 1
        else:
            run = 0
        df.at[i, "tiliang"] = run >= TILIANG_MIN - 1
    df["tiliang"] = df["tiliang"].astype(bool)

    def label(row):
        if row["tiliang"]:
            return "梯量柱"
        if row["pingliang"]:
            return "平量柱"
        if row["beiliang"]:
            return "倍量柱"
        if row["gaoliang"]:
            return "高量柱"
        if row["diliang"]:
            return "低量柱"
        if row["suoliang"]:
            return "缩量柱"
        return "普通量柱"
    df["量柱形态"] = df.apply(label, axis=1)
    return df

# ============ 二、三日定性 ============
def three_day_confirm(df):
    df = df.copy()
    n = len(df)
    close = df["收盘"].values
    low = df["最低"].values
    vol = df["成交量"].values
    open_ = df["开盘"].values

    df["将军柱"] = np.zeros(n, dtype=bool)
    df["黄金柱"] = np.zeros(n, dtype=bool)

    is_candidate = df["beiliang"] | df["gaoliang"] | df["diliang"] | df["tiliang"]

    for i in range(n):
        if not is_candidate[i]:
            continue
        if i + 3 >= n:
            break
        j1, j2, j3 = i + 1, i + 2, i + 3
        base_low = low[i]
        base_close = close[i]
        base_vol = vol[i]

        bu_po = (min(low[j1], low[j2], low[j3]) >= base_low)
        jj_price_up_vol_shrink = any(
            close[j] > close[j - 1] and vol[j] < vol[j - 1] for j in (j1, j2, j3)
        )
        if bu_po and jj_price_up_vol_shrink:
            df.at[i, "将军柱"] = True

        price_up_days = sum([close[j1] > base_close,
                             close[j2] > close[j1],
                             close[j3] > close[j2]])
        vol_shrink_days = sum([vol[j1] < base_vol,
                               vol[j2] < vol[j1],
                               vol[j3] < vol[j2]])
        gj_price_up = (close[j3] > base_close) and (price_up_days >= 2)
        gj_vol_shrink = (np.mean([vol[j1], vol[j2], vol[j3]]) < base_vol) and (vol_shrink_days >= 2)
        base_shidi = min(open_[i], base_close)
        gj_bu_po = min(low[j1], low[j2], low[j3]) >= base_shidi
        combo = (
            (df["beiliang"][i] and df["suoliang"][j1]) or
            (df["gaoliang"][i] and df["suoliang"][j1]) or
            (df["beiliang"][i] and df["tiliang"][j1]) or
            (df["diliang"][i] and df["tiliang"][j1])
        )
        if gj_price_up and gj_vol_shrink and gj_bu_po and combo:
            df.at[i, "黄金柱"] = True
    return df

# ============ 三、量性九种标注 ============
def label_xing(pos, xing, is_jj, is_gj, close_up):
    if is_gj:
        return "黄金柱"
    if is_jj:
        return "将军柱"
    if pos in ("凹底", "低位"):
        if xing in ("倍量柱", "高量柱") and close_up:
            return "启动柱"
        if xing == "低量柱":
            return "试探柱"
        return "建仓柱"
    if pos == "中位":
        if xing in ("梯量柱", "倍量柱") and close_up:
            return "拉升柱"
        if xing == "缩量柱" and close_up:
            return "增仓柱"
        return "震仓柱"
    if pos in ("高位", "过峰"):
        if xing in ("倍量柱", "高量柱"):
            return "拉升柱"
        return "补仓柱"
    return "试探柱"

# ============ 四、日内基因识别（v4: ATR自适应长阴） ============
def identify_genes(df):
    df = df.copy()
    n = len(df)
    close = df["收盘"].values
    open_ = df["开盘"].values
    low = df["最低"].values
    high = df["最高"].values
    vol = df["成交量"].values
    pos = df["位置"].values
    is_jj = df["将军柱"].values
    is_gj = df["黄金柱"].values
    beiliang = df["beiliang"].values

    df["收阳"] = (df["收盘"] > df["收盘"].shift(1)).fillna(False)

    # v4: 长阴短柱改为ATR自适应
    # 当日下跌金额 > 1.5×ATR(14) 且 收阴 且 量缩 = 长阴短柱
    drop_amt = (df["收盘"].shift(1) - df["收盘"]).fillna(0)
    atr_prev = df["ATR14"].shift(1).fillna(0)
    df["长阴短柱"] = (drop_amt > ATR_LONG_DOWN_MULT * atr_prev) & \
                     (df["收盘"] < df["开盘"]) & \
                     (df["成交量"] < df["成交量"].shift(1))
    df["长阴短柱"] = df["长阴短柱"].fillna(False)

    # 百日低量
    baidi = df["成交量"].rolling(100, min_periods=1).apply(
        lambda x: len(x) > 1 and x[-1] == x.min(), raw=True).fillna(0)
    df["百日低量"] = baidi.astype(bool)
    df["百日低量群"] = df["百日低量"].rolling(30, min_periods=1).sum() >= 2

    df["卧底矮将军"] = (df["位置"].isin(["凹底", "低位"])) & is_jj
    df["合力黄金柱"] = is_gj & (df["位置"].isin(["中位", "低位", "凹底"]))

    df["hi10"] = df["最高"].rolling(BEIFENG_WINDOW, min_periods=1).max().shift(1)
    df["倍量过左峰"] = beiliang & df["收阳"] & (df["收盘"] > df["hi10"])

    df["ma20"] = df["收盘"].rolling(20, min_periods=1).mean()
    df["缩量回踩"] = df["suoliang"] & (df["收盘"] >= df["ma20"]) & \
        (df["收盘"] <= df["ma20"] * (1 + MA20_TOL))

    df["vol_ma20"] = df["成交量"].rolling(FASHAO_WINDOW, min_periods=1).mean()
    cond1 = (df["成交量"] > df["成交量"].shift(1) * FASHAO_RATIO).fillna(False)
    cond2 = (df["成交量"] > df["vol_ma20"] * FASHAO_HIGH_RATIO) & df["tiliang"]
    df["发烧柱"] = cond1 | cond2

    df["假阴真阳"] = (df["收盘"] < df["开盘"]) & df["收阳"]
    df["ma20_above"] = df["收盘"] >= df["ma20"]

    # v4新增：高波动标记（ATR/股价>5% = 量化对倒嫌疑）
    df["高波动"] = df["ATR_pct"] > ATR_HIGH_VOL_PCT

    return df

# ============ 五、量价配合 ============
def classify_vp(close_t, close_y, vol_t, vol_y):
    if pd.isna(close_y) or pd.isna(vol_y) or vol_y <= 0:
        return "量价齐升"
    up = close_t > close_y
    vol_up = vol_t > vol_y
    if up and vol_up:
        return "量价齐升"
    if up and not vol_up:
        return "价升量缩"
    if not up and not vol_up:
        return "价跌量缩"
    return "量增价跌"

# ============ 六、三要素组合判定 ============
def judge_phase(day, d_yest, idx_ret):
    pos = day["位置"]
    vp = day["量价配合"]

    build_conds = {
        "位置=凹底/低位": pos in ("凹底", "低位"),
        "百日低量或百日低量群": bool(day["百日低量"]) or bool(day["百日低量群"]),
        "卧底矮将军(低位将军柱)": bool(day["卧底矮将军"]),
        "合力黄金柱(换挡柱)": bool(day["合力黄金柱"]),
        "该跌不跌(大盘跌本股收阳)": bool(idx_ret < 0 and day["收阳"]),
    }

    wash_conds = {
        "位置=中位": pos == "中位",
        "长阴短柱": bool(day["长阴短柱"]),
        "缩量回踩20MA/黄金线": bool(day["缩量回踩"]),
        "量价配合=价跌量缩": vp == "价跌量缩",
    }

    pull_conds = {
        "位置=中位/高位/过峰": pos in ("中位", "高位", "过峰"),
        "倍量过左峰": bool(day["倍量过左峰"]),
        "梯量柱或黄金柱接力": bool(day["tiliang"]) or bool(day["黄金柱"]),
        "量价配合=价升量缩": vp == "价升量缩",
        "突破关键量线(过峰/破10日新高)": pos == "过峰" or bool(day["倍量过左峰"]),
    }

    dist_conds = {
        "位置=顶部(高位)": pos in ("高位", "过峰"),
        "发烧柱(巨量)": bool(day["发烧柱"]),
        "假阴真阳": bool(day["假阴真阳"]),
        "该涨不涨(大盘涨本股收阴)": bool(idx_ret > 0 and not day["收阳"]),
        "量价背离(量增价跌/价升量缩)": vp in ("量增价跌", "价升量缩"),
        "高量柱后三日无法续量": bool(day["gaoliang"]) and not bool(day["tiliang"]),
    }

    stage_pos_ok = {
        PHASE_BUILD: pos in ("凹底", "低位"),
        PHASE_WASH: pos == "中位",
        PHASE_PULL: pos in ("中位", "高位", "过峰"),
        PHASE_DIST: pos in ("高位", "过峰"),
    }

    stage_other_hit = {
        PHASE_BUILD: sum(v for k, v in build_conds.items() if k != "位置=凹底/低位"),
        PHASE_WASH: sum(v for k, v in wash_conds.items() if k != "位置=中位"),
        PHASE_PULL: sum(v for k, v in pull_conds.items() if k != "位置=中位/高位/过峰"),
        PHASE_DIST: sum(v for k, v in dist_conds.items() if k != "位置=顶部(高位)"),
    }
    stage_tot_other = {
        PHASE_BUILD: len(build_conds) - 1,
        PHASE_WASH: len(wash_conds) - 1,
        PHASE_PULL: len(pull_conds) - 1,
        PHASE_DIST: len(dist_conds) - 1,
    }

    stage_reasons = {
        PHASE_BUILD: [k for k, v in build_conds.items() if v],
        PHASE_WASH: [k for k, v in wash_conds.items() if v],
        PHASE_PULL: [k for k, v in pull_conds.items() if v],
        PHASE_DIST: [k for k, v in dist_conds.items() if v],
    }

    candidates = {}
    for ph in PHASES:
        if stage_pos_ok[ph] and stage_other_hit[ph] >= 1:
            candidates[ph] = stage_other_hit[ph]

    if candidates:
        best_stage = max(candidates, key=candidates.get)
        total_hit = stage_other_hit[best_stage] + 1
        total_cond = stage_tot_other[best_stage] + 1
        confidence = total_hit / total_cond
        main_reason = "+".join(stage_reasons[best_stage])
        stage = best_stage
    else:
        stage = PHASE_NONE
        confidence = 0.0
        main_reason = "无明显迹象"

    return stage, confidence, main_reason

# ============ 七、单只股票分析 ============
def analyze_stock(code, name):
    df = load_kline_json(code)
    idx = load_kline_json("sh000001")

    if df.empty:
        warnings.warn(f"[phases] {code} 日线 JSON 无数据")
        return _empty_df()

    df["日期"] = pd.to_datetime(df["日期"])
    idx["日期"] = pd.to_datetime(idx["日期"])
    idx_map = idx.set_index("日期")["收盘"].to_dict() if not idx.empty else {}

    for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
        if col not in df.columns:
            df[col] = np.nan
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df["lo120"] = df["最低"].rolling(POS_WINDOW, min_periods=1).min()
    df["hi120_prev"] = df["最高"].shift(1).rolling(POS_WINDOW, min_periods=1).max()

    df["idx_ret"] = df["日期"].map(idx_map).pct_change().fillna(0.0)

    # v4: 先算ATR，再做量柱识别
    df = compute_atr(df)
    df = identify_volume_columns(df)
    df = three_day_confirm(df)
    df["位置"] = [classify_position(c, l, h) for c, l, h
                  in zip(df["收盘"], df["lo120"], df["hi120_prev"])]
    df["量价配合"] = [classify_vp(c, cy, v, vy)
                     for c, cy, v, vy in zip(
                         df["收盘"], df["收盘"].shift(1),
                         df["成交量"], df["成交量"].shift(1))]
    df = identify_genes(df)
    df["量性"] = df.apply(lambda r: label_xing(
        pos=r["位置"], xing=r["量柱形态"],
        is_jj=bool(r["将军柱"]), is_gj=bool(r["黄金柱"]),
        close_up=bool(r["收阳"])), axis=1)

    n = len(df)
    rows = []
    for i in range(20, n):
        d = df.iloc[i]
        d_yest = df.iloc[i - 1]

        stage, confidence, main_reason = judge_phase(d, d_yest, d["idx_ret"])

        remark = ""
        if not FUND_FLOW_AVAILABLE:
            remark = "资金流向缺失"
        if not bool(d.get("ma20_above", True)):
            remark = (remark + ";" if remark else "") + "大盘MA20之下,信号降权"
        # v4新增：高波动标记
        if bool(d.get("高波动", False)):
            remark = (remark + ";" if remark else "") + "ATR高波动,量化对倒嫌疑"

        rows.append({
            "日期": d["日期"].strftime("%Y-%m-%d"),
            "代码": code,
            "名称": name,
            "当前阶段": stage,
            "置信度": round(confidence, 2),
            "位置": d["位置"],
            "命中的量性": d["量性"],
            "量柱形态": d["量柱形态"],
            "量价配合": d["量价配合"],
            "主要依据": main_reason,
            "备注": remark,
        })

    result = pd.DataFrame(rows)
    if result.empty:
        return result
    stages = result["当前阶段"].tolist()
    nn = len(stages)
    dur = [1] * nn
    for i in range(1, nn):
        dur[i] = dur[i - 1] + 1 if stages[i] == stages[i - 1] else 1
    confirmed = []
    for i in range(nn):
        if dur[i] >= CONFIRM_DAYS:
            confirmed.append("已确认")
        elif i == 0:
            confirmed.append("初始阶段")
        else:
            confirmed.append("疑似切换（未确认）")
    result["持续天数"] = dur
    result["确认状态"] = confirmed
    return result

def _empty_df():
    return pd.DataFrame(columns=[
        "日期", "代码", "名称", "当前阶段", "置信度", "位置", "命中的量性",
        "量柱形态", "量价配合", "主要依据", "备注", "持续天数", "确认状态",
    ])

# ============ 八、主流程 ============
def run_all(stock_list=None, output_path=None, verbose=True):
    if stock_list is None:
        stock_list = STOCKS_4
    if output_path is None:
        output_path = PHASE_LOG_PATH
    if verbose:
        print(f"\n{'='*60}")
        print(f">>> 阶段识别(v4·ATR自适应):{len(stock_list)} 只股票")
        print(f"{'='*60}")

    all_frames = []
    for code, name in stock_list.items():
        df = analyze_stock(code, name)
        if df.empty:
            if verbose:
                print(f"    {name} 无有效数据，跳过")
            continue
        all_frames.append(df)
        if verbose:
            print(f"\n>>> {code} {name}")
            total = len(df)
            counts = df["当前阶段"].value_counts()
            c_build = int(counts.get(PHASE_BUILD, 0))
            c_wash = int(counts.get(PHASE_WASH, 0))
            c_pull = int(counts.get(PHASE_PULL, 0))
            c_dist = int(counts.get(PHASE_DIST, 0))
            c_none = int(counts.get(PHASE_NONE, 0))
            none_pct = c_none / total * 100 if total else 0
            print(f"    建仓{c_build} 洗盘{c_wash} 拉升{c_pull} 出货{c_dist} "
                  f"无迹象{c_none} (无迹象占比{none_pct:.1f}%)")
            pos_dist = df["位置"].value_counts()
            print(f"    位置分布: " + ", ".join(f"{k}:{v}" for k, v in pos_dist.items()))
        del df
        gc.collect()

    if all_frames:
        final = pd.concat(all_frames, ignore_index=True)
        final = final.sort_values(["代码", "日期"]).reset_index(drop=True)
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        final.to_csv(output_path, index=False, encoding="utf-8-sig")
        print(f"\n{'='*60}")
        print(f"结果已写入: {output_path}")
        print(f"总记录数: {len(final)}")
        return final
    else:
        print("无任何有效结果")
        return None

STOCKS_4 = load_self43()

if __name__ == "__main__":
    run_all()
