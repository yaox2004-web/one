#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法报告 - HTML版（量能自适应版）
=================================================
【无未来函数】
【资料来源】：股海明灯《量柱擒涨停》《量线捉涨停》黑马王子著

【设计原则】
1. 核心定义保留官方（倍量/高量/低量/梯量/缩量/平量）
2. 辅助判断用分位数自适应（大量/小量/基柱要求等）
3. 所有参数全部参数化，方便调整
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 【基础路径配置】
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

HOLDINGS = [
    ("sh", "600584"),
    ("sz", "002156"),
    ("sh", "603283"),
    ("sz", "300394"),
    ("sh", "601138"),
    ("sh", "601231"),
    ("sz", "300476"),
    ("sh", "603516"),
]

# ============================================================
# 【ATR自适应总开关】
# ============================================================
ATR_ADAPTIVE = True
ATR_PERIOD = 14

# ============================================================
# 【价格类参数·ATR倍数】
# ============================================================
YIN_BODY_ATR_MULT = 1.5        # 中大阴线实体跌幅 = ATR × 1.5
YIN_BODY_FALLBACK = 5.0        # 不启用ATR时，默认5%
YIN_LOOKBACK = 60              # 往前找多少天内的中大阴线

CHANGYANG_ATR_MULT = 1.5       # 大阳线 = ATR × 1.5
CHANGYANG_FALLBACK = 5.0       # 不启用ATR时，默认5%

LONG_RANGE_ATR_MULT = 2.0      # 长价柱 = ATR × 2.0
SHORT_RANGE_ATR_MULT = 0.7     # 短价柱 = ATR × 0.7

BINGLIN_ATR_MULT = 0.5         # 兵临城下：离峰顶 < ATR × 0.5
BINGLIN_FALLBACK = 2.0         # 不启用ATR时，默认2%

LONG_LEG_ATR_MULT = 1.0        # 长腿：下影线 > ATR × 1.0
GAP_ATR_MULT = 0.5             # 跳空：缺口 > ATR × 0.5

# ============================================================
# 【量柱核心定义参数·来源：股海明灯官网】
# 这些是量学的"语言"，不要随便改！
# ============================================================
BEISHU_RATIO = 1.8             # 倍量柱：今天量/昨天量 >= 1.8（官方最低90%，放宽到1.8）
GAOLIANG_LOOKBACK = 20         # 高量柱：前多少天最高？（默认20天）
PINGLIANG_TOLERANCE = 0.15     # 平量柱：和前5天平均差不超过15%

SMALL_BEISHU_MIN = 1.5         # 小倍阳下限：1.5倍
SMALL_BEISHU_MAX = 2.0         # 小倍阳上限：2.0倍

# ============================================================
# 【量能自适应参数·分位数·来源：量化行业通用做法】
# 这些是辅助判断，用分位数自动适配每只股票
# ============================================================
VOL_LOOKBACK = 20              # 分位数计算窗口：过去多少天？（默认20天）
VOL_PCTL_HIGH = 0.80           # 大量/放量：多少分位以上？（默认80%）
VOL_PCTL_LOW = 0.20            # 小量/缩量：多少分位以下？（默认20%）
BASE_VOL_PCTL = 0.60           # 王牌柱基柱：多少分位以上？（默认60%）

BEISHUO_EXTEND_PCTL = 0.80     # 倍量伸缩：放量到多少分位？
BEISHUO_SHRINK_PCTL = 0.20     # 倍量伸缩：缩量到多少分位？
BEISHUO_LOOKBACK = 5           # 倍量伸缩：看前几天？

LONG_YIN_SHORT_VOL_PCTL = 0.30 # 长阴短柱：量在多少分位以下？（默认30%）

# ============================================================
# 【涨停板参数】
# ============================================================
LIMIT_UP_MAIN = 9.8            # 主板（60/00开头）涨停
LIMIT_UP_GEM = 19.8            # 创业板/科创板（30/68开头）涨停

# ============================================================
# 【王牌柱参数·官方定义】
# ============================================================
GENERAL_CONFIRM_DAYS = 3       # 王牌柱确认天数：3天

# ============================================================
# 【峰顶线/谷底线参数】
# ============================================================
SHORT_WINDOW = 20              # 短期窗口（交易日）
MID_WINDOW = 60                # 中期窗口（交易日）
LONG_WINDOW = 120              # 长期窗口（交易日）

PEAK_SIDE_SHORT = 2            # 短期：左右各2根
PEAK_SIDE_MID = 2              # 中期：左右各2根
PEAK_SIDE_LONG = 3             # 长期：左右各3根

CONFIRM_DAYS_SHORT = 2         # 短期确认天数
CONFIRM_DAYS_MID = 3           # 中期确认天数
CONFIRM_DAYS_LONG = 10         # 长期确认天数

VOL_PERCENTILE = 0.7           # 峰顶/谷底：量柱在前30%以上

# ============================================================
# 【量线参数】
# ============================================================
BODY_RATIO_THRESHOLD = 0.6     # 实体占比超过60%取实体顶底，否则取K线最高最低

PRECISE_MIN_POINTS = 3         # 精准线：至少3个价格点重合
PRECISE_PRICE_TOLERANCE = 1.0  # 精准线：价格相差不超过1%
PRECISE_LOOKBACK = 120         # 精准线：往前找多少天？

XIEHENG_MIN_POINTS = 2         # 斜衡线：至少2个点

BALANCE_LOOKBACK = 30          # 平衡线：往前找多少天？

# ============================================================
# 【关键位量影响力参数】
# ============================================================
IMPACT_VS_KEY_VOL_HIGH = 0.8   # 今天量 > 关键位量的80% → 影响力强
IMPACT_VS_KEY_VOL_MID = 0.5    # 今天量 > 关键位量的50% → 影响力中等

IMPACT_TIME_NEAR = 15          # 时间距离<15天 → 时间近
IMPACT_TIME_MID = 45           # 时间距离<45天 → 时间中等

# ============================================================
# 【位置分位参数】
# ============================================================
POSITION_HIGH = 70             # 位置>70%算高位
POSITION_LOW = 30              # 位置<30%算低位

VOL_POS_HIGH = 80              # 量能位置>80%算天量
VOL_POS_LOW = 20               # 量能位置<20%算地量

# ============================================================
# 【凹口线参数】
# ============================================================
AOKOU_MIN_GAP = 3              # 凹口线：最小间隔天数
AOKOU_MAX_GAP = 13             # 凹口线：最大间隔天数
AOKOU_PINGLIANG_TOLERANCE = 0.15  # 凹口线：两侧量差不超过15%
AOKOU_MIDDLE_SHADOW = 0.6      # 凹口线：中间量 < 两侧平均的60%

# ============================================================
# 【形态信号参数】
# ============================================================
TOUCH_LINE_TOLERANCE = 0.02    # 碰线容差：2%

JIYIN_PREV_DAYS = 5            # 极阴次阳：往前找5天
CIYANG_REBOUND_PCT = 50        # 极阴次阳：反弹幅度50%以上

NIUGU_LOOKBACK = 60            # 牛股三绝：往前找60天
NIUGU_TOUCH_TOLERANCE = 0.01   # 牛股三绝：碰线容差1%

DILIANG_GROUP_DAYS = 100       # 地量群：往前找100天
DILIANG_GROUP_COUNT = 5        # 地量群：至少5天地量

JIA_SHENG_LIANG_SUO_DAYS = 3   # 价升量缩：连续3天

HUICAI_PRECISION_DAYS = 10     # 回踩精准线：最近10天碰过

DOUBLE_SWORD_UPPER_RATIO = 2.0 # 双剑霸天地：上影线>实体2倍
DOUBLE_SWORD_LOWER_RATIO = 2.0 # 双剑霸天地：下影线>实体2倍

SANYUAN_DAYS = 3               # 三元连动：连续3天

DAYANG_DOUBLE_REST_DAYS = 5    # 大阳双休：大阳后5天不破中位

JIELI_DOUBLE_YANG_GAP_MIN = 5  # 接力双阳：最小间隔5天
JIELI_DOUBLE_YANG_GAP_MAX = 20 # 接力双阳：最大间隔20天

GOLD_CROSS_SHORT_MA = 5        # 黄金十字架：短期均线5天
GOLD_CROSS_LONG_MA = 10        # 黄金十字架：长期均线10天

PRECISE_FENGGU_TOLERANCE = 0.01  # 精准峰谷线：容差1%

XIANCHANG_ZHIBIE_DAYS = 10     # 现场直憋：10天窗口
XIANCHANG_ZHIBIE_AMPLITUDE = 0.05  # 现场直憋：振幅<5%
XIANCHANG_ZHIBIE_VOL = 0.8     # 现场直憋：后半段量<前半段80%

XUANYIN31_DAYS = 3             # 悬阴31：连续3天

T4_VARIANT_DAYS = 4            # T4变异：4天
T4_VARIANT_UP_PCT = 5.0        # T4变异：第4天涨5%以上


# ============================================================
# 【ATR计算】
# ============================================================
def calculate_atr(df, period=14):
    if len(df) < period + 1:
        return None, None
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1])
        )
    )
    atr = np.mean(tr[-period:])
    atr_pct = atr / close[-1] * 100
    return atr, atr_pct


def get_atr_threshold(atr_pct, mult, fallback):
    if ATR_ADAPTIVE and atr_pct is not None:
        return atr_pct * mult
    else:
        return fallback


def is_gem_star(code):
    if code.startswith('300') or code.startswith('301') or code.startswith('688'):
        return True
    return False


# ============================================================
# 【量能分位数工具函数】
# ============================================================
def get_vol_percentile(df, lookback=20):
    """
    计算今天的量在过去lookback天的分位数
    返回：0~1之间的数，0=最低，1=最高
    """
    if len(df) < lookback:
        lookback = len(df)
    recent_vols = df.iloc[-lookback:]['volume']
    today_vol = df.iloc[-1]['volume']
    pct = (recent_vols < today_vol).sum() / len(recent_vols)
    return pct


def is_high_volume(df, lookback=20, pct_threshold=0.8):
    """今天的量是不是大量？"""
    return get_vol_percentile(df, lookback) >= pct_threshold


def is_low_volume(df, lookback=20, pct_threshold=0.2):
    """今天的量是不是小量？"""
    return get_vol_percentile(df, lookback) <= pct_threshold


# ============================================================
# 数据读取
# ============================================================
def load_klines(market, code):
    possible_paths = [
        DATA_DIR / market / f"{code}.json",
        DATA_DIR / market / f"{market}{code}.json",
        DATA_DIR / f"{market}{code}.json",
    ]
    for filepath in possible_paths:
        if filepath.exists():
            with open(filepath, 'r') as f:
                data = json.load(f)
            klines = data.get('klines', [])
            ncols = len(klines[0])
            cols = ['date', 'open', 'close', 'high', 'low', 'volume'] if ncols == 6 else ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
            df = pd.DataFrame(klines)
            df = df.iloc[:, :ncols]
            df.columns = cols[:ncols]
            for col in ['open', 'close', 'high', 'low', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
            return df, data.get('name', code)
    return None, None


# ============================================================
# 找大阴实顶
# ============================================================
def find_big_yin_top(df, lookback_days, yin_body_pct):
    if len(df) < lookback_days:
        return None, None, None, None, None
    recent_df = df.iloc[-lookback_days:]
    for i in range(len(recent_df)-1, -1, -1):
        row = recent_df.iloc[i]
        if row['close'] >= row['open']:
            continue
        body_pct = (row['open'] - row['close']) / row['close'] * 100
        if body_pct >= yin_body_pct:
            return row['open'], row['close'], row['date'], row['volume'], len(df) - lookback_days + i
    return None, None, None, None, None


# ============================================================
# 找高量柱安全线/风险线
# ============================================================
def find_gaoliang_lines(recent_df):
    if len(recent_df) < 5:
        return None, None, None, None, None
    max_vol_idx = recent_df['volume'].idxmax()
    max_vol_row = recent_df.loc[max_vol_idx]
    open_price = max_vol_row['open']
    close_price = max_vol_row['close']
    high_price = max_vol_row['high']
    low_price = max_vol_row['low']
    body_size = abs(close_price - open_price)
    total_range = high_price - low_price
    if total_range == 0:
        return None, None, None, None, None
    body_ratio = body_size / total_range
    if body_ratio > BODY_RATIO_THRESHOLD:
        safe_line = max(open_price, close_price)
        risk_line = min(open_price, close_price)
        line_type = "实体"
    else:
        safe_line = high_price
        risk_line = low_price
        line_type = "影线"
    return safe_line, risk_line, line_type, max_vol_row['date'], max_vol_row['volume']


# ============================================================
# 找平衡线
# ============================================================
def find_balance_line(df, lookback_days, yin_body_pct):
    if len(df) < lookback_days:
        return None, None
    recent_df = df.iloc[-lookback_days:]
    for i in range(len(recent_df)-1, -1, -1):
        row = recent_df.iloc[i]
        if row['close'] >= row['open']:
            continue
        body_pct = (row['open'] - row['close']) / row['close'] * 100
        if body_pct >= yin_body_pct:
            return row['open'], row['date']
    return None, None


# ============================================================
# 找精准线
# ============================================================
def find_precise_lines(df, lookback_days, min_points, price_tolerance):
    if len(df) < lookback_days:
        return []
    recent_df = df.iloc[-lookback_days:]
    prices = recent_df['close'].values
    precise_lines = []
    used_indices = set()
    for i in range(len(prices)):
        if i in used_indices:
            continue
        price_i = prices[i]
        cluster_indices = [i]
        for j in range(len(prices)):
            if i == j or j in used_indices:
                continue
            diff_pct = abs(price_i - prices[j]) / price_i * 100
            if diff_pct <= price_tolerance:
                cluster_indices.append(j)
        if len(cluster_indices) >= min_points:
            avg_price = np.mean([prices[idx] for idx in cluster_indices])
            dates = [recent_df.iloc[idx]['date'] for idx in cluster_indices]
            precise_lines.append({
                'price': avg_price,
                'points': len(cluster_indices),
                'first_date': min(dates),
                'last_date': max(dates),
            })
            for idx in cluster_indices:
                used_indices.add(idx)
    precise_lines.sort(key=lambda x: x['points'], reverse=True)
    return precise_lines[:3]


# ============================================================
# 找峰顶线/谷底线
# ============================================================
def find_fenggu_lines(df, lookback_days, peak_side, confirm_days, vol_percentile):
    min_required = lookback_days + confirm_days + peak_side
    if len(df) < min_required:
        return None, None, None, None, [], []
    recent_df = df.iloc[-lookback_days:]
    vol_threshold = recent_df['volume'].quantile(vol_percentile)
    peaks, valleys = [], []
    start = peak_side
    end = len(recent_df) - max(peak_side, confirm_days)
    for i in range(start, end):
        row = recent_df.iloc[i]
        window = recent_df.iloc[i-peak_side:i+peak_side+1]
        is_local_high = row['high'] == window['high'].max()
        is_local_low = row['low'] == window['low'].min()
        has_vol = row['volume'] >= vol_threshold
        if is_local_high and has_vol:
            future = recent_df.iloc[i+1:i+1+confirm_days]
            if all(future['close'] < row['high']):
                peaks.append({'price': row['high'], 'date': row['date'], 'volume': row['volume']})
        if is_local_low and has_vol:
            future = recent_df.iloc[i+1:i+1+confirm_days]
            if all(future['close'] > row['low']):
                valleys.append({'price': row['low'], 'date': row['date'], 'volume': row['volume']})
    recent_peak = peaks[-1] if peaks else None
    recent_valley = valleys[-1] if valleys else None
    return (recent_peak['price'] if recent_peak else None,
            recent_peak['date'] if recent_peak else None,
            recent_valley['price'] if recent_valley else None,
            recent_valley['date'] if recent_valley else None,
            peaks, valleys)


# ============================================================
# 找斜衡线
# ============================================================
def find_xieheng_line(peaks, valleys, today_price):
    up_line = None
    down_line = None
    if len(valleys) >= XIEHENG_MIN_POINTS:
        v1 = valleys[-2]
        v2 = valleys[-1]
        if v2['price'] > v1['price']:
            up_line = {
                'type': '上升',
                'point1_price': v1['price'],
                'point1_date': v1['date'],
                'point2_price': v2['price'],
                'point2_date': v2['date'],
                'above_line': today_price > v2['price'],
            }
    if len(peaks) >= XIEHENG_MIN_POINTS:
        p1 = peaks[-2]
        p2 = peaks[-1]
        if p2['price'] < p1['price']:
            down_line = {
                'type': '下降',
                'point1_price': p1['price'],
                'point1_date': p1['date'],
                'point2_price': p2['price'],
                'point2_date': p2['date'],
                'above_line': today_price > p2['price'],
            }
    return up_line, down_line


# ============================================================
# 识别量柱形态（核心定义，保留官方）
# ============================================================
def identify_vol_pattern(df):
    if len(df) < 10:
        return "未知"
    today_vol = df.iloc[-1]['volume']
    yesterday_vol = df.iloc[-2]['volume']
    
    # 倍量柱：今天量/昨天量 >= BEISHU_RATIO（官方最低90%，参数化）
    if yesterday_vol > 0 and today_vol / yesterday_vol >= BEISHU_RATIO:
        return "倍量柱"
    
    # 高量柱：前20天最高
    recent_20 = df.iloc[-GAOLIANG_LOOKBACK:] if len(df) >= GAOLIANG_LOOKBACK else df
    if today_vol == recent_20['volume'].max():
        return "高量柱"
    
    # 低量柱：前20天最低
    if today_vol == recent_20['volume'].min():
        return "低量柱"
    
    # 梯量柱：连续3天递增
    v1, v2, v3 = df.iloc[-3]['volume'], df.iloc[-2]['volume'], df.iloc[-1]['volume']
    if v1 < v2 < v3:
        return "梯量柱"
    
    # 缩量柱：连续3天递减
    if v1 > v2 > v3:
        return "缩量柱"
    
    # 平量柱：和前5天平均差不多
    recent_5_avg = df.iloc[-6:-1]['volume'].mean()
    if recent_5_avg > 0:
        diff_pct = abs(today_vol - recent_5_avg) / recent_5_avg
        if diff_pct <= PINGLIANG_TOLERANCE:
            return "平量柱"
    
    return "普通量柱"


# ============================================================
# 关键位量影响力判断
# ============================================================
def judge_key_vol_impact(df, key_vol, key_date):
    if key_vol is None or key_date is None:
        return "无关键位", 0, 0
    today_vol = df.iloc[-1]['volume']
    vol_ratio = today_vol / key_vol * 100
    key_idx = None
    for i in range(len(df)-1, -1, -1):
        if df.iloc[i]['date'] == key_date:
            key_idx = i
            break
    time_distance = len(df) - 1 - key_idx if key_idx else 0
    if vol_ratio >= IMPACT_VS_KEY_VOL_HIGH * 100:
        vol_impact = "强"
    elif vol_ratio >= IMPACT_VS_KEY_VOL_MID * 100:
        vol_impact = "中"
    else:
        vol_impact = "弱"
    if time_distance <= IMPACT_TIME_NEAR:
        time_impact = "近"
    elif time_distance <= IMPACT_TIME_MID:
        time_impact = "中"
    else:
        time_impact = "远"
    if vol_impact == "强" and time_impact == "近":
        impact = "强"
    elif vol_impact == "弱" and time_impact == "远":
        impact = "弱"
    else:
        impact = "中"
    return impact, vol_ratio, time_distance


# ============================================================
# 【王牌柱官方版·优先级搜索·基柱用量分位数】
# ============================================================
def find_pillars_official(df, lookback_days=60):
    """
    王牌柱官方定义（股海明灯官网）
    搜索优先级：元帅柱 > 黄金柱 > 将军柱
    
    基柱条件：基柱量在过去20日的BASE_VOL_PCTL分位以上（自适应）
    """
    if len(df) < lookback_days + GENERAL_CONFIRM_DAYS + 20:
        return "无", None, None
    
    recent_df = df.iloc[-lookback_days:]
    
    marshals = []
    goldens = []
    generals = []
    
    for i in range(len(recent_df) - GENERAL_CONFIRM_DAYS - 1, 5, -1):
        row = recent_df.iloc[i]
        
        # 基柱必须是阳线
        if row['close'] <= row['open']:
            continue
        
        # 【自适应】基柱量在过去20日的BASE_VOL_PCTL分位以上
        # 而不是写死"比前一天高"
        if i < 20:
            continue
        vol_window = recent_df.iloc[i-20:i]['volume']
        vol_pctl = (vol_window < row['volume']).sum() / len(vol_window)
        if vol_pctl < BASE_VOL_PCTL:
            continue
        
        # 后三日数据
        future = recent_df.iloc[i+1:i+1+GENERAL_CONFIRM_DAYS]
        if len(future) < GENERAL_CONFIRM_DAYS:
            continue
        
        base_open = row['open']
        base_close = row['close']
        base_vol = row['volume']
        
        # 原则1：收盘价三日不破底
        future_avg_close = future['close'].mean()
        if future_avg_close < base_open:
            continue
        
        # 原则2：量柱群三日不过头（最后一天量 < 基柱量）
        future_last_vol = future.iloc[-1]['volume']
        if future_last_vol >= base_vol:
            continue
        
        # 判断是将军柱还是黄金柱
        is_golden = future_avg_close >= base_close
        
        # 元帅柱：黄金柱 + 基柱跳空高开
        if i > 0:
            prev_row = recent_df.iloc[i-1]
            is_gap_up = row['open'] > prev_row['high']
        else:
            is_gap_up = False
        
        pillar = (row['date'], row['low'])
        
        if is_golden and is_gap_up:
            marshals.append(pillar)
        elif is_golden:
            goldens.append(pillar)
        else:
            generals.append(pillar)
    
    # 按优先级返回
    if marshals:
        return "元帅柱", marshals[0][0], marshals[0][1]
    elif goldens:
        return "黄金柱", goldens[0][0], goldens[0][1]
    elif generals:
        return "将军柱", generals[0][0], generals[0][1]
    else:
        return "无", None, None


# ============================================================
# 找凹口线
# ============================================================
def find_aokou_line(df, lookback_days=60):
    if len(df) < lookback_days:
        return None, None, None
    recent_df = df.iloc[-lookback_days:]
    vols = recent_df['volume'].values
    best_gap = None
    best_price = None
    best_date = None
    for gap in range(AOKOU_MIN_GAP, AOKOU_MAX_GAP + 1, 2):
        for i in range(gap, len(vols)):
            vol_left = vols[i - gap]
            vol_right = vols[i]
            vol_diff = abs(vol_left - vol_right) / max(vol_left, vol_right)
            if vol_diff > AOKOU_PINGLIANG_TOLERANCE:
                continue
            middle_vols = vols[i - gap + 1:i]
            if len(middle_vols) == 0:
                continue
            min_middle_vol = middle_vols.min()
            avg_side_vol = (vol_left + vol_right) / 2
            if min_middle_vol > avg_side_vol * AOKOU_MIDDLE_SHADOW:
                continue
            min_idx = i - gap + 1 + middle_vols.argmin()
            aokou_price = recent_df.iloc[min_idx]['low']
            aokou_date = recent_df.iloc[min_idx]['date']
            if best_gap is None or gap > best_gap:
                best_gap = gap
                best_price = aokou_price
                best_date = aokou_date
    if best_price:
        return best_price, best_date, best_gap
    else:
        return None, None, None


# ============================================================
# 识别所有形态信号
# ============================================================
def identify_all_signals(df, valley_price, safe_line, precise_price, big_yin_top, peak_20,
                         atr_pct, changyang_threshold, binglin_threshold, code):
    signals = []
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    today_open = today['open']
    today_close = today['close']
    today_high = today['high']
    today_low = today['low']
    today_vol = today['volume']
    yesterday_open = yesterday['open']
    yesterday_close = yesterday['close']
    yesterday_vol = yesterday['volume']
    
    # 量能分位数
    today_vol_pctl = get_vol_percentile(df, VOL_LOOKBACK)
    
    if today_close > today_open and today_vol > yesterday_vol and today_close > yesterday_close:
        signals.append("阳胜进")
    if today_close < today_open and today_vol > yesterday_vol and today_close < yesterday_close:
        signals.append("阴胜出")
    
    body_pct = (today_close - today_open) / today_open * 100
    vol_ratio = today_vol / yesterday_vol if yesterday_vol > 0 else 0
    if 0 < body_pct < 3 and SMALL_BEISHU_MIN <= vol_ratio < SMALL_BEISHU_MAX:
        signals.append("小倍阳（矮将军）")
    
    body_size = abs(today_close - today_open)
    lower_shadow = min(today_open, today_close) - today_low
    touched_line = None
    if valley_price and abs(today_low - valley_price) / valley_price < TOUCH_LINE_TOLERANCE:
        touched_line = "谷底线"
    elif safe_line and abs(today_low - safe_line) / safe_line < TOUCH_LINE_TOLERANCE:
        touched_line = "安全线"
    elif precise_price and abs(today_low - precise_price) / precise_price < TOUCH_LINE_TOLERANCE:
        touched_line = "精准线"
    elif big_yin_top and abs(today_low - big_yin_top) / big_yin_top < TOUCH_LINE_TOLERANCE:
        touched_line = "大阴实顶线"
    
    if body_size > 0:
        lower_shadow_atr = lower_shadow / today_close * 100
        if atr_pct and lower_shadow_atr > atr_pct * LONG_LEG_ATR_MULT:
            if touched_line:
                signals.append(f"长腿踩线（{touched_line}）")
            else:
                signals.append("长腿（未踩线）")
        elif lower_shadow / body_size > 2.0:
            if touched_line:
                signals.append(f"长腿踩线（{touched_line}）")
            else:
                signals.append("长腿（未踩线）")
    
    # 长阴短柱：用分位数
    body_pct_down = (today_open - today_close) / today_close * 100
    if body_pct_down > changyang_threshold and today_vol_pctl < LONG_YIN_SHORT_VOL_PCTL:
        signals.append("长阴短柱")
    
    if today_close > yesterday_open and today_open < yesterday_close and today_close > today_open:
        signals.append("阳包阴")
    if today_close < yesterday_open and today_open > yesterday_close and today_close < today_open:
        signals.append("阴包阳")
    
    gap_up_pct = (today_open - yesterday['high']) / yesterday['high'] * 100
    gap_down_pct = (yesterday['low'] - today_open) / yesterday['low'] * 100
    gap_threshold = atr_pct * GAP_ATR_MULT if atr_pct else 0.5
    if gap_up_pct > gap_threshold:
        signals.append("跳空高开")
    if gap_down_pct > gap_threshold:
        signals.append("跳空低开")
    
    today_range = today_high - today_low
    if today_range > 0 and body_size / today_range < 0.1:
        signals.append("十字星")
    
    if peak_20 and today_close > peak_20:
        signals.append("过左峰")
    
    if today_close < today_open and today_close > yesterday_close and today_vol > yesterday_vol:
        signals.append("假阴真阳")
    
    if len(df) >= JIYIN_PREV_DAYS:
        prev_5 = df.iloc[-JIYIN_PREV_DAYS:]
        for i in range(len(prev_5)-2, 0, -1):
            row = prev_5.iloc[i]
            drop_pct = (row['close'] - row['open']) / row['open'] * 100
            if drop_pct < changyang_threshold:
                if today_close > today_open:
                    yin_body_size = row['open'] - row['close']
                    rebound_size = today_close - row['close']
                    if yin_body_size > 0 and rebound_size / yin_body_size > CIYANG_REBOUND_PCT / 100:
                        signals.append("极阴次阳")
                break
    
    # 长阳矮柱：用分位数
    chongyang_up_pct = (today_close - yesterday_close) / yesterday_close * 100
    if chongyang_up_pct > changyang_threshold and today_vol_pctl < 0.5:
        signals.append("长阳矮柱")
    
    if len(df) >= NIUGU_LOOKBACK:
        recent_60 = df.iloc[-NIUGU_LOOKBACK:]
        for i in range(len(recent_60)-1, 5, -1):
            row = recent_60.iloc[i]
            prev_row = recent_60.iloc[i-1]
            if prev_row['volume'] > 0 and row['volume'] / prev_row['volume'] >= BEISHU_RATIO and row['close'] > row['open']:
                beiliang_bottom = row['open']
                future = recent_60.iloc[i+1:]
                if len(future) > 0 and all(future['low'] >= beiliang_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
                    signals.append("倍量不穿")
                break
    
    if len(df) >= NIUGU_LOOKBACK:
        recent_60 = df.iloc[-NIUGU_LOOKBACK:]
        max_vol_idx = recent_60['volume'].idxmax()
        max_vol_row = recent_60.loc[max_vol_idx]
        gaoliang_bottom = max_vol_row['low']
        future = recent_60.iloc[max_vol_idx + 1:]
        if len(future) > 0 and all(future['low'] >= gaoliang_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
            signals.append("高量不破")
    
    if len(df) >= 10:
        recent_10 = df.iloc[-10:]
        for i in range(len(recent_10)-1, 1, -1):
            row = recent_10.iloc[i]
            prev_row = recent_10.iloc[i-1]
            if row['open'] > prev_row['high']:
                gap_bottom = prev_row['high']
                future = recent_10.iloc[i+1:]
                if len(future) > 0 and all(future['low'] >= gap_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
                    signals.append("跳空不补")
                break
    
    # 地量群：用分位数
    if len(df) >= DILIANG_GROUP_DAYS:
        recent_100 = df.iloc[-DILIANG_GROUP_DAYS:]
        vol_low_pctl = recent_100['volume'].quantile(VOL_PCTL_LOW)
        low_vol_count = sum(recent_100['volume'] <= vol_low_pctl)
        if low_vol_count >= DILIANG_GROUP_COUNT:
            signals.append("地量群")
    
    if len(df) >= JIA_SHENG_LIANG_SUO_DAYS:
        recent_3 = df.iloc[-JIA_SHENG_LIANG_SUO_DAYS:]
        prices_up = all(recent_3.iloc[i]['close'] > recent_3.iloc[i-1]['close'] for i in range(1, len(recent_3)))
        vols_down = all(recent_3.iloc[i]['volume'] < recent_3.iloc[i-1]['volume'] for i in range(1, len(recent_3)))
        if prices_up and vols_down:
            signals.append("价升量缩")
    
    if precise_price and len(df) >= HUICAI_PRECISION_DAYS:
        recent_10 = df.iloc[-HUICAI_PRECISION_DAYS:]
        touched = any(abs(row['low'] - precise_price) / precise_price < TOUCH_LINE_TOLERANCE for _, row in recent_10.iterrows())
        if touched:
            signals.append("回踩精准线")
    
    upper_shadow = today_high - max(today_open, today_close)
    if body_size > 0:
        if upper_shadow / body_size > DOUBLE_SWORD_UPPER_RATIO and lower_shadow / body_size > DOUBLE_SWORD_LOWER_RATIO:
            signals.append("双剑霸天地")
    
    if len(df) >= SANYUAN_DAYS:
        recent_3 = df.iloc[-SANYUAN_DAYS:]
        prices_up = all(recent_3.iloc[i]['close'] > recent_3.iloc[i-1]['close'] for i in range(1, len(recent_3)))
        vols_down = all(recent_3.iloc[i]['volume'] < recent_3.iloc[i-1]['volume'] for i in range(1, len(recent_3)))
        if prices_up and vols_down:
            signals.append("三元连动")
    
    if peak_20:
        distance_to_peak = (peak_20 - today_close) / today_close * 100
        if 0 < distance_to_peak < binglin_threshold and today_close > today_open:
            signals.append("兵临城下")
    
    if len(df) >= DAYANG_DOUBLE_REST_DAYS:
        recent_5 = df.iloc[-DAYANG_DOUBLE_REST_DAYS:]
        for i in range(len(recent_5)-1, 0, -1):
            row = recent_5.iloc[i]
            body_pct_up = (row['close'] - row['open']) / row['open'] * 100
            if body_pct_up > changyang_threshold:
                yang_bottom = row['open']
                yang_mid = (yang_bottom + row['close']) / 2
                future = recent_5.iloc[i+1:]
                if len(future) > 0 and all(future['low'] >= yang_mid):
                    signals.append("大阳双休")
                break
    
    if len(df) >= JIELI_DOUBLE_YANG_GAP_MAX + 5:
        recent_30 = df.iloc[-30:]
        big_yangs = []
        for i in range(len(recent_30)):
            row = recent_30.iloc[i]
            body_pct_up = (row['close'] - row['open']) / row['open'] * 100
            if body_pct_up > changyang_threshold:
                big_yangs.append(i)
        if len(big_yangs) >= 2:
            gap = big_yangs[-1] - big_yangs[-2]
            if JIELI_DOUBLE_YANG_GAP_MIN <= gap <= JIELI_DOUBLE_YANG_GAP_MAX:
                signals.append("接力双阳")
    
    today_pct = (today_close - yesterday_close) / yesterday_close * 100
    limit_up_pct = LIMIT_UP_GEM if is_gem_star(code) else LIMIT_UP_MAIN
    if today_pct >= limit_up_pct:
        signals.append("涨停板")
    
    # 倍量伸缩：用分位数
    if len(df) >= BEISHUO_LOOKBACK:
        recent_5 = df.iloc[-BEISHUO_LOOKBACK:]
        vols = recent_5['volume'].values
        vols_pctl = (recent_5['volume'].rank(pct=True)).values
        has_beishuo = False
        for i in range(1, len(vols)):
            if vols_pctl[i] >= BEISHUO_EXTEND_PCTL and vols_pctl[i-1] <= BEISHUO_SHRINK_PCTL:
                has_beishuo = True
                break
        if has_beishuo:
            signals.append("倍量伸缩")
    
    if len(df) >= GOLD_CROSS_LONG_MA + 1:
        ma5_today = df.iloc[-GOLD_CROSS_SHORT_MA:]['close'].mean()
        ma5_yesterday = df.iloc[-GOLD_CROSS_SHORT_MA-1:-1]['close'].mean()
        ma10_today = df.iloc[-GOLD_CROSS_LONG_MA:]['close'].mean()
        ma10_yesterday = df.iloc[-GOLD_CROSS_LONG_MA-1:-1]['close'].mean()
        vol_ma5_today = df.iloc[-GOLD_CROSS_VOL_SHORT_MA:]['volume'].mean()
        vol_ma5_yesterday = df.iloc[-GOLD_CROSS_VOL_SHORT_MA-1:-1]['volume'].mean()
        vol_ma10_today = df.iloc[-GOLD_CROSS_VOL_LONG_MA:]['volume'].mean()
        vol_ma10_yesterday = df.iloc[-GOLD_CROSS_VOL_LONG_MA-1:-1]['volume'].mean()
        price_cross = ma5_yesterday <= ma10_yesterday and ma5_today > ma10_today
        vol_cross = vol_ma5_yesterday <= vol_ma10_yesterday and vol_ma5_today > vol_ma10_today
        if price_cross and vol_cross:
            signals.append("黄金十字架")
    
    if peak_20 and valley_price and precise_price:
        near_peak = abs(precise_price - peak_20) / peak_20 < PRECISE_FENGGU_TOLERANCE
        near_valley = abs(precise_price - valley_price) / valley_price < PRECISE_FENGGU_TOLERANCE
        if near_peak and near_valley:
            signals.append("精准峰谷线")
    
    if len(df) >= XIANCHANG_ZHIBIE_DAYS:
        recent_10 = df.iloc[-XIANCHANG_ZHIBIE_DAYS:]
        high_max = recent_10['high'].max()
        low_min = recent_10['low'].min()
        amplitude = (high_max - low_min) / low_min
        first_half_avg = recent_10.iloc[:5]['volume'].mean()
        second_half_avg = recent_10.iloc[5:]['volume'].mean()
        if amplitude < XIANCHANG_ZHIBIE_AMPLITUDE and second_half_avg < first_half_avg * XIANCHANG_ZHIBIE_VOL:
            signals.append("现场直憋")
    
    if len(df) >= XUANYIN31_DAYS:
        recent_3 = df.iloc[-XUANYIN31_DAYS:]
        all_yin = all(recent_3.iloc[i]['close'] < recent_3.iloc[i]['open'] for i in range(len(recent_3)))
        vols_desc = all(recent_3.iloc[i]['volume'] < recent_3.iloc[i-1]['volume'] for i in range(1, len(recent_3)))
        if all_yin and vols_desc:
            signals.append("悬阴31")
    
    if len(df) >= T4_VARIANT_DAYS:
        recent_4 = df.iloc[-T4_VARIANT_DAYS:]
        day1_up_pct = (recent_4.iloc[0]['close'] - recent_4.iloc[0]['open']) / recent_4.iloc[0]['open'] * 100
        day2_down = recent_4.iloc[1]['close'] < recent_4.iloc[1]['open']
        day3_up = recent_4.iloc[2]['close'] > recent_4.iloc[2]['open']
        day4_up_pct = (recent_4.iloc[3]['close'] - recent_4.iloc[3]['open']) / recent_4.iloc[3]['open'] * 100
        if day1_up_pct > changyang_threshold and day2_down and day3_up and day4_up_pct > T4_VARIANT_UP_PCT:
            signals.append("T4变异")
    
    return signals


# ============================================================
# 生成综合解读
# ============================================================
def generate_interpretation(stock):
    sections = []
    
    if stock['big_yin_top']:
        above_text = "上方" if bool(stock['price_above_yintop']) else "下方"
        pct_text = f"{stock['price_vs_yintop_pct']:+.2f}%"
        if bool(stock['price_above_yintop']):
            conclusion = "说明买方已经把那天卖方的成果抢回来了，买方在这个区间占优。"
        else:
            conclusion = "说明买方还没能收复那天卖方的失地，卖方在这个区间仍占优。"
        sections.append({
            'title': '【起点】大阴实顶的市场意义',
            'content': [
                f"大阴实顶发生在{stock['days_since_yin']}天前（{stock['big_yin_date']}），价格{stock['big_yin_top']:.2f}元。",
                '<strong>市场机理</strong>：这是多空双方上次「休战」的警戒点。',
                f'<strong>推导</strong>：现在价格在大阴实顶<strong>{above_text}</strong> {pct_text}，{conclusion}',
                '<strong>量学依据</strong>：大阴实顶是回形针看盘法的起点。'
            ]
        })
    else:
        sections.append({
            'title': '【起点】大阴实顶的市场意义',
            'content': [
                '近60日没有出现中大阴线。',
                '<strong>市场机理</strong>：说明近期没有明显的多空大战分界线。',
                '<strong>量学依据</strong>：没有大阴实顶，说明多空双方还没有进行过大规模决战。'
            ]
        })
    
    if stock['yang_count'] + stock['yin_count'] > 0:
        ratio = stock['yang_yin_ratio']
        if ratio > 1.5:
            detail = "阳线明显多于阴线，说明买方赢得更频繁。"
        elif ratio < 0.67:
            detail = "阴线明显多于阴线，说明卖方赢得更频繁。"
        else:
            detail = "阴阳数量相当，说明多空双方力量均衡。"
        sections.append({
            'title': '【第一步】从右向左看——多空力量对比',
            'content': [
                f"从大阴实顶到今天：阳线{stock['yang_count']}根、阴线{stock['yin_count']}根，阴阳比{ratio:.2f}。",
                '<strong>市场机理</strong>：每根K线都是多空一天的战斗结果。',
                f'<strong>推导</strong>：阴阳比{ratio:.2f}，{detail}',
                '<strong>量学依据</strong>：价柱的阴阳数量对比，是多空力量最直观的体现。'
            ]
        })
    
    if stock['big_yin_vol']:
        vol_size = stock['yin_vol_size']
        if vol_size == "大量":
            mechanism = "那天多空双方真刀真枪干了一架，卖方放量砸盘。"
            conclusion = "大阴实顶那天是<strong>大量</strong>，说明上方的抛压是真实的。"
        elif vol_size == "小量":
            mechanism = "那天虽然价格跌了，但成交很清淡，没人接盘的「假跌」。"
            conclusion = "大阴实顶那天是<strong>小量</strong>，说明那次下跌是无量空跌。"
        else:
            mechanism = "那天的量和平时差不多，是正常调整。"
            conclusion = "大阴实顶那天是<strong>平量</strong>，说明那次下跌是正常调整。"
        sections.append({
            'title': '【第二步】从上往下看——量的真假判断',
            'content': [
                f"大阴实顶那天的成交量：{vol_size}。",
                f'<strong>市场机理</strong>：{mechanism}',
                f'<strong>推导</strong>：{conclusion}',
                '<strong>量学依据</strong>：量是因，价是果。'
            ]
        })
    
    if stock['big_yin_vol']:
        vol_ratio = stock['today_vs_yin_vol']
        days = stock['days_since_yin']
        if vol_ratio > 100:
            vol_judge = f"今天的量比大阴实顶那天还大（{vol_ratio:.1f}%）。"
        elif vol_ratio < 50:
            vol_judge = f"今天的量只有大阴实顶那天的{vol_ratio:.1f}%。"
        else:
            vol_judge = f"今天的量和大阴实顶那天差不多（{vol_ratio:.1f}%）。"
        if days <= IMPACT_TIME_NEAR:
            time_judge = f"时间距离只有{days}天，那个位置的「记忆」还很新鲜。"
        elif days <= IMPACT_TIME_MID:
            time_judge = f"时间距离{days}天，那个位置还有一定的影响力。"
        else:
            time_judge = f"时间距离已经{days}天了，那个位置的影响力已经比较弱了。"
        sections.append({
            'title': '【第三步】从左往右看——量的影响力',
            'content': [
                f"{vol_judge}",
                f"{time_judge}",
                '<strong>市场机理</strong>：量越大、时间越近，那个位置的「记忆」就越新鲜。',
                f'<strong>推导</strong>：大阴实顶的量对当下的影响力是<strong>{stock["time_impact"]}</strong>。',
                '<strong>量学依据</strong>：量柱的远近多少，决定了那个量柱对当下的影响力大小。'
            ]
        })
    
    vol_len = stock['vol_length']
    price_len = stock['price_length']
    body_ratio = stock['body_ratio']
    today_direction = "买方" if stock['power'] == "买方占优" else "卖方"
    if body_ratio > 60:
        body_judge = f"实体占比{body_ratio:.1f}%，实体较长，说明{today_direction}今天赢了，而且赢得比较彻底。"
    elif body_ratio < 30:
        body_judge = f"实体占比{body_ratio:.1f}%，实体很短，说明今天多空打了个平手。"
    else:
        body_judge = f"实体占比{body_ratio:.1f}%，实体中等，说明{today_direction}今天赢了，但赢得不算彻底。"
    sections.append({
        'title': '【第四步】从下往上看——当下量价建构',
        'content': [
            f"今天的量柱：{vol_len}；今天的价柱：{price_len}。",
            f"{body_judge}",
            '<strong>市场机理</strong>：量柱长短=今天多空双方投入了多少兵力；价柱长短=今天战斗的激烈程度。',
            f'<strong>推导</strong>：今天{vol_len}、{price_len}、{body_judge}',
            '<strong>量学依据</strong>：量价的长短伸缩，是当下多空力量最直接的体现。'
        ]
    })
    
    key_points = []
    if stock['peak_20']:
        above = "上方" if stock['close'] > stock['peak_20'] else "下方"
        key_points.append(f"20日峰顶线{stock['peak_20']:.2f}元（{stock['peak_date_20']}）：当前在<strong>{above}</strong>")
    if stock['valley_20']:
        above = "上方" if stock['close'] > stock['valley_20'] else "下方"
        key_points.append(f"20日谷底线{stock['valley_20']:.2f}元（{stock['valley_date_20']}）：当前在<strong>{above}</strong>")
    if stock['precise_lines']:
        pl = stock['precise_lines'][0]
        above = "上方" if stock['close'] > pl['price'] else "下方"
        key_points.append(f"精准线{pl['price']:.2f}元（{pl['points']}个点）：当前在<strong>{above}</strong>")
    if stock['safe_20']:
        above = "上方" if stock['close'] > stock['safe_20'] else "下方"
        key_points.append(f"20日高量柱安全线{stock['safe_20']:.2f}元：当前在<strong>{above}</strong>")
    if stock['balance_price']:
        above = "上方" if stock['close'] > stock['balance_price'] else "下方"
        key_points.append(f"平衡线{stock['balance_price']:.2f}元：当前在<strong>{above}</strong>")
    if stock.get('pillar_type') and stock['pillar_type'] != "无":
        above = "上方" if stock['close'] > stock['golden_line'] else "下方"
        key_points.append(f"{stock['pillar_type']}黄金线{stock['golden_line']:.2f}元：当前在<strong>{above}</strong>")
    if stock.get('aokou_price'):
        above = "上方" if stock['close'] > stock['aokou_price'] else "下方"
        key_points.append(f"凹口线{stock['aokou_price']:.2f}元：当前在<strong>{above}</strong>")
    if key_points:
        sections.append({
            'title': '【第五步】左侧关键位的约束',
            'content': [
                '当前价格与左侧关键位的关系：',
                *[f"• {kp}" for kp in key_points],
                '<strong>市场机理</strong>：峰顶线=上次卖方赢了的位置，现在变成压力位；谷底线=上次买方赢了的位置，现在变成支撑位。',
                '<strong>量学依据</strong>：量线是多空双方的「记忆」。'
            ]
        })
    
    conclusion_points = []
    if stock['big_yin_top']:
        if bool(stock['price_above_yintop']):
            conclusion_points.append("买方已经收复了大阴实顶，说明买方在这个区间占优")
        else:
            conclusion_points.append("买方还没能收复大阴实顶，卖方仍在这个区间占优")
    if stock['yang_yin_ratio'] > 1.5:
        conclusion_points.append("从大阴实顶到今天，阳线多于阴线，说明买方在逐步推进")
    elif stock['yang_yin_ratio'] < 0.67:
        conclusion_points.append("从大阴实顶到今天，阴线多于阳线，说明卖方仍在压制")
    if stock['yin_vol_size'] == "小量":
        conclusion_points.append("大阴实顶那天是小量，说明那次下跌是无量空跌")
    elif stock['yin_vol_size'] == "大量":
        conclusion_points.append("大阴实顶那天是大量，说明那次下跌是真出货")
    conclusion_points.append(f"今天{stock['pct_chg']:+.2f}%，{stock['power']}")
    conclusion_points.append(f"当前在近120日{stock['pos_status']}")
    
    sections.append({
        'title': '【综合结论】逻辑闭环',
        'content': [
            '把以上五步串起来：',
            *[f"{i+1}. {p}" for i, p in enumerate(conclusion_points)],
            f'<strong>最终判断</strong>：当前价格在{stock["pos_status"]}，{stock["power"]}，近3日涨跌{stock["pct_3d"]:+.2f}%，近5日涨跌{stock["pct_5d"]:+.2f}%。',
            '<strong>注意</strong>：以上是基于量学理论的客观描述，不构成任何交易建议。'
        ]
    })
    
    return sections


# ============================================================
# 生成单只股票数据
# ============================================================
def get_stock_data(market, code):
    df, name = load_klines(market, code)
    if df is None:
        return None
    
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    today_price = today['close']
    today_volume = today['volume']
    pct_chg = (today['close'] - yesterday['close']) / yesterday['close'] * 100
    
    atr_value, atr_pct = calculate_atr(df, ATR_PERIOD)
    
    yin_body_threshold = get_atr_threshold(atr_pct, YIN_BODY_ATR_MULT, YIN_BODY_FALLBACK)
    changyang_threshold = get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK)
    binglin_threshold = get_atr_threshold(atr_pct, BINGLIN_ATR_MULT, BINGLIN_FALLBACK)
    
    big_yin_top, big_yin_bottom, big_yin_date, big_yin_vol, big_yin_idx = find_big_yin_top(
        df, YIN_LOOKBACK, yin_body_threshold
    )
    
    if big_yin_top:
        price_vs_yintop_pct = (today_price - big_yin_top) / big_yin_top * 100
        price_above_yintop = bool(price_vs_yintop_pct > 0)
    else:
        price_vs_yintop_pct = 0
        price_above_yintop = None
    
    if big_yin_idx:
        period_df = df.iloc[big_yin_idx:]
        yang_count = int(sum(period_df['close'] > period_df['open']))
        yin_count = int(sum(period_df['close'] < period_df['open']))
        yang_yin_ratio = yang_count / max(yin_count, 1)
    else:
        yang_count = 0
        yin_count = 0
        yang_yin_ratio = 0
    
    recent_20 = df.iloc[-SHORT_WINDOW:]
    recent_high = recent_20['high'].max()
    recent_low = recent_20['low'].min()
    
    # 大阴实顶的量判断：用分位数
    if big_yin_vol:
        # 找大阴实顶那天在过去20日的量分位数
        big_yin_idx_in_df = None
        for i in range(len(df)):
            if df.iloc[i]['date'] == big_yin_date:
                big_yin_idx_in_df = i
                break
        if big_yin_idx_in_df and big_yin_idx_in_df >= 20:
            vol_window = df.iloc[big_yin_idx_in_df-20:big_yin_idx_in_df]['volume']
            yin_vol_pctl = (vol_window < big_yin_vol).sum() / len(vol_window)
            if yin_vol_pctl >= VOL_PCTL_HIGH:
                yin_vol_size = "大量"
            elif yin_vol_pctl <= VOL_PCTL_LOW:
                yin_vol_size = "小量"
            else:
                yin_vol_size = "平量"
        else:
            yin_vol_size = "未知"
    else:
        yin_vol_size = "未知"
    
    if big_yin_idx:
        days_since_yin = len(df) - 1 - big_yin_idx
    else:
        days_since_yin = 0
    
    if big_yin_vol:
        today_vs_yin_vol = today_volume / big_yin_vol * 100
    else:
        today_vs_yin_vol = 0
    
    if days_since_yin <= IMPACT_TIME_NEAR:
        time_impact = "很近（影响力强）"
    elif days_since_yin <= IMPACT_TIME_MID:
        time_impact = "中等（影响力一般）"
    else:
        time_impact = "很远（影响力弱）"
    
    vol_high_20 = recent_20['volume'].max()
    vol_low_20 = recent_20['volume'].min()
    vol_pos_20 = (today_volume - vol_low_20) / (vol_high_20 - vol_low_20) * 100
    if vol_pos_20 > VOL_POS_HIGH:
        vol_length = "长量柱（天量）"
    elif vol_pos_20 < VOL_POS_LOW:
        vol_length = "短量柱（地量）"
    else:
        vol_length = "中等量柱"
    
    today_range = today['high'] - today['low']
    today_range_pct = today_range / today_price * 100
    long_range_threshold = get_atr_threshold(atr_pct, LONG_RANGE_ATR_MULT, 3.0)
    short_range_threshold = get_atr_threshold(atr_pct, SHORT_RANGE_ATR_MULT, 1.0)
    if atr_pct and today_range_pct > long_range_threshold:
        price_length = "长价柱（振幅大）"
    elif atr_pct and today_range_pct < short_range_threshold:
        price_length = "短价柱（振幅小）"
    else:
        price_length = "中等价柱"
    
    body_size = abs(today['close'] - today['open'])
    body_ratio = body_size / today_range * 100 if today_range > 0 else 0
    if body_ratio > BODY_RATIO_LONG * 100:
        body_length = "长实体"
    elif body_ratio < BODY_RATIO_SHORT * 100:
        body_length = "短实体（十字星）"
    else:
        body_length = "中等实体"
    
    safe_20, risk_20, type_20, date_20, key_vol_20 = find_gaoliang_lines(recent_20)
    
    safe_60 = risk_60 = type_60 = date_60 = key_vol_60 = None
    recent_60 = df.iloc[-MID_WINDOW:] if len(df) > MID_WINDOW else None
    if recent_60 is not None:
        safe_60, risk_60, type_60, date_60, key_vol_60 = find_gaoliang_lines(recent_60)
    
    safe_120 = risk_120 = type_120 = date_120 = key_vol_120 = None
    recent_120 = df.iloc[-LONG_WINDOW:] if len(df) > LONG_WINDOW else None
    if recent_120 is not None:
        safe_120, risk_120, type_120, date_120, key_vol_120 = find_gaoliang_lines(recent_120)
    
    balance_price, balance_date = find_balance_line(df, BALANCE_LOOKBACK, yin_body_threshold)
    precise_lines = find_precise_lines(df, PRECISE_LOOKBACK, PRECISE_MIN_POINTS, PRECISE_PRICE_TOLERANCE)
    
    peak_20, peak_date_20, valley_20, valley_date_20, peaks_20, valleys_20 = find_fenggu_lines(
        df, SHORT_WINDOW, PEAK_SIDE_SHORT, CONFIRM_DAYS_SHORT, VOL_PERCENTILE
    )
    
    peak_60 = peak_date_60 = valley_60 = valley_date_60 = None
    peaks_60 = []
    valleys_60 = []
    if len(df) >= MID_WINDOW + CONFIRM_DAYS_MID + PEAK_SIDE_MID:
        peak_60, peak_date_60, valley_60, valley_date_60, peaks_60, valleys_60 = find_fenggu_lines(
            df, MID_WINDOW, PEAK_SIDE_MID, CONFIRM_DAYS_MID, VOL_PERCENTILE
        )
    
    peak_120 = peak_date_120 = valley_120 = valley_date_120 = None
    peaks_120 = []
    valleys_120 = []
    if len(df) >= LONG_WINDOW + CONFIRM_DAYS_LONG + PEAK_SIDE_LONG:
        peak_120, peak_date_120, valley_120, valley_date_120, peaks_120, valleys_120 = find_fenggu_lines(
            df, LONG_WINDOW, PEAK_SIDE_LONG, CONFIRM_DAYS_LONG, VOL_PERCENTILE
        )
    
    up_line, down_line = find_xieheng_line(peaks_120, valleys_120, today_price)
    vol_pattern = identify_vol_pattern(df)
    impact_20, vol_ratio_20, time_dist_20 = judge_key_vol_impact(df, key_vol_20, date_20)
    
    # 王牌柱
    pillar_type, pillar_date, golden_line = find_pillars_official(df)
    
    aokou_price, aokou_date, aokou_gap = find_aokou_line(df)
    
    precise_price = precise_lines[0]['price'] if precise_lines else None
    full_code = f"{market}{code}"
    extra_signals = identify_all_signals(
        df, valley_20, safe_20, precise_price, big_yin_top, peak_20,
        atr_pct, changyang_threshold, binglin_threshold, full_code
    )
    
    short_dist_high = (recent_high - today_price) / today_price * 100
    short_dist_low = (today_price - recent_low) / today_price * 100
    
    mid_high = mid_low = None
    mid_dist_high = mid_dist_low = None
    if recent_60 is not None:
        mid_high = recent_60['high'].max()
        mid_low = recent_60['low'].min()
        mid_dist_high = (mid_high - today_price) / today_price * 100
        mid_dist_low = (today_price - mid_low) / today_price * 100
    
    long_high = long_low = None
    long_dist_high = long_dist_low = None
    if recent_120 is not None:
        long_high = recent_120['high'].max()
        long_low = recent_120['low'].min()
        long_dist_high = (long_high - today_price) / today_price * 100
        long_dist_low = (today_price - long_low) / today_price * 100
    
    pos_120 = (today_price - long_low) / (long_high - long_low) * 100 if long_high else 50
    if pos_120 > POSITION_HIGH:
        pos_status = "高位"
    elif pos_120 < POSITION_LOW:
        pos_status = "低位"
    else:
        pos_status = "中位"
    
    power = "买方占优" if today['close'] > today['open'] else "卖方占优"
    
    pct_3d = (today['close'] - df.iloc[-4]['close']) / df.iloc[-4]['close'] * 100
    pct_5d = (today['close'] - df.iloc[-6]['close']) / df.iloc[-6]['close'] * 100
    
    stock_data = {
        'name': name,
        'code': full_code,
        'date': today['date'],
        'close': today_price,
        'pct_chg': pct_chg,
        'atr_pct': atr_pct,
        'yin_body_threshold': yin_body_threshold,
        'big_yin_top': big_yin_top,
        'big_yin_date': big_yin_date,
        'big_yin_vol': big_yin_vol,
        'price_above_yintop': price_above_yintop,
        'price_vs_yintop_pct': price_vs_yintop_pct,
        'yang_count': yang_count,
        'yin_count': yin_count,
        'yang_yin_ratio': yang_yin_ratio,
        'recent_high': recent_high,
        'recent_low': recent_low,
        'yin_vol_size': yin_vol_size,
        'days_since_yin': days_since_yin,
        'today_vs_yin_vol': today_vs_yin_vol,
        'time_impact': time_impact,
        'vol_pos_20': vol_pos_20,
        'vol_length': vol_length,
        'price_length': price_length,
        'body_length': body_length,
        'body_ratio': body_ratio,
        'safe_20': safe_20,
        'risk_20': risk_20,
        'date_20': date_20,
        'safe_60': safe_60,
        'risk_60': risk_60,
        'date_60': date_60,
        'safe_120': safe_120,
        'risk_120': risk_120,
        'date_120': date_120,
        'balance_price': balance_price,
        'balance_date': balance_date,
        'precise_lines': precise_lines,
        'up_line': up_line,
        'down_line': down_line,
        'peak_20': peak_20,
        'peak_date_20': peak_date_20,
        'valley_20': valley_20,
        'valley_date_20': valley_date_20,
        'peak_60': peak_60,
        'peak_date_60': peak_date_60,
        'valley_60': valley_60,
        'valley_date_60': valley_date_60,
        'peak_120': peak_120,
        'peak_date_120': peak_date_120,
        'valley_120': valley_120,
        'valley_date_120': valley_date_120,
        'vol_pattern': vol_pattern,
        'impact_20': impact_20,
        'vol_ratio_20': vol_ratio_20,
        'short_dist_high': short_dist_high,
        'short_dist_low': short_dist_low,
        'mid_high': mid_high,
        'mid_low': mid_low,
        'mid_dist_high': mid_dist_high,
        'mid_dist_low': mid_dist_low,
        'long_high': long_high,
        'long_low': long_low,
        'long_dist_high': long_dist_high,
        'long_dist_low': long_dist_low,
        'pos_status': pos_status,
        'power': power,
        'pct_3d': pct_3d,
        'pct_5d': pct_5d,
        'pillar_type': pillar_type,
        'pillar_date': pillar_date,
        'golden_line': golden_line,
        'aokou_price': aokou_price,
        'aokou_date': aokou_date,
        'aokou_gap': aokou_gap,
        'extra_signals': extra_signals,
    }
    
    stock_data['interpretations'] = generate_interpretation(stock_data)
    
    return stock_data


# ============================================================
# 生成HTML
# ============================================================
def generate_html(stocks_data, today_str):
    items = []
    for stock in stocks_data:
        if stock is None:
            continue
        
        price_class = "price-up" if stock['pct_chg'] > 0 else "price-down"
        
        if stock['big_yin_top']:
            yintop_text = f"{stock['big_yin_top']:.2f}（{stock['big_yin_date']}）"
        else:
            yintop_text = "无（近60日无中大阴线）"
        
        if stock['price_above_yintop'] is None:
            yintop_status = "未知"
            yintop_color = "#94a3b8"
        elif bool(stock['price_above_yintop']):
            yintop_status = "上方（强势）"
            yintop_color = "#ef4444"
        else:
            yintop_status = "下方（弱势）"
            yintop_color = "#22c55e"
        
        precise_html = ""
        if stock['precise_lines']:
            for i, line in enumerate(stock['precise_lines']):
                precise_html += f"""
                <div class="grid-item">
                    <div class="label">精准线{i+1}（{line['points']}点）</div>
                    <div class="value">{line['price']:.2f}（{line['first_date']}~{line['last_date']}）</div>
                </div>
                """
        else:
            precise_html = """
            <div class="grid-item">
                <div class="label">精准线</div>
                <div class="value value-none">无</div>
            </div>
            """
        
        def peak_html(label, price, date):
            if price is not None and date is not None:
                return f"""
                <div class="grid-item">
                    <div class="label">{label}</div>
                    <div class="value">{price:.2f}（{date}）</div>
                </div>
                """
            else:
                return f"""
                <div class="grid-item">
                    <div class="label">{label}</div>
                    <div class="value value-none value-strong">无（寻顶中·偏强）</div>
                </div>
                """
        
        def valley_html(label, price, date):
            if price is not None and date is not None:
                return f"""
                <div class="grid-item">
                    <div class="label">{label}</div>
                    <div class="value">{price:.2f}（{date}）</div>
                </div>
                """
            else:
                return f"""
                <div class="grid-item">
                    <div class="label">{label}</div>
                    <div class="value value-none value-weak">无（寻底中·偏弱）</div>
                </div>
                """
        
        if stock['pillar_type'] == "元帅柱":
            pillar_html = f"""
            <div class="grid-item" style="border:2px solid #fbbf24;">
                <div class="label">👑 元帅柱</div>
                <div class="value" style="color:#fbbf24;">{stock['pillar_date']}</div>
            </div>
            """
        elif stock['pillar_type'] == "黄金柱":
            pillar_html = f"""
            <div class="grid-item" style="border:2px solid #fbbf24;">
                <div class="label">⭐ 黄金柱</div>
                <div class="value" style="color:#fbbf24;">{stock['pillar_date']}</div>
            </div>
            """
        elif stock['pillar_type'] == "将军柱":
            pillar_html = f"""
            <div class="grid-item" style="border:2px solid #60a5fa;">
                <div class="label">将军柱</div>
                <div class="value" style="color:#60a5fa;">{stock['pillar_date']}</div>
            </div>
            """
        else:
            pillar_html = """
            <div class="grid-item">
                <div class="label">王牌柱</div>
                <div class="value value-none">无</div>
            </div>
            """
        
        if stock['aokou_price']:
            aokou_html = f"""
            <div class="grid-item" style="border:2px solid #a78bfa;">
                <div class="label">🎯 凹口线</div>
                <div class="value" style="color:#a78bfa;">{stock['aokou_price']:.2f}（{stock['aokou_date']}，间隔{stock['aokou_gap']}天）</div>
            </div>
            """
        else:
            aokou_html = """
            <div class="grid-item">
                <div class="label">凹口线</div>
                <div class="value value-none">无</div>
            </div>
            """
        
        extra_html = ""
        if stock['extra_signals']:
            for sig in stock['extra_signals']:
                extra_html += f'<span style="display:inline-block; background:#fbbf24; color:#000; padding:2px 8px; border-radius:4px; font-size:11px; margin:2px;">{sig}</span>'
        else:
            extra_html = '<span style="color:#94a3b8; font-size:12px;">无</span>'
        
        interp_html = ""
        for section in stock['interpretations']:
            interp_html += f"""
            <div style="margin-bottom: 12px; padding: 10px; background: #0f172a; border-radius: 8px; border-left: 3px solid #fbbf24;">
                <div style="font-weight: bold; color: #fbbf24; margin-bottom: 6px; font-size: 13px;">{section['title']}</div>
            """
            for line in section['content']:
                interp_html += f'                <p style="margin: 4px 0; font-size: 12px; color: #cbd5e1; line-height: 1.7;">{line}</p>\n'
            interp_html += """            </div>"""
        
        atr_text = f"{stock['atr_pct']:.2f}%" if stock['atr_pct'] else "未知"
        yin_thresh_text = f"{stock['yin_body_threshold']:.2f}%" if stock.get('yin_body_threshold') else "未知"
        
        item_html = f"""
        <div class="stock-card">
            <div class="stock-header">
                <div>
                    <div class="stock-name">{stock['name']}</div>
                    <div class="stock-code">{stock['code']}</div>
                </div>
                <div class="stock-price {price_class}">{stock['close']:.2f}元 ({stock['pct_chg']:+.2f}%)</div>
            </div>
            
            <div class="step-section">
                <div class="step-title">📐 本股ATR参数（自动计算）</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">ATR(14)</div>
                            <div class="value">{atr_text}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">中大阴线阈值</div>
                            <div class="value">{yin_thresh_text}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">起点：大阴实顶</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">大阴实顶（近60日）</div>
                            <div class="value">{yintop_text}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">当前位置</div>
                            <div class="value" style="color:{yintop_color}">{yintop_status}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">① 从右向左看：比较价柱的高低阴阳</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">价格vs大阴实顶</div>
                            <div class="value">{stock['price_vs_yintop_pct']:+.2f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">阳线/阴线数量</div>
                            <div class="value">{stock['yang_count']}阳 / {stock['yin_count']}阴</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">阴阳比</div>
                            <div class="value">{stock['yang_yin_ratio']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日高点</div>
                            <div class="value">{stock['recent_high']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日低点</div>
                            <div class="value">{stock['recent_low']:.2f}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">② 从上往下看：比较量价的真假大小</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">大阴实顶的量</div>
                            <div class="value">{stock['yin_vol_size']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">今日量柱形态</div>
                            <div class="value">{stock['vol_pattern']}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">③ 从左往右看：比较量柱的远近多少</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">时间距离</div>
                            <div class="value">{stock['days_since_yin']}天前</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">时间影响力</div>
                            <div class="value">{stock['time_impact']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">今天量vs大阴实顶量</div>
                            <div class="value">{stock['today_vs_yin_vol']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">关键位量影响力</div>
                            <div class="value" style="color:{'#ef4444' if stock['impact_20'] == '强' else '#fbbf24' if stock['impact_20'] == '中' else '#94a3b8'}">{stock['impact_20']}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">④ 从下往上看：比较量价的长短伸缩</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">量柱长短</div>
                            <div class="value">{stock['vol_length']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量能位置(20日)</div>
                            <div class="value">{stock['vol_pos_20']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">价柱伸缩</div>
                            <div class="value">{stock['price_length']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">实体占比</div>
                            <div class="value">{stock['body_ratio']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">📊 今日信号（25种涨停基因全）</div>
                <div class="step-content">
                    {extra_html}
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">王牌柱体系（官方版·优先级搜索·基柱自适应）</div>
                <div class="step-content">
                    <div class="grid-2">
                        {pillar_html}
                        <div class="grid-item">
                            <div class="label">黄金线（基柱最低价）</div>
                            <div class="value">{f"{stock['golden_line']:.2f}" if stock['golden_line'] else "无"}</div>
                        </div>
                        {aokou_html}
                        <div class="grid-item">
                            <div class="label">20日量柱位置</div>
                            <div class="value">{stock['vol_pos_20']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">⑤ 左侧关键位</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">平衡线</div>
                            <div class="value">{f"{stock['balance_price']:.2f}（{stock['balance_date']}）" if stock['balance_price'] else '-'}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">精准线</div>
                            <div class="value">{f"{stock['precise_lines'][0]['price']:.2f}（{stock['precise_lines'][0]['points']}点）" if stock['precise_lines'] else '-'}</div>
                        </div>
                        {peak_html('20日峰顶线', stock['peak_20'], stock['peak_date_20'])}
                        {valley_html('20日谷底线', stock['valley_20'], stock['valley_date_20'])}
                        <div class="grid-item">
                            <div class="label">20日安全线</div>
                            <div class="value">{f"{stock['safe_20']:.2f}（{stock['date_20']}）" if stock['safe_20'] else '-'}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日风险线</div>
                            <div class="value">{f"{stock['risk_20']:.2f}（{stock['date_20']}）" if stock['risk_20'] else '-'}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">📖 综合解读（量学理论推导）</div>
                <div class="step-content" style="background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);">
                    {interp_html}
                </div>
            </div>
        </div>
        """
        items.append(item_html)
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>四维循环看盘报告 - {today_str}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            background: #0f172a; 
            color: #e2e8f0; 
            line-height: 1.6;
            padding: 20px;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{ 
            background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%); 
            color: white; 
            padding: 30px; 
            border-radius: 12px; 
            margin-bottom: 20px;
            border-left: 4px solid #fbbf24;
        }}
        .header h1 {{ font-size: 24px; color: #fbbf24; margin-bottom: 8px; }}
        .header .date {{ opacity: 0.8; font-size: 14px; }}
        
        .signal-guide {{
            background: #1e293b;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid #334155;
        }}
        .signal-guide h2 {{
            font-size: 18px;
            color: #fbbf24;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #334155;
        }}
        .signal-item {{
            margin-bottom: 12px;
            padding: 10px;
            background: #0f172a;
            border-radius: 8px;
        }}
        .signal-item h3 {{
            font-size: 14px;
            color: #60a5fa;
            margin-bottom: 6px;
        }}
        .signal-item p {{
            font-size: 12px;
            color: #cbd5e1;
            margin-bottom: 4px;
        }}
        .signal-item .source {{
            font-size: 11px;
            color: #94a3b8;
            font-style: italic;
        }}
        
        .stock-card {{ 
            background: #1e293b; 
            border-radius: 12px; 
            padding: 20px; 
            margin-bottom: 15px; 
            border: 1px solid #334155;
        }}
        .stock-header {{ 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 15px; 
            padding-bottom: 15px; 
            border-bottom: 1px solid #334155;
        }}
        .stock-name {{ font-size: 18px; font-weight: bold; color: #e2e8f0; }}
        .stock-code {{ font-size: 12px; color: #94a3b8; }}
        .stock-price {{ font-size: 22px; font-weight: bold; }}
        .price-up {{ color: #ef4444; }}
        .price-down {{ color: #22c55e; }}
        
        .step-section {{ margin-bottom: 15px; }}
        .step-title {{ 
            font-size: 14px; 
            font-weight: bold; 
            color: #60a5fa; 
            margin-bottom: 8px; 
            padding-left: 8px; 
            border-left: 3px solid #fbbf24; 
        }}
        .step-content {{ 
            background: #0f172a; 
            padding: 12px; 
            border-radius: 8px; 
            font-size: 13px; 
            color: #cbd5e1; 
        }}
        
        .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
        .grid-item {{ 
            background: #0f172a; 
            padding: 8px; 
            border-radius: 6px; 
            font-size: 13px; 
        }}
        .grid-item .label {{ color: #94a3b8; font-size: 11px; }}
        .grid-item .value {{ font-weight: bold; color: #e2e8f0; font-size: 12px; }}
        .grid-item .value-none {{ color: #94a3b8; font-weight: normal; font-size: 11px; }}
        .grid-item .value-strong {{ color: #ef4444; font-weight: normal; font-size: 11px; }}
        .grid-item .value-weak {{ color: #22c55e; font-weight: normal; font-size: 11px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>四维循环看盘报告</h1>
            <div class="date">{today_str}</div>
            <div class="note" style="margin-top:10px;font-size:13px;opacity:0.7">量能自适应版 · 核心定义保留官方 · 辅助判断用分位数</div>
        </div>
        
        <div class="signal-guide">
            <h2>参数说明（全部参数化，方便调整）</h2>
            
            <div class="signal-item">
                <h3>【核心定义·保留官方】</h3>
                <p>倍量柱：今天量/昨天量 ≥ 1.8（官方最低90%）</p>
                <p>高量柱：前20天最高</p>
                <p>低量柱：前20天最低</p>
                <p>梯量柱：连续3天递增</p>
                <p>缩量柱：连续3天递减</p>
                <p>平量柱：和前5天平均差不超过15%</p>
                <p class="source">来源：股海明灯官网</p>
            </div>
            
            <div class="signal-item">
                <h3>【辅助判断·分位数自适应】</h3>
                <p>大量/放量：过去20日量的80%分位以上</p>
                <p>小量/缩量：过去20日量的20%分位以下</p>
                <p>王牌柱基柱：基柱量在过去20日的60%分位以上</p>
                <p>倍量伸缩：放量到80%分位 + 缩量到20%分位</p>
                <p class="source">来源：量化行业通用做法</p>
            </div>
            
            <div class="signal-item">
                <h3>【王牌柱官方定义】</h3>
                <p>三原则：①三日收盘不破底 ②量柱三日不过头 ③基柱是相对高量</p>
                <p>搜索优先级：元帅柱 > 黄金柱 > 将军柱</p>
                <p class="source">来源：股海明灯官网《王子老师语录十》</p>
            </div>
            
            <div class="signal-item">
                <h3>【最高原则】</h3>
                <p><strong>所有参数、阈值都要适配当前最新市场环境</strong></p>
                <p><strong>代码不要写死，能用参数阈值的就用参数阈值</strong></p>
                <p><strong>不构成任何交易建议，只做客观描述</strong></p>
            </div>
        </div>
        
        {''.join(items)}
    </div>
</body>
</html>
"""
    
    return html


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 60)
    print("四维循环看盘报告 - HTML版（量能自适应版）")
    print("=" * 60)
    
    stocks_data = []
    today_str = ""
    
    for market, code in HOLDINGS:
        try:
            data = get_stock_data(market, code)
            if data:
                stocks_data.append(data)
                today_str = data['date']
                if data['atr_pct']:
                    print(f"  已生成：{data['name']}（ATR={data['atr_pct']:.2f}%，王牌柱={data['pillar_type']}）")
                else:
                    print(f"  已生成：{data['name']}")
        except Exception as e:
            print(f"  Error: {market}{code} {e}")
    
    html_content = generate_html(stocks_data, today_str)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    html_file = OUTPUT_DIR / f"my_holdings_4d_report_{today_str}.html"
    
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n已生成HTML报告: {html_file}")


if __name__ == "__main__":
    main()
