#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
对倒识别引擎 (dim_wash)
========================
作为 signal_engine.py 的第 5 个维度。

原著依据（每条判据注释中引用）：
  - 第1章「庄在散先」：对倒本质是主力诱导散户，需识别主力意图
  - 第5章「张扬高倍阳是诱多」：高位放量的"强势"可能是诱多
  - 第22章「高位主动买量大是对倒出货」：高位放量滞涨是典型对倒
  - 第23章「算法拆单时代大单≠主力」：日线层只能近似，需 Level-2 数据确认

Level-2 备注（本模块日线层不实现，仅在返回值标注 need_l2）：
  - 主动买卖方向（撤单率 / 主动性买量占比）
  - 挂单撤单识别
  - 聪明钱模型

换手率计算（方案②）：
  日换手率 = 当日成交量（手）× 100 ÷ 流通股本（股）× 100%
  流通股本：东财 push2 f85 字段，拉一次缓存
  [工程近似：用当前流通股本反推历史换手率，股本变动期间有偏差]

四档判定优先级：confirmed > suspicious > unknown > normal
  confirmed  → 判据2命中（高位放量滞涨）→ 剔除信号
  suspicious → 判据1或3命中 → 信号强度降一级
  unknown    → 判据1/3 换手率数据缺失 → 备注"换手率缺失，未判定"
  normal     → 其余 → 不动
"""
import json
import re
import sqlite3
import time
import warnings
from typing import Optional

import pandas as pd

from data_fetcher import DB_PATH

# ============ 全局配置 ============
# 流通股本缓存（东财 push2 f85，运行时拉一次）
_float_shares_cache: dict = {}

# 东方财富 push2 接口配置
_EM_PUSH2_URL = "https://push2.eastmoney.com/api/qt/stock/get"
_EM_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Referer": "https://quote.eastmoney.com/",
}

# 判据阈值（主板 = 60/00 开头，创业板/科创板 = 30/68 开头）
# [工程参数，需回测校准]
_THRESHOLDS = {
    "main": {  # 主板（60/00 开头）
        "abs_low": 5.0,    # 判据1 绝对下限（日换手率 %）
        "abs_high": 15.0,  # 判据1 绝对上限（日换手率 %）
        "rel_mult": 2.5,   # 判据1 相对倍率（60日均值 × 2.5）
        "c3_abs": 15.0,    # 判据3 绝对下限（日换手率 %）
        "c3_rel": 5.0,     # 判据3 相对倍率（60日均值 × 5）
    },
    "growth": {  # 创业板/科创板（30/68 开头），阈值 × 1.5
        "abs_low": 7.5,
        "abs_high": 22.5,
        "rel_mult": 2.5,
        "c3_abs": 22.5,
        "c3_rel": 5.0,
    },
}

# 判据2 参数（日线可做，不需换手率）
_C2_PARAMS = {
    "pos_high": ("高位", "过峰"),  # 位置 = 高位或过峰（复用 phases.py 位置字段）
    "chg_pct": 0.5,      # 逐日涨幅阈值（前一日 AND 当日，各自 < 0.5%）
    "vol_mult": 1.5,     # 量 > 1.5 × 20日均量
    "vol_window": 20,   # 均量窗口（交易日）
}

# 判据1 涨跌幅阈值
_C1_PCT = 2.0  # |当日涨跌幅| < 2%

# ============ 阶段/位置门槛（dim_wash 是保护层：宁漏不误杀，保护出货、不反噬拉升）============
# 修正1：判据1/3 只在"非吸筹区"触发——位置∈{中位,高位,过峰} 才触发；凹底/低位 是吸筹区，不判对倒
_WASH_POS_GATE = ("中位", "高位", "过峰")

# 修正2：confirmed（判据2命中）按阶段分流
#   出货/无明显迹象 → 剔除（真对倒出货）
#   拉升/洗盘/建仓  → 只降一级（保护真拉升，主升浪中继洗盘不是对倒）
_CONFIRM_REMOVE_STAGES = ("出货", "无明显迹象")

# 修正3：suspicious（判据1/3命中）按阶段分流
#   拉升/洗盘/建仓  → 只备注"疑似对倒"，不降级（保护真信号）
#   出货/无明显迹象 → 降一级（疑似对倒，降级提示）
_SUSPICIOUS_DOWNGRADE_STAGES = ("出货", "无明显迹象")

# ============ 环境过滤（B' 结论：dim_wash 在"非牛市"才剔除，牛市只保护性降级）============
# 市场状态用上证指数判定（动态环境，不用个股静态分组）：
#   close > MA20 × 1.02 → "bull"
#   close < MA20 × 0.98 → "bear"
#   else                → "sideways"
# [工程参数，需回测校准]（偏离度 1.02/0.98 避免贴均线走的震荡日被误判）
_MKT_DEV_UP = 1.02   # 牛市偏离度
_MKT_DEV_DN = 0.98   # 熊市偏离度

# 环境 × wash_level → 动作（修正3：dim_wash 动作改为"环境相关"）
#   bull    : confirmed→downgrade(保护), suspicious→note_only(保护)
#   bear    : confirmed→remove(剔除),     suspicious→downgrade(降级)
#   sideways: confirmed→remove(剔除),     suspicious→downgrade(降级)
_ENV_ACTIONS = {
    "bull":     {"confirmed": "downgrade", "suspicious": "note_only"},
    "bear":     {"confirmed": "remove",     "suspicious": "downgrade"},
    "sideways": {"confirmed": "remove",     "suspicious": "downgrade"},
}


def _is_growth(code: str) -> bool:
    """
    判断是否为创业板/科创板（30/68 开头）。
    [工程参数，需回测校准]
    """
    return code[:2] in ("30", "68")


def _get_thresholds(code: str) -> dict:
    """根据代码前缀返回对应阈值组。"""
    return _THRESHOLDS["growth"] if _is_growth(code) else _THRESHOLDS["main"]


def _em_push2_float_shares(code: str, retries: int = 3, delay: float = 2.0) -> Optional[int]:
    """东财 push2 f85，带重试（通道不稳定，已观测到 RemoteDisconnected）。"""
    prefix = "1." if code[0] in ("5", "6") else "0."
    secid = f"{prefix}{code}"
    import requests
    for attempt in range(1, retries + 1):
        try:
            r = requests.get(
                _EM_PUSH2_URL,
                params={"secid": secid, "fields": "f84,f85"},
                headers=_EM_HEADERS,
                timeout=15,
            )
            data = r.json().get("data", {}) or {}
            f85 = data.get("f85")
            if f85 is not None:
                return int(float(f85))
            # f85 为空，重试
            if attempt < retries:
                time.sleep(delay)
                continue
            return None
        except Exception:
            if attempt < retries:
                time.sleep(delay)
                continue
            return None
    return None


def _tx_qt_float_shares(code: str) -> Optional[int]:
    """
    腾讯 qt.gtimg.cn 备用通道。
    [工程近似] 用腾讯实时接口 [44]流通市值(亿) / [3]现价 × 1e8 反推流通股本。
    仅在东财 push2 全部失败时启用。
    """
    import requests
    tx_code = ("sh" if code[0] in ("5", "6") else "sz") + code
    try:
        r = requests.get(f"https://qt.gtimg.cn/q={tx_code}", timeout=15)
        r.encoding = "gbk"
        f = r.text.split("~")
        if len(f) > 46:
            price = float(f[3])       # 现价
            liutong_mv = float(f[44]) # 流通市值(亿元)
            if price > 0:
                return int(liutong_mv * 1e8 / price)
        return None
    except Exception:
        return None


def get_float_shares(code: str) -> Optional[int]:
    """
    获取流通股本（股），双通道容错。
    主通道：东财 push2 f85（带 3 次重试，通道不稳定已观测）
    备通道：腾讯 qt.gtimg.cn [44]流通市值/[3]现价 反推
    结果缓存到 _float_shares_cache，同一进程内只拉一次。

    返回：
      int   流通股本（股）
      None  获取失败（降级，dim_wash 返回 unknown）

    [工程近似：用当前流通股本反推历史换手率，股本变动期间有偏差]
    """
    if code in _float_shares_cache:
        return _float_shares_cache[code]

    # 主通道：东财 push2（重试 3 次）
    shares = _em_push2_float_shares(code, retries=3, delay=2.0)
    if shares is not None:
        _float_shares_cache[code] = shares
        return shares

    # 备通道：腾讯
    shares = _tx_qt_float_shares(code)
    if shares is not None:
        _float_shares_cache[code] = shares
        return shares

    _float_shares_cache[code] = None
    return None


def compute_turnover_series(code: str, df: pd.DataFrame,
                            float_shares: int) -> pd.DataFrame:
    """
    计算整只股票的历史换手率序列 + 前60日均值。

    参数：
      code         : 股票代码（6位，如 '601138'）
      df           : 日线 DataFrame（含 '日期','成交量' 列，按日期升序）
      float_shares : 流通股本（股）

    返回：
      与 df 同索引的 DataFrame，列：
        '日换手率'      : 当日换手率（%）
        '前60日均值'    : 前60个交易日换手率均值（%），rolling(60).mean().shift(1)

    [工程近似：用当前流通股本反推历史换手率，股本变动期间有偏差]
    说明：rolling(60).mean().shift(1) 保证窗口为 [i-60, i-1]，不含当日 i，避免未来函数。
    """
    out = df.reset_index(drop=True).copy()
    # 成交量单位为手（1手=100股）
    out["日换手率"] = out["成交量"] * 100 / float_shares * 100  # %
    # 前60日均值：rolling(60).mean() 取 [i-59, i] 的均值，shift(1) → [i-60, i-1]
    out["前60日均值"] = out["日换手率"].rolling(60, min_periods=60).mean().shift(1)
    return out


def _prev_20day_avg_vol(df: pd.DataFrame, i: int, window: int = 20) -> Optional[float]:
    """
    计算前 window 个交易日的平均成交量（不含当日 i）。
    返回 None 表示数据不足（降级）。
    """
    if i < window:
        return None
    vol_series = df["成交量"].iloc[i - window:i]
    return float(vol_series.mean())


def _get_prev_day_chg(df: pd.DataFrame, i: int) -> Optional[float]:
    """
    获取第 i 行相对第 i-1 行的涨跌幅（%）。即"当日 i 相对前一日 i-1"。
    需要 i>=1。
    返回 None 表示数据不足。
    """
    if i < 1:
        return None
    prev_close = float(df["收盘"].iloc[i - 1])
    if prev_close == 0:
        return None
    curr_close = float(df["收盘"].iloc[i])
    return (curr_close - prev_close) / prev_close * 100


def dim_wash(df: pd.DataFrame, i: int, code: str,
             turnover_series: Optional[pd.DataFrame],
             float_shares: Optional[int]) -> dict:
    """
    对倒识别引擎：判断当日是否存在对倒出货/诱多迹象。

    参数：
      df               : 该股日线 DataFrame（按日期升序，含 日期/开盘/收盘/最高/最低/成交量/成交额）
      i                : 当前行索引（0-based）
      code             : 股票代码（6位字符串）
      turnover_series  : compute_turnover_series 的输出（含 '日换手率','前60日均值' 列）
                         为 None 时，判据1/3 降级为 unknown
      float_shares     : 流通股本（股），None 时判据1/3 降级为 unknown

    返回：
      {
        "wash_level": "confirmed" | "suspicious" | "unknown" | "normal",
        "reason"    : 判定原因（可追溯字符串）
        "need_l2"   : True（日线层无法确认，需 Level-2 数据）
      }

    优先级：confirmed > suspicious > unknown > normal
    """
    need_l2 = True  # 日线层无法确认主动买卖方向，需 Level-2

    # ---- 判据2：高位放量滞涨（日线可做，不需换手率）----
    c2_hit, c2_reason = _check_criterion2(df, i, code)

    if c2_hit:
        return {
            "wash_level": "confirmed",
            "reason": c2_reason,
            "need_l2": need_l2,
        }

    # ---- 判据1/3 需要换手率数据 ----
    if turnover_series is None or float_shares is None or i >= len(turnover_series):
        # 换手率数据缺失 → unknown（无论判据2是否命中，判据2已先判过）
        return {
            "wash_level": "unknown",
            "reason": "换手率缺失，未判定 [工程近似：用当前流通股本反推历史换手率]",
            "need_l2": need_l2,
        }

    hs = float(turnover_series["日换手率"].iloc[i])        # 当日换手率
    hs_avg60 = turnover_series["前60日均值"].iloc[i]        # 前60日均值（可能为 NaN）
    # 若前60日均值 NaN（数据不足），相对判据不可用，只判绝对
    hs_avg60_valid = not pd.isna(hs_avg60) if hs_avg60 is not None else False

    c1_hit, c1_reason = _check_criterion1(code, hs, hs_avg60, hs_avg60_valid, df, i)
    c3_hit, c3_reason = _check_criterion3(code, hs, hs_avg60, hs_avg60_valid, df, i)

    if c1_hit or c3_hit:
        reasons = []
        if c1_hit:
            reasons.append(f"判据1(高换手横盘): {c1_reason}")
        if c3_hit:
            reasons.append(f"判据3(高量柱+高换手): {c3_reason}")
        return {
            "wash_level": "suspicious",
            "reason": "; ".join(reasons),
            "need_l2": need_l2,
        }

    return {
        "wash_level": "normal",
        "reason": "无对倒迹象",
        "need_l2": need_l2,
    }


def _check_criterion2(df: pd.DataFrame, i: int, code: str) -> tuple:
    """
    判据2：高位放量滞涨。

    "滞涨" = 价格基本不动（两日累计 |涨幅| < 1%），不是"下跌"。
    放量下跌（负涨幅）是出货，不是对倒——必须排除。

    条件（三条件全部命中）：
      1. 位置 = 高位或过峰（复用 phases.py 位置字段，第4章"位置决定性质"）
      2. 两日累计 |涨幅| < 1%（第22章工程近似）
         累计涨幅 = (1+前一日涨幅/100)×(1+当日涨幅/100) - 1
         真对倒在高位是"原地踏步多日"，不必要求每一天都<0.5%。
      3. 当日量 > 1.5 × 20日均量（第5章"张扬高倍阳是诱多"工程近似）

    [工程参数，非原著]
    原著依据：
      - 第22章「高位主动买量大是对倒出货」
      - 第5章「张扬高倍阳是诱多」
      - 第4章「位置决定性质」
    """
    p = _C2_PARAMS
    # 1) 位置检查：从 df 当日行取位置字段（phases.py 写入的）
    # df 在 signal_engine 中由 phases.py 产出，含 '位置' 列
    pos = str(df["位置"].iloc[i]) if "位置" in df.columns else ""
    if pos not in p["pos_high"]:
        return (False, f"判据2位置={pos}，非高位/过峰，跳过")

    # 2) 前一日涨幅 + 当日涨幅（各自 < 0.5%）
    #    当日涨幅（i 相对 i-1）= _get_prev_day_chg(df, i)
    #    前一日涨幅（i-1 相对 i-2）= _get_prev_day_chg(df, i-1)
    if i < 2:
        return (False, "判据2数据不足（需至少3个交易日）")
    curr_chg = _get_prev_day_chg(df, i)        # 当日 i 相对 i-1
    prev_chg = _get_prev_day_chg(df, i - 1)    # 前一日 i-1 相对 i-2
    if curr_chg is None or prev_chg is None:
        return (False, "判据2数据不足（涨幅不可用）")

    # 两日累计涨幅 = (1+prev/100)×(1+curr/100) - 1，再取绝对值 < 1%
    cumulative = (1 + prev_chg / 100) * (1 + curr_chg / 100) - 1
    if not (abs(cumulative) < 1.0):
        return (False, f"判据2累计涨幅不满足：前一日{prev_chg:+.2f}% 当日{curr_chg:+.2f}% → 累计{cumulative:+.2f}%，需|累计|<1%")

    # 3) 量 > 1.5 × 20日均量
    avg_vol = _prev_20day_avg_vol(df, i, p["vol_window"])
    if avg_vol is None:
        return (False, "判据2数据不足（20日均量不可用）")
    curr_vol = float(df["成交量"].iloc[i])
    if curr_vol > p["vol_mult"] * avg_vol:
        reason = (
            f"判据2命中：位置={pos}，前一日{prev_chg:+.2f}% 当日{curr_chg:+.2f}% → 累计{cumulative:+.2f}%（滞涨），"
            f"量{curr_vol:.0f}>{p['vol_mult']}×20日均{avg_vol:.0f} "
            f"[第22章高位对倒出货，第5章诱多，第4章位置决定性质]"
        )
        return (True, reason)
    else:
        return (False, f"判据2量不满足：{curr_vol:.0f}≤{p['vol_mult']}×{avg_vol:.0f}")


def _check_criterion1(code: str, hs: float, hs_avg60, hs_avg60_valid: bool,
                      df: pd.DataFrame, i: int) -> tuple:
    """
    判据1：高换手横盘。

    命中 = (绝对阈值 OR 相对阈值) AND |当日涨跌幅| < 2%

    绝对阈值 [工程参数，需回测校准]：
      主板：日换手率 ∈ [5%, 15%]
      创/科：日换手率 ∈ [7.5%, 22.5%]

    相对阈值 [工程参数，需回测校准]：
      日换手率 > 前60日均值 × 2.5

    原著依据：
      - 第1章「庄在散先」：高换手横盘是主力对倒诱多的典型特征
      - 第23章「算法拆单时代大单≠主力」：日线层只能近似
    """
    th = _get_thresholds(code)

    # 修正1：位置门槛——吸筹区（凹底/低位）不判对倒（第1章"庄在散先"：低位放量是吸筹非对倒）
    pos = str(df["位置"].iloc[i]) if "位置" in df.columns else ""
    if pos not in _WASH_POS_GATE:
        return (False, f"判据1位置={pos}∈吸筹区，不触发（只在中位/高位/过峰判对倒）")

    abs_hit = th["abs_low"] <= hs <= th["abs_high"]
    rel_hit = hs_avg60_valid and hs_avg60 > 0 and hs > th["rel_mult"] * hs_avg60

    if not (abs_hit or rel_hit):
        return (False, f"判据1换手率{hs:.2f}%未命中（绝对{th['abs_low']}~{th['abs_high']}%，"
                       f"相对>{th['rel_mult']}×60日均）")

    # 检查涨跌幅
    chg = _get_prev_day_chg(df, i)
    if chg is None:
        return (False, "判据1数据不足（当日涨跌幅不可用）")
    if abs(chg) < _C1_PCT:
        trigger = "绝对" if abs_hit else "相对"
        reason = (
            f"判据1命中({trigger})：日换手率{hs:.2f}%，"
            f"前60日均值{hs_avg60:.2f}%{'(有效)' if hs_avg60_valid else '(数据不足,用绝对)'}，"
            f"|当日涨跌幅|{abs(chg):.2f}%<{_C1_PCT}% "
            f"[第1章庄在散先，第23章日线近似]"
        )
        return (True, reason)
    else:
        return (False, f"判据1换手率命中但|涨跌幅|{abs(chg):.2f}%≥{_C1_PCT}%，跳过")


def _check_criterion3(code: str, hs: float, hs_avg60, hs_avg60_valid: bool,
                      df: pd.DataFrame, i: int) -> tuple:
    """
    判据3：高量柱+高换手。

    命中 = (绝对 OR 相对) AND 量能 > 2.5×均量

    绝对阈值 [工程参数，需回测校准]：
      主板：日换手率 > 15%
      创/科：日换手率 > 22.5%

    相对阈值 [工程参数，需回测校准]：
      日换手率 > 前60日均值 × 5

    量能条件：当日量 > 2.5 × 20日均量

    原著依据：
      - 第5章「张扬高倍阳是诱多」
      - 第22章「高位主动买量大是对倒出货」
      - 第1章「庄在散先」
    """
    th = _get_thresholds(code)

    # 修正1：位置门槛——吸筹区（凹底/低位）不判对倒（与判据1 一致）
    pos = str(df["位置"].iloc[i]) if "位置" in df.columns else ""
    if pos not in _WASH_POS_GATE:
        return (False, f"判据3位置={pos}∈吸筹区，不触发（只在中位/高位/过峰判对倒）")

    abs_hit = hs > th["c3_abs"]
    rel_hit = hs_avg60_valid and hs_avg60 > 0 and hs > th["c3_rel"] * hs_avg60

    if not (abs_hit or rel_hit):
        return (False, f"判据3换手率{hs:.2f}%未命中（绝对>{th['c3_abs']}%，"
                       f"相对>{th['c3_rel']}×60日均）")

    # 量能条件
    avg_vol = _prev_20day_avg_vol(df, i, _C2_PARAMS["vol_window"])
    if avg_vol is None:
        return (False, "判据3数据不足（20日均量不可用）")
    curr_vol = float(df["成交量"].iloc[i])
    vol_mult = 2.5
    if curr_vol > vol_mult * avg_vol:
        trigger = "绝对" if abs_hit else "相对"
        reason = (
            f"判据3命中({trigger})：日换手率{hs:.2f}%>绝对{th['c3_abs']}%"
            f"{'或相对>' + str(th['c3_rel']) + '×60日均' if rel_hit else ''}，"
            f"量{curr_vol:.0f}>{vol_mult}×20日均{avg_vol:.0f} "
            f"[第5章诱多，第22章高位对倒]"
        )
        return (True, reason)
    else:
        return (False, f"判据3换手率命中但量{curr_vol:.0f}≤{vol_mult}×{avg_vol:.0f}，跳过")


def compute_market_state(index_df: pd.DataFrame) -> pd.Series:
    """
    计算上证指数每日的市场状态（bull/bear/sideways）。

    参数：
      index_df : 指数日线 DataFrame（含 '收盘' 列，按日期升序）

    返回：
      与 index_df 同索引的 Series，值 ∈ {"bull","bear","sideways"}

    判定 [工程参数，需回测校准]：
      close > MA20 × 1.02 → bull（牛市）
      close < MA20 × 0.98 → bear（熊市）
      else                → sideways（震荡）
    说明：偏离度 1.02/0.98 避免贴均线走的震荡日被误判为牛/熊。
    """
    ma20 = index_df["收盘"].rolling(20, min_periods=20).mean()
    state = pd.Series("sideways", index=index_df.index)
    state[index_df["收盘"] > ma20 * _MKT_DEV_UP] = "bull"
    state[index_df["收盘"] < ma20 * _MKT_DEV_DN] = "bear"
    # 前 20 个交易日 MA20 未填满（NaN）→ 归为 sideways
    state[ma20.isna()] = "sideways"
    return state


def get_market_state_by_date(index_df: pd.DataFrame) -> dict:
    """
    返回 {日期字符串(YYYY-MM-DD): 市场状态} 映射，供逐日查询。
    """
    state = compute_market_state(index_df)
    dcol = index_df["日期"].astype(str).str[:10] if "日期" in index_df.columns else index_df["d"]
    return dict(zip(dcol, state))


# ============ 信号强度降级 ============
def downgrade_strength(strength: str) -> str:
    """
    suspicious 档位：信号强度降一级。
      强信号 → 中信号
      中信号 → 弱信号
      弱信号 → 无信号
      无信号 → 无信号（不变）
    """
    ladder = {"强信号": "中信号", "中信号": "弱信号", "弱信号": "无信号", "无信号": "无信号"}
    return ladder.get(strength, "无信号")


def apply_wash_adjustment(strength: str, wash_level: str,
                          reason: str, note: str,
                          stage: str = "",
                          market_state: str = "sideways") -> tuple:
    """
    根据 dim_wash 结果 + 当前阶段 + 市场状态，写"疑似对倒"备注。

    【定稿方案 2026-09-17】dim_wash 经 30 只牛熊样本对照检验未通过
    （78 条剔除中 67 条事后优于随机基线），降级为"仅作备注"：
      - confirmed / suspicious → 不剔除、不降级，只在备注栏追加"[疑似对倒]"标注
      - unknown → 备注"换手率缺失，未判定"
      - normal → 不动

    设计原则：保留全部计算逻辑（compute_market_state / 判据1/2/3 / _ENV_ACTIONS），
    将来接入 Level-2 数据或样本扩到 60+ 只时，可一键重启"剔除/降级"动作
    （只需把下面 confirmed/suspicious 分支的 action 改回 "remove"/"downgrade" 即可）。

    参数：
      strength     : 原始信号强度（强信号/中信号/弱信号/无信号）
      wash_level   : dim_wash 返回的档位（confirmed/suspicious/unknown/normal）
      reason       : dim_wash 返回的原因（含具体判据）
      note         : 原始备注字符串
      stage        : 当前阶段（建仓/洗盘/拉升/出货/无明显迹象）
      market_state : 市场状态（bull/bear/sideways），写入备注供人工参考

    备注格式示例：
      [疑似对倒-判据2] 高位放量滞涨，环境=sideways，[日线近似，样本未显著，需人工确认]

    返回：
      (new_strength, new_note, action)
      new_strength 恒等于 传入的 strength（不改强度）
      action ∈ {"note_only", "mark_unknown", "normal"}
    """
    # 定稿方案：confirm / suspicious 均"仅写备注，不改强度"
    if wash_level in ("confirmed", "suspicious"):
        # 从 reason 里提取判据编号（判据1/2/3）
        criterion = "判据?"
        for tag in ("判据2", "判据1", "判据3"):
            if tag in reason:
                criterion = tag
                break
        wash_tag = "疑似对倒" if wash_level == "suspicious" else "确认对倒"
        append = (f"[{wash_tag}-{criterion}] {reason}，"
                  f"环境={market_state}，[日线近似，样本未显著，需人工确认]")
        new_note = f"{note}; {append}" if note else append
        # 定稿：不改强度，action=note_only
        return (strength, new_note, "note_only")

    elif wash_level == "unknown":
        new_note = f"{note}; {reason}" if note else reason
        return (strength, new_note, "mark_unknown")
    else:  # normal
        return (strength, note, "normal")
