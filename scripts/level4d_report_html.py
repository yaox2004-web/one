#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法报告 - HTML版（量学原版：大阴实顶+四维对比+个股解读+所有量线）
=================================================
设计思路（为什么这样写）：
  1. 【起点】先找最近的大阴实顶（量学原版四维看盘的起点）
  2. 【四维对比】从大阴实顶开始做四维对比
     - ① 从右向左看：比较价柱的高低阴阳
     - ② 从上往下看：比较量价的真假大小
     - ③ 从左往右看：比较量柱的远近多少
     - ④ 从下往上看：比较量价的长短伸缩
  3. 【所有量线】保留之前加的所有量线（安全线/风险线/峰顶线/谷底线/平衡线/精准线/斜衡线）
  4. 【个股解读】用四维看盘法客观描述当前状态，不做主观判断

【重要：无未来函数保证】
  1. 所有判断只用截止到今天收盘的数据
  2. 大阴实顶是历史数据，不是未来数据

量学理论来源：
  - 股海明灯（量学官网论坛）
  - 《量柱擒涨停》黑马王子著
  - 《量线捉涨停》黑马王子著
  - 四维看盘 = 回形针看盘法
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 【配置区】所有参数阈值都在这里，方便调整！
# ============================================================

# --- 文件路径配置 ---
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

# --- 持仓股配置 ---
HOLDINGS = [
    ("sh", "600584"),  # 长电科技
    ("sz", "002156"),  # 通富微电
    ("sh", "603283"),  # 赛腾股份
    ("sz", "300394"),  # 天孚通信
    ("sh", "601138"),  # 工业富联
    ("sh", "601231"),  # 环旭电子
    ("sz", "300476"),  # 胜宏科技
    ("sh", "603516"),  # 淳中科技
]

# --- 大阴实顶参数 ---
YIN_BODY_PCT = 3.0        # 中大阴线实体跌幅阈值（%）
YIN_LOOKBACK = 60          # 往前找多少天内的中大阴线

# --- 周期配置 ---
SHORT_WINDOW = 20    # 短期窗口（交易日）
MID_WINDOW = 60      # 中期窗口（交易日）
LONG_WINDOW = 120    # 长期窗口（交易日）

# --- 峰顶线/谷底线识别参数（适配量化时代） ---
PEAK_SIDE_SHORT = 2    # 短期(20日)：左右各2根 → 共5根（标准分形）
PEAK_SIDE_MID = 2      # 中期(60日)：左右各2根 → 共5根（标准分形）
PEAK_SIDE_LONG = 3     # 长期(120日)：左右各3根 → 共7根（更严格）

CONFIRM_DAYS_SHORT = 3  # 短期：3天确认
CONFIRM_DAYS_MID = 5    # 中期：5天确认
CONFIRM_DAYS_LONG = 10  # 长期：10天确认

VOL_PERCENTILE = 0.7    # 前30%以上（= 70%分位数）

# --- 高量柱安全线/风险线参数 ---
BODY_RATIO_THRESHOLD = 0.6  # 实体占比超过60%取实体顶底，否则取K线最高最低

# --- 平衡线参数 ---
BALANCE_YIN_BODY_PCT = 3.0  # 中大阴线实体跌幅阈值（%）
BALANCE_LOOKBACK = 30        # 往前找多少天内的中大阴线

# --- 精准线参数 ---
PRECISE_MIN_POINTS = 3        # 至少3个价格点重合
PRECISE_PRICE_TOLERANCE = 1.0 # 价格相差不超过1%
PRECISE_LOOKBACK = 120         # 往前找多少天内的价格点

# --- 斜衡线参数 ---
XIEHENG_MIN_POINTS = 2        # 至少2个点

# --- 量柱形态识别参数（量学理论：高低平倍梯缩） ---
BEISHU_RATIO = 2.0          # 倍量柱：今天量是昨天的2倍以上
PINGLIANG_TOLERANCE = 0.15  # 平量柱：和前5天平均相差不超过15%
GAOLIANG_LOOKBACK = 20       # 高量柱：前20天最高
DILIANGLIANG_LOOKBACK = 20   # 低量柱：前20天最低

# --- 关键位量影响力参数 ---
IMPACT_VS_KEY_VOL_HIGH = 0.8   # 今天量 > 关键位量的80% → 影响力强
IMPACT_VS_KEY_VOL_MID = 0.5    # 今天量 > 关键位量的50% → 影响力中等
IMPACT_TIME_NEAR = 20           # 时间距离<20天 → 时间近
IMPACT_TIME_MID = 60            # 时间距离<60天 → 时间中等

# --- 量价组合参数 ---
VOL_RATIO_HIGH = 1.5     # 量比>1.5算放量
VOL_RATIO_LOW = 0.7      # 量比<0.7算缩量
BODY_RATIO_LONG = 0.6    # 实体占比超过60%算长实体
BODY_RATIO_SHORT = 0.3   # 实体占比<30%算短实体

# --- 位置分位参数 ---
POSITION_HIGH = 70        # 位置>70%算高位
POSITION_LOW = 30         # 位置<30%算低位

# --- 量能位置参数 ---
VOL_POS_HIGH = 80         # 量能位置>80%算天量
VOL_POS_LOW = 20          # 量能位置<20%算地量


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
            
            if ncols == 6:
                cols = ['date', 'open', 'close', 'high', 'low', 'volume']
            else:
                cols = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
            
            df = pd.DataFrame(klines)
            df = df.iloc[:, :ncols]
            df.columns = cols[:ncols]
            
            for col in ['open', 'close', 'high', 'low', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
            
            return df, data.get('name', code)
    
    return None, None


# ============================================================
# 找大阴实顶（四维看盘的起点！）
# ============================================================
def find_big_yin_top(df, lookback_days, yin_body_pct):
    """
    找最近的中大阴线实体顶部（大阴实顶）
    
    量学理论：
    - 四维看盘的起点：从大阴实顶开始看
    - 大阴实顶 = 中大阴线的开盘价（因为是阴线，开盘价>收盘价）
    - 大阴实顶是多空双方上次休战的"警戒点"
    
    【无未来函数】：只用历史数据
    """
    if len(df) < lookback_days:
        return None, None, None, None, None
    
    recent_df = df.iloc[-lookback_days:]
    
    for i in range(len(recent_df)-1, -1, -1):
        row = recent_df.iloc[i]
        
        # 找阴线
        if row['close'] >= row['open']:
            continue
        
        # 计算实体跌幅
        body_pct = (row['open'] - row['close']) / row['close'] * 100
        
        # 中大阴线
        if body_pct >= yin_body_pct:
            big_yin_top = row['open']  # 阴线实体顶部 = 开盘价
            big_yin_bottom = row['close']  # 阴线实体底部 = 收盘价
            big_yin_date = row['date']
            big_yin_vol = row['volume']
            big_yin_idx = len(df) - lookback_days + i  # 在整个df中的索引
            
            return big_yin_top, big_yin_bottom, big_yin_date, big_yin_vol, big_yin_idx
    
    return None, None, None, None, None


# ============================================================
# 找高量柱的安全线和风险线
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
# 找平衡线（量学理论：左侧中大阴线实体顶部）
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
            balance_price = row['open']
            balance_date = row['date']
            return balance_price, balance_date
    
    return None, None


# ============================================================
# 找精准线（量学理论：多个价格重合的位置）
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
            
            price_j = prices[j]
            
            diff_pct = abs(price_i - price_j) / price_i * 100
            
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
# 找峰顶线和谷底线（多空双方博弈过的）
# ============================================================
def find_fenggu_lines(df, lookback_days, peak_side, confirm_days, vol_percentile):
    min_required = lookback_days + confirm_days + peak_side
    if len(df) < min_required:
        return None, None, None, None, [], []
    
    recent_df = df.iloc[-lookback_days:]
    
    vol_threshold = recent_df['volume'].quantile(vol_percentile)
    
    peaks = []
    valleys = []
    
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
            confirmed = all(future['close'] < row['high'])
            
            if confirmed:
                peaks.append({
                    'price': row['high'],
                    'date': row['date'],
                    'volume': row['volume'],
                })
        
        if is_local_low and has_vol:
            future = recent_df.iloc[i+1:i+1+confirm_days]
            confirmed = all(future['close'] > row['low'])
            
            if confirmed:
                valleys.append({
                    'price': row['low'],
                    'date': row['date'],
                    'volume': row['volume'],
                })
    
    recent_peak = peaks[-1] if peaks else None
    recent_valley = valleys[-1] if valleys else None
    
    return (recent_peak['price'] if recent_peak else None,
            recent_peak['date'] if recent_peak else None,
            recent_valley['price'] if recent_valley else None,
            recent_valley['date'] if recent_valley else None,
            peaks, valleys)


# ============================================================
# 找斜衡线（量学理论：连接两个峰顶/谷底的斜线）
# ============================================================
def find_xieheng_line(peaks, valleys, today_price):
    up_line = None
    down_line = None
    
    if len(valleys) >= XIEHENG_MIN_POINTS:
        v1 = valleys[-2]
        v2 = valleys[-1]
        
        if v2['price'] > v1['price']:
            today_on_line = v2['price']
            
            up_line = {
                'type': '上升',
                'point1_price': v1['price'],
                'point1_date': v1['date'],
                'point2_price': v2['price'],
                'point2_date': v2['date'],
                'current_on_line': today_on_line,
                'above_line': today_price > today_on_line,
            }
    
    if len(peaks) >= XIEHENG_MIN_POINTS:
        p1 = peaks[-2]
        p2 = peaks[-1]
        
        if p2['price'] < p1['price']:
            today_on_line = p2['price']
            
            down_line = {
                'type': '下降',
                'point1_price': p1['price'],
                'point1_date': p1['date'],
                'point2_price': p2['price'],
                'point2_date': p2['date'],
                'current_on_line': today_on_line,
                'above_line': today_price > today_on_line,
            }
    
    return up_line, down_line


# ============================================================
# 识别量柱形态（量学理论：高低平倍梯缩）
# ============================================================
def identify_vol_pattern(df):
    if len(df) < 10:
        return "未知"
    
    today_vol = df.iloc[-1]['volume']
    yesterday_vol = df.iloc[-2]['volume']
    
    recent_20 = df.iloc[-GAOLIANG_LOOKBACK:] if len(df) >= GAOLIANG_LOOKBACK else df
    
    if today_vol / yesterday_vol >= BEISHU_RATIO:
        return "倍量柱"
    
    if today_vol == recent_20['volume'].max():
        return "高量柱"
    
    if today_vol == recent_20['volume'].min():
        return "低量柱"
    
    v1 = df.iloc[-3]['volume']
    v2 = df.iloc[-2]['volume']
    v3 = df.iloc[-1]['volume']
    if v1 < v2 < v3:
        return "梯量柱"
    
    if v1 > v2 > v3:
        return "缩量柱"
    
    recent_5_avg = df.iloc[-6:-1]['volume'].mean()
    diff_pct = abs(today_vol - recent_5_avg) / recent_5_avg
    
    if diff_pct <= PINGLIANG_TOLERANCE:
        return "平量柱"
    
    return "普通量柱"


# ============================================================
# 关键位量对今天的影响力判断
# ============================================================
def judge_key_vol_impact(df, key_vol, key_date):
    """
    判断关键位的量对今天的影响力
    
    量学理论：
    - 关键位的量越大，影响力越强
    - 关键位离今天越近，影响力越强
    - 今天的量越接近关键位的量，说明关键位的量对今天影响越大
    
    【无未来函数】：只用历史数据
    """
    if key_vol is None or key_date is None:
        return "无关键位", 0, 0
    
    today_vol = df.iloc[-1]['volume']
    
    # 1. 量能对比：今天量是关键位量的百分之多少
    vol_ratio = today_vol / key_vol * 100
    
    # 2. 时间距离：关键位到今天隔了多少天
    key_idx = None
    for i in range(len(df)-1, -1, -1):
        if df.iloc[i]['date'] == key_date:
            key_idx = i
            break
    
    if key_idx is None:
        time_distance = 0
    else:
        time_distance = len(df) - 1 - key_idx
    
    # 3. 综合判断影响力
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
# 生成个股解读
# ============================================================
def generate_interpretation(stock):
    """
    用四维看盘法客观解读个股当前状态
    
    原则：客观描述，不做主观判断
    """
    interpretations = []
    
    # 1. 大阴实顶位置解读
    if stock['big_yin_top']:
        if stock['price_above_yintop']:
            interpretations.append(
                f"当前价格在大阴实顶（{stock['big_yin_top']:.2f}元，{stock['big_yin_date']}）上方，"
                f"高出{stock['price_vs_yintop_pct']:.2f}%。"
                f"说明大阴实顶那天卖出的人，卖出后价格又涨回来了。"
            )
        else:
            interpretations.append(
                f"当前价格在大阴实顶（{stock['big_yin_top']:.2f}元，{stock['big_yin_date']}）下方，"
                f"低于{abs(stock['price_vs_yintop_pct']):.2f}%。"
                f"说明大阴实顶那天卖出的人，卖出后价格继续下跌。"
            )
    else:
        interpretations.append("近60日没有出现中大阴线，说明近期没有明显的多空大战分界线。")
    
    # 2. 阴阳对比解读
    if stock['yang_count'] + stock['yin_count'] > 0:
        if stock['yang_yin_ratio'] > 1.5:
            interpretations.append(
                f"从大阴实顶到今天，阳线{stock['yang_count']}根，阴线{stock['yin_count']}根，"
                f"阴阳比{stock['yang_yin_ratio']:.2f}，阳线明显多于阴线。"
            )
        elif stock['yang_yin_ratio'] < 0.67:
            interpretations.append(
                f"从大阴实顶到今天，阳线{stock['yang_count']}根，阴线{stock['yin_count']}根，"
                f"阴阳比{stock['yang_yin_ratio']:.2f}，阴线明显多于阳线。"
            )
        else:
            interpretations.append(
                f"从大阴实顶到今天，阳线{stock['yang_count']}根，阴线{stock['yin_count']}根，"
                f"阴阳比{stock['yang_yin_ratio']:.2f}，多空双方力量相当。"
            )
    
    # 3. 量价真假解读
    if stock['yin_vol_size'] == "大量":
        interpretations.append(
            f"大阴实顶那天的成交量很大（{stock['yin_vol_size']}），"
            f"说明那天多空双方博弈很激烈。"
        )
    elif stock['yin_vol_size'] == "小量":
        interpretations.append(
            f"大阴实顶那天的成交量很小（{stock['yin_vol_size']}），"
            f"说明那天虽然价格跌了，但成交很清淡。"
        )
    
    # 4. 时间距离解读
    if stock['days_since_yin'] <= 10:
        interpretations.append(
            f"大阴实顶发生在{stock['days_since_yin']}天前，时间很近，"
            f"这个位置的记忆还很新鲜。"
        )
    elif stock['days_since_yin'] <= 30:
        interpretations.append(
            f"大阴实顶发生在{stock['days_since_yin']}天前，时间中等，"
            f"这个位置还有一定的影响力。"
        )
    else:
        interpretations.append(
            f"大阴实顶发生在{stock['days_since_yin']}天前，时间很远，"
            f"这个位置的影响力已经比较弱了。"
        )
    
    # 5. 量的多少对比解读
    if stock['today_vs_yin_vol'] > 100:
        interpretations.append(
            f"今天的成交量是大阴实顶那天的{stock['today_vs_yin_vol']:.1f}%，"
            f"说明今天的博弈比那天还激烈。"
        )
    elif stock['today_vs_yin_vol'] < 50:
        interpretations.append(
            f"今天的成交量是大阴实顶那天的{stock['today_vs_yin_vol']:.1f}%，"
            f"说明今天的成交比那天清淡很多。"
        )
    else:
        interpretations.append(
            f"今天的成交量是大阴实顶那天的{stock['today_vs_yin_vol']:.1f}%，"
            f"和那天差不多。"
        )
    
    # 6. 量价长短伸缩解读
    interpretations.append(
        f"今天的量柱：{stock['vol_length']}；今天的价柱：{stock['price_length']}。"
    )
    
    if stock['body_ratio'] > 60:
        interpretations.append(
            f"今天K线实体占比{stock['body_ratio']:.1f}%，实体较长，"
            f"说明今天多空一方赢了，而且赢得比较彻底。"
        )
    elif stock['body_ratio'] < 30:
        interpretations.append(
            f"今天K线实体占比{stock['body_ratio']:.1f}%，实体很短，"
            f"说明今天多空打了个平手。"
        )
    
    # 7. 位置总结
    interpretations.append(
        f"当前价格在近120日{stock['pos_status']}，近3日涨跌{stock['pct_3d']:+.2f}%，"
        f"近5日涨跌{stock['pct_5d']:+.2f}%。"
    )
    
    return interpretations


# ============================================================
# 生成单只股票的报告数据
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
    
    # ========== 【起点】找大阴实顶 ==========
    big_yin_top, big_yin_bottom, big_yin_date, big_yin_vol, big_yin_idx = find_big_yin_top(
        df, YIN_LOOKBACK, YIN_BODY_PCT
    )
    
    # ========== ① 从右向左看：比较价柱的高低阴阳 ==========
    if big_yin_top:
        price_vs_yintop = today_price - big_yin_top
        price_vs_yintop_pct = price_vs_yintop / big_yin_top * 100
        price_above_yintop = price_vs_yintop > 0
    else:
        price_vs_yintop = 0
        price_vs_yintop_pct = 0
        price_above_yintop = None
    
    if big_yin_idx:
        period_df = df.iloc[big_yin_idx:]
        yang_count = sum(period_df['close'] > period_df['open'])
        yin_count = sum(period_df['close'] < period_df['open'])
        yang_yin_ratio = yang_count / max(yin_count, 1)
    else:
        yang_count = 0
        yin_count = 0
        yang_yin_ratio = 0
    
    recent_20 = df.iloc[-SHORT_WINDOW:]
    recent_high = recent_20['high'].max()
    recent_low = recent_20['low'].min()
    
    # ========== ② 从上往下看：比较量价的真假大小 ==========
    if big_yin_vol:
        avg_vol_20 = recent_20['volume'].mean()
        big_yin_vs_avg = big_yin_vol / avg_vol_20
        
        if big_yin_vs_avg > VOL_RATIO_HIGH:
            yin_vol_size = "大量"
        elif big_yin_vs_avg < VOL_RATIO_LOW:
            yin_vol_size = "小量"
        else:
            yin_vol_size = "平量"
    else:
        yin_vol_size = "未知"
        big_yin_vs_avg = 0
    
    if big_yin_vol and big_yin_vs_avg:
        if big_yin_vs_avg > VOL_RATIO_HIGH:
            yin_vol_true = "量大（可能是出货）"
        elif big_yin_vs_avg < VOL_RATIO_LOW:
            yin_vol_true = "量小（真跌，没人接）"
        else:
            yin_vol_true = "量平（正常调整）"
    else:
        yin_vol_true = "未知"
    
    # ========== ③ 从左往右看：比较量柱的远近多少 ==========
    if big_yin_idx:
        days_since_yin = len(df) - 1 - big_yin_idx
    else:
        days_since_yin = 0
    
    if big_yin_vol:
        today_vs_yin_vol = today_volume / big_yin_vol * 100
        
        if today_vs_yin_vol > 100:
            vol_more_less = "今天量更大"
        elif today_vs_yin_vol < 50:
            vol_more_less = "今天量更小"
        else:
            vol_more_less = "差不多"
    else:
        today_vs_yin_vol = 0
        vol_more_less = "未知"
    
    if days_since_yin <= 10:
        time_impact = "很近（影响力强）"
    elif days_since_yin <= 30:
        time_impact = "中等（影响力一般）"
    else:
        time_impact = "很远（影响力弱）"
    
    # ========== ④ 从下往上看：比较量价的长短伸缩 ==========
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
    avg_range_20 = recent_20.apply(lambda x: x['high'] - x['low'], axis=1).mean()
    range_ratio = today_range / avg_range_20
    
    if range_ratio > 1.5:
        price_length = "长价柱（振幅大）"
    elif range_ratio < 0.7:
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
    
    # ========== 所有量线 ==========
    # 高量柱安全线/风险线
    safe_20, risk_20, type_20, date_20, key_vol_20 = find_gaoliang_lines(recent_20)
    
    safe_60 = risk_60 = type_60 = date_60 = key_vol_60 = None
    recent_60 = df.iloc[-MID_WINDOW:] if len(df) > MID_WINDOW else None
    if recent_60 is not None:
        safe_60, risk_60, type_60, date_60, key_vol_60 = find_gaoliang_lines(recent_60)
    
    safe_120 = risk_120 = type_120 = date_120 = key_vol_120 = None
    recent_120 = df.iloc[-LONG_WINDOW:] if len(df) > LONG_WINDOW else None
    if recent_120 is not None:
        safe_120, risk_120, type_120, date_120, key_vol_120 = find_gaoliang_lines(recent_120)
    
    # 平衡线
    balance_price, balance_date = find_balance_line(df, BALANCE_LOOKBACK, BALANCE_YIN_BODY_PCT)
    
    # 精准线
    precise_lines = find_precise_lines(df, PRECISE_LOOKBACK, PRECISE_MIN_POINTS, PRECISE_PRICE_TOLERANCE)
    
    # 峰顶线/谷底线
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
    
    # 斜衡线
    up_line, down_line = find_xieheng_line(peaks_120, valleys_120, today_price)
    
    # 量柱形态
    vol_pattern = identify_vol_pattern(df)
    
    # 关键位量影响力
    impact_20, vol_ratio_20, time_dist_20 = judge_key_vol_impact(df, key_vol_20, date_20)
    
    # ========== ⑤ 和历史对比 ==========
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
    
    # ========== ⑥ 全景总结 ==========
    pos_120 = (today_price - long_low) / (long_high - long_low) * 100 if long_high else 50
    
    if pos_120 > POSITION_HIGH:
        pos_status = "高位"
    elif pos_120 < POSITION_LOW:
        pos_status = "低位"
    else:
        pos_status = "中位"
    
    if today['close'] > today['open']:
        power = "买方占优"
    else:
        power = "卖方占优"
    
    pct_3d = (today['close'] - df.iloc[-4]['close']) / df.iloc[-4]['close'] * 100
    pct_5d = (today['close'] - df.iloc[-6]['close']) / df.iloc[-6]['close'] * 100
    
    stock_data = {
        'name': name,
        'code': f"{market}{code}",
        'date': today['date'],
        'close': today_price,
        'pct_chg': pct_chg,
        # 大阴实顶
        'big_yin_top': big_yin_top,
        'big_yin_bottom': big_yin_bottom,
        'big_yin_date': big_yin_date,
        'big_yin_vol': big_yin_vol,
        # ① 从右向左看
        'price_above_yintop': price_above_yintop,
        'price_vs_yintop_pct': price_vs_yintop_pct,
        'yang_count': yang_count,
        'yin_count': yin_count,
        'yang_yin_ratio': yang_yin_ratio,
        'recent_high': recent_high,
        'recent_low': recent_low,
        # ② 从上往下看
        'yin_vol_size': yin_vol_size,
        'yin_vol_true': yin_vol_true,
        # ③ 从左往右看
        'days_since_yin': days_since_yin,
        'today_vs_yin_vol': today_vs_yin_vol,
        'vol_more_less': vol_more_less,
        'time_impact': time_impact,
        # ④ 从下往上看
        'vol_pos_20': vol_pos_20,
        'vol_length': vol_length,
        'price_length': price_length,
        'body_length': body_length,
        'body_ratio': body_ratio,
        # 所有量线
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
        'time_dist_20': time_dist_20,
        # ⑤ 和历史对比
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
        # ⑥ 全景总结
        'pos_status': pos_status,
        'power': power,
        'pct_3d': pct_3d,
        'pct_5d': pct_5d,
    }
    
    # 生成个股解读
    stock_data['interpretations'] = generate_interpretation(stock_data)
    
    return stock_data


# ============================================================
# 生成峰顶线/谷底线的HTML
# ============================================================
def render_peak_item(label, price, date):
    if price is not None and date is not None:
        value = f"{price:.2f}（{date}）"
        value_class = "value"
    else:
        value = "无（寻顶中·偏强）"
        value_class = "value value-none value-strong"
    
    return f"""
    <div class="grid-item">
        <div class="label">{label}</div>
        <div class="{value_class}">{value}</div>
    </div>
    """


def render_valley_item(label, price, date):
    if price is not None and date is not None:
        value = f"{price:.2f}（{date}）"
        value_class = "value"
    else:
        value = "无（寻底中·偏弱）"
        value_class = "value value-none value-weak"
    
    return f"""
    <div class="grid-item">
        <div class="label">{label}</div>
        <div class="{value_class}">{value}</div>
    </div>
    """


# ============================================================
# 生成斜衡线的HTML
# ============================================================
def render_xieheng_html(up_line, down_line):
    html = ""
    
    if up_line:
        above_text = "上方" if up_line['above_line'] else "下方"
        html += f"""
        <div class="grid-item">
            <div class="label">上升斜衡线（支撑）</div>
            <div class="value">
                {up_line['point1_price']:.2f}（{up_line['point1_date']}）
                → {up_line['point2_price']:.2f}（{up_line['point2_date']}）
                <br><span style="font-size:11px; color:#94a3b8;">当前在{above_text}</span>
            </div>
        </div>
        """
    else:
        html += """
        <div class="grid-item">
            <div class="label">上升斜衡线（支撑）</div>
            <div class="value value-none">无</div>
        </div>
        """
    
    if down_line:
        above_text = "上方" if down_line['above_line'] else "下方"
        html += f"""
        <div class="grid-item">
            <div class="label">下降斜衡线（阻力）</div>
            <div class="value">
                {down_line['point1_price']:.2f}（{down_line['point1_date']}）
                → {down_line['point2_price']:.2f}（{down_line['point2_date']}）
                <br><span style="font-size:11px; color:#94a3b8;">当前在{above_text}</span>
            </div>
        </div>
        """
    else:
        html += """
        <div class="grid-item">
            <div class="label">下降斜衡线（阻力）</div>
            <div class="value value-none">无</div>
        </div>
        """
    
    return html


# ============================================================
# 生成HTML
# ============================================================
def generate_html(stocks_data, today_str):
    items = []
    for stock in stocks_data:
        if stock is None:
            continue
        
        price_class = "price-up" if stock['pct_chg'] > 0 else "price-down"
        
        # 大阴实顶显示
        if stock['big_yin_top']:
            yintop_text = f"{stock['big_yin_top']:.2f}（{stock['big_yin_date']}）"
        else:
            yintop_text = "无（近60日无中大阴线）"
        
        if stock['price_above_yintop'] is True:
            yintop_status = "上方（强势）"
            yintop_color = "#ef4444"
        elif stock['price_above_yintop'] is False:
            yintop_status = "下方（弱势）"
            yintop_color = "#22c55e"
        else:
            yintop_status = "未知"
            yintop_color = "#94a3b8"
        
        mid_high_str = f"{stock['mid_high']:.2f}" if stock['mid_high'] else '-'
        mid_low_str = f"{stock['mid_low']:.2f}" if stock['mid_low'] else '-'
        long_high_str = f"{stock['long_high']:.2f}" if stock['long_high'] else '-'
        long_low_str = f"{stock['long_low']:.2f}" if stock['long_low'] else '-'
        
        balance_str = f"{stock['balance_price']:.2f}（{stock['balance_date']}）" if stock['balance_price'] else '-'
        
        # 精准线HTML
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
        
        xieheng_html = render_xieheng_html(stock['up_line'], stock['down_line'])
        
        safe_20_str = f"{stock['safe_20']:.2f}（{stock['date_20']}）" if stock['safe_20'] else '-'
        risk_20_str = f"{stock['risk_20']:.2f}（{stock['date_20']}）" if stock['risk_20'] else '-'
        safe_60_str = f"{stock['safe_60']:.2f}（{stock['date_60']}）" if stock['safe_60'] else '-'
        risk_60_str = f"{stock['risk_60']:.2f}（{stock['date_60']}）" if stock['risk_60'] else '-'
        safe_120_str = f"{stock['safe_120']:.2f}（{stock['date_120']}）" if stock['safe_120'] else '-'
        risk_120_str = f"{stock['risk_120']:.2f}（{stock['date_120']}）" if stock['risk_120'] else '-'
        
        peak_20_html = render_peak_item("20日峰顶线", stock['peak_20'], stock['peak_date_20'])
        valley_20_html = render_valley_item("20日谷底线", stock['valley_20'], stock['valley_date_20'])
        peak_60_html = render_peak_item("60日峰顶线", stock['peak_60'], stock['peak_date_60'])
        valley_60_html = render_valley_item("60日谷底线", stock['valley_60'], stock['valley_date_60'])
        peak_120_html = render_peak_item("120日峰顶线", stock['peak_120'], stock['peak_date_120'])
        valley_120_html = render_valley_item("120日谷底线", stock['valley_120'], stock['valley_date_120'])
        
        impact_color = "#ef4444" if stock['impact_20'] == "强" else ("#fbbf24" if stock['impact_20'] == "中" else "#94a3b8")
        
        # 个股解读HTML
        interpretation_html = ""
        for interp in stock['interpretations']:
            interpretation_html += f"<p style='margin:8px 0; padding-left:10px; border-left: 3px solid #fbbf24;'>{interp}</p>\n"
        
        item_html = f"""
        <div class="stock-card">
            <div class="stock-header">
                <div>
                    <div class="stock-name">{stock['name']}</div>
                    <div class="stock-code">{stock['code']}</div>
                </div>
                <div class="stock-price {price_class}">{stock['close']:.2f}元 ({stock['pct_chg']:+.2f}%)</div>
            </div>
            
            <!-- 【起点】大阴实顶 -->
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
            
            <!-- ① 从右向左看：比较价柱的高低阴阳 -->
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
            
            <!-- 所有量线 -->
            <div class="step-section">
                <div class="step-title">量线体系</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">平衡线（大阴实顶）</div>
                            <div class="value">{balance_str}</div>
                        </div>
                    </div>
                    
                    <div style="margin-top:10px;">
                        <p style="color:#60a5fa; font-size:12px; margin-bottom:5px;">精准线：</p>
                        <div class="grid-2">
                            {precise_html}
                        </div>
                    </div>
                    
                    <div style="margin-top:10px;">
                        <p style="color:#60a5fa; font-size:12px; margin-bottom:5px;">斜衡线：</p>
                        <div class="grid-2">
                            {xieheng_html}
                        </div>
                    </div>
                    
                    <div style="margin-top:10px;">
                        <p style="color:#60a5fa; font-size:12px; margin-bottom:5px;">峰顶线/谷底线：</p>
                        <div class="grid-2">
                            {peak_20_html}
                            {valley_20_html}
                            {peak_60_html}
                            {valley_60_html}
                            {peak_120_html}
                            {valley_120_html}
                        </div>
                    </div>
                    
                    <div style="margin-top:10px;">
                        <p style="color:#60a5fa; font-size:12px; margin-bottom:5px;">高量柱安全线/风险线：</p>
                        <div class="grid-2">
                            <div class="grid-item">
                                <div class="label">20日安全线</div>
                                <div class="value">{safe_20_str}</div>
                            </div>
                            <div class="grid-item">
                                <div class="label">20日风险线</div>
                                <div class="value">{risk_20_str}</div>
                            </div>
                            <div class="grid-item">
                                <div class="label">60日安全线</div>
                                <div class="value">{safe_60_str}</div>
                            </div>
                            <div class="grid-item">
                                <div class="label">60日风险线</div>
                                <div class="value">{risk_60_str}</div>
                            </div>
                            <div class="grid-item">
                                <div class="label">120日安全线</div>
                                <div class="value">{safe_120_str}</div>
                            </div>
                            <div class="grid-item">
                                <div class="label">120日风险线</div>
                                <div class="value">{risk_120_str}</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- ② 从上往下看：比较量价的真假大小 -->
            <div class="step-section">
                <div class="step-title">② 从上往下看：比较量价的真假大小</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">大阴实顶的量</div>
                            <div class="value">{stock['yin_vol_size']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量价真假判断</div>
                            <div class="value">{stock['yin_vol_true']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">今日量柱形态</div>
                            <div class="value">{stock['vol_pattern']}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- ③ 从左往右看：比较量柱的远近多少 -->
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
                            <div class="label">量的多少对比</div>
                            <div class="value">{stock['vol_more_less']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">关键位量影响力</div>
                            <div class="value" style="color:{impact_color}">{stock['impact_20']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">今日量vs关键位量</div>
                            <div class="value">{stock['vol_ratio_20']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- ④ 从下往上看：比较量价的长短伸缩 -->
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
                            <div class="label">实体长短</div>
                            <div class="value">{stock['body_length']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">实体占比</div>
                            <div class="value">{stock['body_ratio']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <!-- ⑤ 和历史对比 -->
            <div class="step-section">
                <div class="step-title">⑤ 和历史对比</div>
                <div class="step-content">
                    <p><strong>短期(20日)：</strong>
                        离高点 {stock['short_dist_high']:+.2f}% | 
                        离低点 {stock['short_dist_low']:+.2f}%
                    </p>
                    <p><strong>中期(60日)：</strong>
                        离高点 {stock['mid_dist_high']:+.2f}% | 
                        离低点 {stock['mid_dist_low']:+.2f}%
                    </p>
                    <p><strong>长期(120日)：</strong>
                        离高点 {stock['long_dist_high']:+.2f}% | 
                        离低点 {stock['long_dist_low']:+.2f}%
                    </p>
                </div>
            </div>
            
            <!-- 个股解读 -->
            <div class="step-section">
                <div class="step-title">📖 个股解读（四维看盘法）</div>
                <div class="step-content" style="background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);">
                    {interpretation_html}
                </div>
            </div>
            
            <!-- ⑥ 全景总结 -->
            <div class="step-section">
                <div class="step-title">⑥ 全景总结</div>
                <div class="summary-box">
                    <p>
                        今日{stock['pct_chg']:+.2f}%，{stock['pos_status']}，{stock['power']}。<br>
                        量柱：{stock['vol_length']}，价柱：{stock['price_length']}。<br>
                        大阴实顶：{yintop_text}<br>
                        近3日涨跌：{stock['pct_3d']:+.2f}%，近5日涨跌：{stock['pct_5d']:+.2f}%。<br>
                    </p>
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
        .step-content p {{ margin-bottom: 4px; }}
        
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
        
        .summary-box {{
            background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
            padding: 15px;
            border-radius: 8px;
            margin-top: 10px;
        }}
        .summary-box p {{ margin: 0; color: #fbbf24; font-size: 13px; line-height: 1.8; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>四维循环看盘报告</h1>
            <div class="date">{today_str}</div>
            <div class="note" style="margin-top:10px;font-size:13px;opacity:0.7">量学原版：大阴实顶 + 四维对比 + 所有量线 + 个股解读</div>
        </div>
        
        <!-- 信号说明区（顶部，只放一次） -->
        <div class="signal-guide">
            <h2>四维看盘法说明</h2>
            
            <div class="signal-item">
                <h3>起点：大阴实顶</h3>
                <p><strong>定义：</strong>从今天往左找最近的中大阴线（实体幅度≥3%），其实体顶部就是"大阴实顶"</p>
                <p><strong>原理：</strong>大阴实顶是多空双方上次休战的"警戒点"，下次争夺的"起动点"</p>
                <p><strong>参数：</strong>近60日搜索，阴线实体幅度≥3%</p>
                <p><strong>设计思路：</strong>以最近的大阴线为基准，建立对比锚点</p>
                <p><strong>注意事项：</strong>必须是最近的，不能用太远的</p>
                <p class="source">来源：股海明灯（量学官网）</p>
            </div>
            
            <div class="signal-item">
                <h3>① 从右向左看：比较价柱的高低阴阳</h3>
                <p><strong>视线：</strong>从今天往左，往大阴实顶方向看</p>
                <p><strong>对比内容：</strong>价格高低、阴阳数量、阴阳比</p>
                <p><strong>参数：</strong>统计从大阴实顶到今天的所有K线</p>
                <p><strong>设计思路：</strong>看多空双方力量对比</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>② 从上往下看：比较量价的真假大小</h3>
                <p><strong>视线：</strong>从大阴实顶的价柱往下看量柱</p>
                <p><strong>对比内容：</strong>量柱大小、量价真假</p>
                <p><strong>量柱形态：</strong>高量柱、低量柱、平量柱、倍量柱、梯量柱、缩量柱</p>
                <p><strong>设计思路：</strong>判断大阴实顶那天的量是真还是假</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>③ 从左往右看：比较量柱的远近多少</h3>
                <p><strong>视线：</strong>从大阴实顶的量柱往右看，看到今天的量柱</p>
                <p><strong>对比内容：</strong>时间距离、量的多少对比</p>
                <p><strong>时间影响力：</strong>很近（≤10天）、较近（11-30天）、较远（31-60天）、很远（>60天）</p>
                <p><strong>关键位量影响力：</strong>强/中/弱</p>
                <p><strong>设计思路：</strong>看大阴实顶的量对当下的影响力</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>④ 从下往上看：比较量价的长短伸缩</h3>
                <p><strong>视线：</strong>从今天的量柱往上看价柱</p>
                <p><strong>对比内容：</strong>量柱长短、价柱伸缩、实体长短</p>
                <p><strong>实体占比：</strong>实体长度/振幅长度</p>
                <p><strong>设计思路：</strong>判断当下的量价建构</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>量线体系</h3>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>平衡线（大阴实顶）</h3>
                <p><strong>定义：</strong>最近大阴线的实体顶部</p>
                <p><strong>原理：</strong>多空双方上次休战的"警戒点"</p>
                <p><strong>参数：</strong>近60日搜索</p>
                <p><strong>设计思路：</strong>以最近的大阴实顶为基准</p>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>精准线</h3>
                <p><strong>定义：</strong>多个价格点重合在同一水平线上</p>
                <p><strong>原理：</strong>多空双方多次在同一价位博弈，形成"精准"支撑/压力</p>
                <p><strong>参数：</strong>至少3个价格点重合，误差≤1%</p>
                <p><strong>设计思路：</strong>找多空双方反复争夺的关键价位</p>
                <p><strong>注意事项：</strong>需要右确认（至少3个点）</p>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>斜衡线</h3>
                <p><strong>定义：</strong>连接两个或多个峰顶/谷底的斜线</p>
                <p><strong>原理：</strong>反映趋势的斜率和方向</p>
                <p><strong>参数：</strong>至少2个点，上升斜衡线=支撑，下降斜衡线=阻力</p>
                <p><strong>设计思路：</strong>看趋势的方向和斜率</p>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>峰顶线/谷底线</h3>
                <p><strong>定义：</strong>多空双方激烈博弈过的高点/低点</p>
                <p><strong>原理：</strong>峰顶=卖方赢了，谷底线=买方赢了</p>
                <p><strong>参数：</strong>峰边距≥3天（左右各3天，取中间最高/最低），成交量要求适配当前环境</p>
                <p><strong>设计思路：</strong>找真正博弈过的关键位，不用左侧历史极值法</p>
                <p><strong>注意事项：</strong>需要右确认（峰边距≥3天）</p>
                <p><strong>没有峰顶/谷底的情况：</strong>无峰顶=寻顶中（偏强势），无谷底=寻底中（偏弱势）</p>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>高量柱安全线/风险线</h3>
                <p><strong>定义：</strong>高量柱的最高价=安全线，最低价=风险线</p>
                <p><strong>原理：</strong>高量柱那天多空博弈最激烈，最高价和最低价就是关键位</p>
                <p><strong>参数：</strong>20日/60日/120日高量柱</p>
                <p><strong>设计思路：</strong>以高量柱的高低点为基准</p>
                <p><strong>注意事项：</strong>取实（最高价/最低价），不取虚</p>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>量柱六种形态</h3>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>高量柱</h3>
                <p><strong>定义：</strong>近N日最大成交量</p>
                <p><strong>原理：</strong>多空博弈最激烈的一天</p>
                <p><strong>参数：</strong>近20日/60日/120日天量</p>
                <p><strong>设计思路：</strong>找博弈最激烈的位置</p>
            </div>
            
            <div class="signal-item">
                <h3>低量柱</h3>
                <p><strong>定义：</strong>近N日最小成交量</p>
                <p><strong>原理：</strong>多空双方都休息了，无人关注</p>
                <p><strong>参数：</strong>近20日/60日/120日地量</p>
                <p><strong>设计思路：</strong>找无人关注的位置</p>
            </div>
            
            <div class="signal-item">
                <h3>平量柱</h3>
                <p><strong>定义：</strong>与昨日量差不多（±20%以内）</p>
                <p><strong>原理：</strong>多空双方力量平衡</p>
                <p><strong>参数：</strong>±20%以内</p>
                <p><strong>设计思路：</strong>看量能是否平稳</p>
            </div>
            
            <div class="signal-item">
                <h3>倍量柱</h3>
                <p><strong>定义：</strong>今日量≥昨日量×1.9</p>
                <p><strong>原理：</strong>多空一方突然发力</p>
                <p><strong>参数：</strong>≥1.9倍</p>
                <p><strong>设计思路：</strong>看是否有突然放量</p>
            </div>
            
            <div class="signal-item">
                <h3>梯量柱</h3>
                <p><strong>定义：</strong>连续3天放量</p>
                <p><strong>原理：</strong>多空双方逐步加码</p>
                <p><strong>参数：</strong>连续3天递增</p>
                <p><strong>设计思路：</strong>看是否有连续放量</p>
            </div>
            
            <div class="signal-item">
                <h3>缩量柱</h3>
                <p><strong>定义：</strong>连续3天缩量</p>
                <p><strong>原理：</strong>多空双方逐步退场</p>
                <p><strong>参数：</strong>连续3天递减</p>
                <p><strong>设计思路：</strong>看是否有连续缩量</p>
            </div>
            
            <div class="signal-item">
                <h3>关键位量影响力</h3>
                <p><strong>定义：</strong>判断关键位的量对当下的影响力</p>
                <p><strong>原理：</strong>量越大、时间越近，影响力越强</p>
                <p><strong>参数：</strong>强/中/弱</p>
                <p><strong>设计思路：</strong>综合时间距离和量大小判断</p>
            </div>
            
            <div class="signal-item">
                <h3>个股解读</h3>
                <p><strong>原则：</strong>客观描述，不做主观判断</p>
                <p><strong>方法：</strong>用四维看盘法逐步描述</p>
            </div>
            
            <div class="signal-item">
                <h3>最高原则</h3>
                <p><strong>所有参数、阈值都要适配当前最新市场环境</strong></p>
                <p><strong>代码不要写死，能用参数阈值的就用参数阈值</strong></p>
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
    print("四维循环看盘报告 - HTML版（量学原版：大阴实顶+四维对比+所有量线+个股解读）")
    print("=" * 60)
    
    stocks_data = []
    today_str = ""
    
    for market, code in HOLDINGS:
        try:
            data = get_stock_data(market, code)
            if data:
                stocks_data.append(data)
                today_str = data['date']
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
