#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号引擎 (signal_engine.py)
===========================
接收 phases.py 的阶段识别结果，叠加 4 个信号维度（量价形态、大盘共振、
龙虎榜席位、位置确认），产出信号日志。

设计原则：
- 每个信号点独立决策：基于 4 维组合判定
- 信号必须可回溯：输出完整依据（哪几个维度命中）
- 信号可复现：同一输入必出同一输出
- 维度独立计算，组合判定用"评分制"，不引入复杂规则

输入：phases.py 产出的 phase_log.csv（阶段、置信度、位置、量柱形态等）
      加上 data_fetcher.py 的日线/龙虎榜数据
输出：/var/minis/workspace/astock/signal_log.csv
      字段：日期、代码、名称、阶段、信号、置信度、信号依据、触发时间、
            信号强度、备注

4 个维度（详见下方各维度函数）：
  1. 量价形态：基于量柱形态+量价配合
  2. 大盘共振：基于上证指数同期趋势
  3. 龙虎榜席位：基于东财 datacenter-web 龙虎榜接口（已验证可用）
  4. 位置确认：基于 120 日相对分位

纪律：
  - 这是"信号引擎"骨架，不含仓位、止损、退出
  - 席位维度若接口失败返回 None，不阻塞其他维度
  - 每个维度有独立降级机制
"""
import sqlite3
import time
import warnings
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd

from data_fetcher import DB_PATH, fetch_lhb_history, fetch_index_daily, FUND_FLOW_AVAILABLE, fetch_daily
from phases import STOCKS_4, STOCKS_GROUP, PHASE_LOG_PATH
from dim_wash import (
    get_float_shares,
    compute_turnover_series,
    dim_wash,
    apply_wash_adjustment,
    compute_market_state,
)

# 资金流向降级标注（从 data_fetcher 引入）
FUND_FLOW_AVAILABLE_NOTE = not FUND_FLOW_AVAILABLE

# ============ 全局配置 ============
SIGNAL_LOG_PATH = "/var/minis/workspace/astock/signal_log.csv"

# 大盘趋势窗口（上证指数 20 日均线判断牛熊）
INDEX_TREND_WINDOW = 20
# 大盘共振判定：个股位置=中位/高位/过峰 时，要求大盘同向
POSITIVE_POS = ("中位", "高位", "过峰")

# 信号强度阈值（四维评分，满分 4）
SIGNAL_THRESHOLDS = {
    "强信号": 3,   # 4 维中至少 3 个命中
    "中信号": 2,   # 至少 2 个命中
    "弱信号": 1,   # 仅 1 个命中（记录但不强调）
}


# ============ 维度1：量价形态 ============
def dim_volume_price(day_row) -> bool:
    """
    量价形态维度：判断当日量柱形态是否"有效"。

    有效形态（量学原著概念，引用知识库）：
      - 倍量柱（第9章）
      - 梯量柱（第9章）
      - 黄金柱（第11章）
      - 将军柱（第11章）
    以及对应的量价配合（第10章）：
      - 价升量缩（供不应求，第10章最有价值形态）
      - 量价齐升（强势）

    命中 = 量柱形态 ∈ {倍量柱, 梯量柱} 或 量价配合 ∈ {价升量缩, 量价齐升}
    """
    zhuang = day_row.get("量柱形态", "")
    vp = day_row.get("量价配合", "")
    return (zhuang in ("倍量柱", "梯量柱")) or (vp in ("价升量缩", "量价齐升"))


# ============ 维度2：大盘共振 ============
def dim_market(index_ma_up: bool, day_row) -> bool:
    """
    大盘共振维度：当日上证指数 20 日均线趋势方向 vs 个股位置。
    命中 = (大盘 MA20 向上 且 个股位置 ∈ {中位,高位,过峰}) 或
          (大盘 MA20 向下 且 个股位置 ∈ {凹底,低位})
    即大盘与个股"同向共振"。

    依据：量学"位置决定性质"——大盘趋势决定个股阶段的有效性。
    大盘向上时，中位/高位的拉升更可信；大盘向下时，凹底/低位的建仓更可信。
    """
    pos = day_row.get("位置", "")
    if index_ma_up:
        return pos in POSITIVE_POS
    else:
        return pos in ("凹底", "低位")


# ============ 维度3：龙虎榜席位 ============
def dim_lhb(code: str, date_str: str, lhb_df: Optional[pd.DataFrame]) -> Optional[bool]:
    """
    龙虎榜席位维度：判断当日该股是否上榜，以及席位画像。
    - 上榜 = 命中
    - 席位画像（机构买入占比）影响信号强度

    依据：量学"庄在散先"（第1章）——席位是"庄"的可观测代理。
    东财 datacenter-web 接口可用（已验证）。

    返回：
      True  = 上榜
      False = 未上榜
      None  = 接口失败（降级，不阻塞其他维度）
    """
    if lhb_df is None:
        return None
    # 龙虎榜数据：'代码' + '上榜日'
    if "上榜日" in lhb_df.columns:
        day = lhb_df[lhb_df["上榜日"] == date_str]
    elif "date" in lhb_df.columns:
        day = lhb_df[lhb_df["date"] == date_str]
    else:
        return None
    if day.empty:
        return False
    return True


# ============ 维度4：位置确认 ============
def dim_position(day_row) -> bool:
    """
    位置确认维度：基于 120 日相对分位。
    命中 = 位置 ∈ {凹底, 低位, 中位}（位置决定性质，第4章）
    排除 = 过峰（过峰通常已脱离有效区间）

    依据：量学第4章"位置决定性质"——任何信号都要在正确位置才有效。
    """
    pos = day_row.get("位置", "")
    return pos in ("凹底", "低位", "中位")


# ============ 第六步 4c 定稿：信号定性 + 统一备注 ============
# 第六步 4c 配对检验收敛：系统定位=描述性工具+弱势提示，
# 所有信号扣随机基线后无 +5pp 正增量，不作交易决策依据，仅作看盘辅助。
SIGNAL_DISCLAIMER = "[参考信息，非交易信号；相对随机日增量<5pp，仅作看盘辅助]"

def classify_signal_4c(stage: str, pos: str = "", strength: str = "") -> str:
    """
    按第六步 4c 五组定性表，给信号定性（仅作看盘提示，不作交易依据）。
    符号比为主、中位数标幅度（|值|≥5pp=显著）。
    返回定性字符串；调用方拼接 SIGNAL_DISCLAIMER。

    参数：
      stage    : 当前阶段（phases.py 的"当前阶段"列：建仓/洗盘/拉升/出货/无明显迹象）
      pos      : 信号日位置（120日分位：凹底/低位/中位/高位/过峰）
      strength : 四维信号强度（强/中/弱/无信号）；用于识别"0维命中"的真无信号

    映射完整性（覆盖全部 5 个阶段 × 强度）：
      出货          → 谨慎提示（全组71%负，不实时分流；牛股子集偏弱/熊横盘子集明确反向）
      拉升+高位/过峰 → 谨慎提示（弱，80%负，中位数幅度不足）
      拉升+其他位置  → 参考备注（无显著增量）
      建仓          → 中性参考备注（57%正，幅度不足，配对口径非负资产）
      洗盘          → 参考备注（中性）
      无明显迹象    → 无明确信号（阶段无迹象，不预测方向）
      任意阶段+0维命中（strength=无信号）→ 无明确信号（0维命中，不预测）
      兜底（未知stage）→ 参考备注
    """
    # "无明显迹象"阶段 → 无明确信号（阶段本就不预测方向）
    # 注意：此分支须在 0 维命中判断之前，因"无明显迹象"阶段 raw_strength 恒为"无信号"
    if stage == "无明显迹象":
        return "无明确信号（阶段无迹象，不预测方向）"

    # 其他阶段 + 0 维命中（四维全未命中）→ 不算真信号，4c 配对检验的对象是"有信号"
    if strength == "无信号":
        return "无明确信号（阶段有迹象但0维命中，不预测）"

    if stage == "出货":
        # 4c 全组出货符号比71%负(258牛股弱倾向/110熊横盘明确反向)，引擎不实时分流个股牛熊。
        # 决策(用户定论)：不分流，文案讲清"全组偏弱+不分流事实"，避免误导成引擎已分组。
        return ("谨慎提示（出货全组：符号比71%负，中位数偏负；"
                "不实时分流个股牛熊，牛股子集偏弱/熊横子集明确反向）")
    if stage == "拉升" and pos in ("高位", "过峰"):
        return "谨慎提示（弱：拉升高位 80%负，中位数幅度不足）"
    if stage == "拉升":
        return "参考备注（拉升 无显著增量）"
    if stage == "建仓":
        # 配对口径：57%正/中位数+0.72pp 幅度不足 → 中性（非负资产，绝对值口径才是负资产）
        return "中性参考备注（建仓 57%正，幅度不足）"
    if stage == "洗盘":
        return "参考备注（洗盘 中性，无显著增量）"
    # 兜底：未知 stage
    return "参考备注"


# ============ 主流程：信号判定 ============
def compute_signals(phase_log: pd.DataFrame,
                    index_ma_cache: dict,
                    lhb_cache: dict,
                    daily_cache: dict = None,
                    float_shares_cache: dict = None,
                    market_state_cache: dict = None) -> pd.DataFrame:
    """
    接收 phase_log，逐日判定 5 维信号，输出 signal_log。

    参数：
      phase_log          : phases.py 产出的 DataFrame
      index_ma_cache     : {(code, date): bool} 大盘 MA20 向上缓存
      lhb_cache          : {code: DataFrame} 各股龙虎榜数据
      daily_cache        : {code: (df, turnover_series)} 日线 + 换手率序列缓存
                           （dim_wash 需要；None 时第5维降级 unknown）
      float_shares_cache : {code: int} 流通股本缓存
      market_state_cache : {date_str: bull/bear/sideways} 市场状态缓存（dim_wash 备注用）

    返回：
      signal_log DataFrame（含 5 个新列：wash_level, wash_reason, need_l2,
                         信号强度(已调整), 备注(已调整)）
    """
    cols = ["日期", "代码", "名称", "阶段", "信号", "置信度",
            "信号依据", "触发时间", "信号强度", "备注", "信号定性",
            "wash_level", "wash_reason", "need_l2",
            "位置", "量价配合", "量柱形态"]
    out = []

    for _, r in phase_log.iterrows():
        stage = r["当前阶段"]
        code = str(r["代码"]).zfill(6)
        name = r["名称"]
        date_str = str(r["日期"])

        # ---- 4 维独立判定 ----
        dim1 = dim_volume_price(r)
        dim2 = dim_market(index_ma_cache.get((code, date_str), False), r)
        lhb_df = lhb_cache.get(code)
        dim3 = dim_lhb(code, date_str, lhb_df)
        dim4 = dim_position(r)

        # 命中数（4维；dim_wash 是第5维，不参与评分，只做剔除/降级）
        hits = [d for d in (dim1, dim2, dim3, dim4) if d is True]
        n_hits = len(hits)

        # 原始信号强度
        if stage == "无明显迹象":
            raw_strength = "无信号"
            signal = "无明显迹象"
        else:
            if n_hits >= SIGNAL_THRESHOLDS["强信号"]:
                raw_strength = "强信号"
            elif n_hits >= SIGNAL_THRESHOLDS["中信号"]:
                raw_strength = "中信号"
            elif n_hits >= SIGNAL_THRESHOLDS["弱信号"]:
                raw_strength = "弱信号"
            else:
                raw_strength = "无信号"
            signal = stage

        # 信号依据（4维命中说明）
        reasons = []
        if dim1:
            reasons.append("量价形态")
        if dim2:
            reasons.append("大盘共振")
        if dim3 is True:
            reasons.append("龙虎榜")
        if dim4:
            reasons.append("位置确认")
        reason_str = "+".join(reasons) if reasons else "无维度命中"

        # ---- 第5维：对倒识别（dim_wash）----
        wash_level = "unknown"
        wash_reason = "日线缓存未加载，未判定"
        need_l2 = False
        if daily_cache is not None and code in daily_cache:
            df_daily, turnover_series = daily_cache[code]
            date_col = df_daily["日期"].astype(str)
            date_idx = df_daily.index[date_col.str.startswith(date_str)]
            if len(date_idx) > 0:
                i = date_idx[0]
                fsh = float_shares_cache.get(code) if float_shares_cache else None
                wash_result = dim_wash(df_daily, i, code, turnover_series, fsh)
                wash_level = wash_result["wash_level"]
                wash_reason = wash_result["reason"]
                need_l2 = wash_result.get("need_l2", False)

        # 应用 wash 调整
        notes = []
        if dim3 is None:
            notes.append("龙虎榜降级(接口失败)")
        if not FUND_FLOW_AVAILABLE_NOTE:
            notes.append("资金流向缺失")
        note_str = "; ".join(notes) if notes else ""

        new_strength, new_note, _action = apply_wash_adjustment(
            raw_strength, wash_level, wash_reason, note_str,
            stage=stage,
            market_state=(market_state_cache or {}).get(date_str, "sideways")
        )

        # 第六步 4c：信号定性 + 统一备注（描述性工具，非交易信号）
        pos_val = r.get("位置", "")
        # raw_strength=原始四维强度（0维命中=无信号），传给 classify 识别"无明确信号"
        signal_class = classify_signal_4c(stage, pos_val, raw_strength)
        # 统一备注：把免责声明拼到"备注"列末尾。
        # [无信号也加免责，为口径统一，不代表"无信号"是负面信息]
        base_note = new_note if new_note else ""
        final_note = (base_note + "; " if base_note else "") + SIGNAL_DISCLAIMER

        out.append({
            "日期": date_str,
            "代码": code,
            "名称": name,
            "阶段": stage,
            "信号": signal,
            "置信度": r.get("置信度", 0.0),
            "信号依据": reason_str,
            "触发时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "信号强度": new_strength,
            "备注": final_note,
            "信号定性": signal_class,
            "wash_level": wash_level,
            "wash_reason": wash_reason,
            "need_l2": need_l2,
            "位置": r.get("位置", ""),
            "量价配合": r.get("量价配合", ""),
            "量柱形态": r.get("量柱形态", ""),
        })

    return pd.DataFrame(out, columns=cols)


# ============ 龙虎榜数据加载 ============
def load_lhb_cache(codes: list) -> dict:
    """
    预加载各股票的龙虎榜历史数据到缓存（只读 SQLite 表，不触发网络请求）。
    表不存在（未初始化）的 code 置为空 DataFrame，维度3自动降级为"未上榜"。
    返回：{code: DataFrame 或 None}
      - DataFrame：该股票龙虎榜记录（可能为空）
      - None：表存在但读取失败
    """
    cache = {}
    for code in codes:
        tbl = f"lhb_{code.lower().lstrip('shszbj')}"
        try:
            conn = sqlite3.connect(DB_PATH)
            df = pd.read_sql_query(
                f"SELECT * FROM {tbl} ORDER BY 上榜日", conn)
            conn.close()
            cache[code] = df  # 表存在，可能为空
        except Exception:
            # 表不存在（未初始化龙虎榜历史），置空 DataFrame → 维度3 判定"未上榜"
            cache[code] = pd.DataFrame(columns=["代码", "上榜日"])
    return cache


# ============ 大盘 MA 缓存 ============
def build_index_ma_cache(phase_log: pd.DataFrame) -> dict:
    """
    预计算 phase_log 中每个 (code, date) 对应的大盘 MA20 向上状态。
    优化：大盘是共享的，只拉一次指数数据，预计算所有 unique 日期。
    """
    cache = {}
    try:
        idx = fetch_index_daily("sh000001", limit=500)
        if idx.empty:
            return cache
        idx = idx.sort_values("day")
        idx["ma20"] = idx["close"].rolling(20, min_periods=1).mean()
        # 预计算每个日期的 MA20 是否向上
        ma_by_date = {}
        for i in range(1, len(idx)):
            d_str = idx["day"].iloc[i].strftime("%Y-%m-%d")
            ma_by_date[d_str] = bool(idx["ma20"].iloc[i] > idx["ma20"].iloc[i - 1])
        # 同一日期的大盘状态对所有个股共享
        unique_dates = sorted(set(phase_log["日期"].astype(str).unique()))
        for date_str in unique_dates:
            up = ma_by_date.get(date_str, False)
            for code in phase_log["代码"].unique():
                cache[(code, date_str)] = up
        return cache
    except Exception as e:
        warnings.warn(f"[build_index_ma_cache] 大盘MA计算失败: {e}")
        return cache


# ============ 日线 + 换手率缓存（dim_wash 用）============
def build_daily_cache(codes: list, phase_log: pd.DataFrame = None,
                      stock_list: dict = None) -> tuple:
    """
    预加载日线数据 + 换手率序列 + 流通股本，供 dim_wash 使用。

    参数：
      codes        : 股票代码列表
      stock_list   : {code: name} 映射（用于显示）

    返回：
      daily_cache      : {code: (df_daily, turnover_series)}
                         df_daily 含 '位置' 列（phases.py 产出）
                         turnover_series 含 '日换手率','前60日均值' 列
      float_shares_cache : {code: int}

    说明：
      - 日线从 SQLite 读取（data_fetcher 已落库），不触发网络请求
      - '位置' 列需要 phases.py 已算好并写入 phase_log，这里从 phase_log 带过来
      - 流通股本调用 get_float_shares（东财 push2，带缓存）
    """
    daily_cache = {}
    float_shares_cache = {}
    for code in codes:
        try:
            conn = sqlite3.connect(DB_PATH)
            tbl = f"daily_{code}"
            df = pd.read_sql_query(f"SELECT * FROM {tbl} ORDER BY 日期", conn)
            conn.close()
            # 把 phase_log 的位置/量柱形态等列 merge 进来（判据2 需要位置）
            if phase_log is not None:
                sub = phase_log[phase_log["代码"].astype(str).str.zfill(6) == code]
                if not sub.empty and "位置" in sub.columns:
                    # 按日期对齐（phase_log 日期格式 YYYY-MM-DD，日线日期可能带时间戳）
                    df["日期_str"] = df["日期"].astype(str).str[:10]
                    pos_map = sub.set_index(sub["日期"].astype(str).str[:10])["位置"].to_dict()
                    df["位置"] = df["日期_str"].map(pos_map).fillna("未知")
                    if "量柱形态" in sub.columns:
                        df["量柱形态"] = df["日期_str"].map(
                            sub.set_index(sub["日期"].astype(str).str[:10])["量柱形态"].to_dict()
                        ).fillna("")
            # 流通股本
            fsh = get_float_shares(code)
            if fsh is not None:
                float_shares_cache[code] = fsh
                turnover = compute_turnover_series(code, df, fsh)
            else:
                turnover = None
            daily_cache[code] = (df, turnover)
        except Exception as e:
            warnings.warn(f"[build_daily_cache] {code} 加载失败: {e}")
            daily_cache[code] = (None, None)
    return daily_cache, float_shares_cache


# ============ 市场状态缓存（dim_wash 备注用）============
def build_market_state_cache(phase_log: pd.DataFrame) -> dict:
    """
    预计算每个日期对应的市场状态（bull/bear/sideways）。
    基于上证指数收盘 vs MA20 × 偏离度（dim_wash.compute_market_state）。
    返回：{date_str: state}
    """
    try:
        idx = fetch_index_daily("sh000001", limit=500)
        if idx.empty:
            return {}
        idx = idx.sort_values("day").reset_index(drop=True)
        state = compute_market_state(idx.rename(columns={"close": "收盘"}))
        cache = {}
        for i, d in enumerate(idx["day"]):
            cache[d.strftime("%Y-%m-%d")] = state.iloc[i]
        return cache
    except Exception as e:
        warnings.warn(f"[build_market_state_cache] 市场状态计算失败: {e}")
        return {}


# ============ 主入口 ============
def run_signal_engine(stock_list: dict = None,
                      output_path: str = SIGNAL_LOG_PATH) -> pd.DataFrame:
    """
    主入口：跑阶段识别 → 4维信号判定 → 输出 signal_log.csv
    """
    if stock_list is None:
        stock_list = STOCKS_4

    print(f"\n{'='*60}")
    print(f">>> 信号引擎：{len(stock_list)} 只股票")
    print(f"{'='*60}")

    # 1) 先跑阶段识别
    from phases import run_all as run_phases
    phase_log = run_phases(stock_list=stock_list, output_path=PHASE_LOG_PATH,
                           verbose=False)
    if phase_log.empty:
        print("phase_log 为空，无法生成信号")
        return pd.DataFrame()

    # 2) 预加载龙虎榜
    print("  加载龙虎榜数据...")
    lhb_cache = load_lhb_cache(list(stock_list.keys()))
    print(f"  龙虎榜缓存: {sum(1 for v in lhb_cache.values() if v is not None)}"
          f"/{len(lhb_cache)} 只")

    # 3) 预计算大盘 MA 缓存 + 市场状态
    print("  计算大盘 MA20 缓存...")
    index_ma_cache = build_index_ma_cache(phase_log)
    n_up = sum(1 for v in index_ma_cache.values() if v)
    print(f"  大盘 MA 向上: {n_up}/{len(index_ma_cache)} 天")

    print("  计算市场状态缓存（dim_wash 备注用）...")
    market_state_cache = build_market_state_cache(phase_log)
    from collections import Counter as _CC
    mkt_dist = _CC(market_state_cache.values())
    print(f"  市场状态: " + " ".join(f"{k}={v}" for k, v in mkt_dist.items()))

    # 4) 逐日判定信号
    print("  加载日线 + 换手率缓存（dim_wash 用）...")
    daily_cache, float_shares_cache = build_daily_cache(
        list(stock_list.keys()), phase_log=phase_log, stock_list=stock_list)
    n_wash = sum(1 for v in daily_cache.values() if v[1] is not None)
    print(f"  日线缓存: {len(daily_cache)} 只, 含换手率序列: {n_wash} 只")

    print("  判定 5 维信号...")
    t0 = time.time()
    signal_log = compute_signals(phase_log, index_ma_cache, lhb_cache,
                                 daily_cache, float_shares_cache,
                                 market_state_cache=market_state_cache)
    print(f"  完成, 耗时 {time.time()-t0:.1f}s, 共 {len(signal_log)} 条")

    # 5) 输出
    # 可复现性修复（2026-09-17）：输出强制按 (代码,日期) 排序，行序与跑的次数/进程无关
    signal_log = signal_log.sort_values(["代码", "日期"]).reset_index(drop=True)
    signal_log.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n{'='*60}")
    print(f"信号日志已写入: {output_path}")
    print(f"总记录数: {len(signal_log)}")
    print(f"强信号 {int((signal_log['信号强度']=='强信号').sum())} 条, "
          f"中信号 {int((signal_log['信号强度']=='中信号').sum())} 条, "
          f"弱信号 {int((signal_log['信号强度']=='弱信号').sum())} 条, "
          f"无信号 {int((signal_log['信号强度']=='无信号').sum())} 条")

    # dim_wash 统计
    if "wash_level" in signal_log.columns:
        print(f"\n--- dim_wash 命中分布 ---")
        for lvl in ["confirmed", "suspicious", "unknown", "normal"]:
            cnt = int((signal_log["wash_level"] == lvl).sum())
            print(f"  {lvl:<12} {cnt} 条")
    return signal_log


if __name__ == "__main__":
    run_signal_engine()
