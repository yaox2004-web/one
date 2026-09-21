#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法报告 - HTML版（量学理论推导版）
=================================================
设计思路：
  1. 起点：大阴实顶（量学四维看盘的起点）
  2. 四维对比：从大阴实顶开始做四维对比
  3. 左侧关键位：所有量线（平衡线/精准线/斜衡线/峰顶线/谷底线/高量柱线）
  4. 综合解读：量学理论驱动的逻辑推导，不是数据罗列
     - 每一步都有市场机理
     - 每一步都有量学理论依据
     - 每一步都能推导下一步
     - 最终形成逻辑闭环

【无未来函数】：所有判断只用截止到今天收盘的数据
【资料来源】：股海明灯《量柱擒涨停》《量线捉涨停》黑马王子著
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 【配置区】所有参数阈值都在这里
# ============================================================

DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

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

YIN_BODY_PCT = 3.0
YIN_LOOKBACK = 60

SHORT_WINDOW = 20
MID_WINDOW = 60
LONG_WINDOW = 120

PEAK_SIDE_SHORT = 2
PEAK_SIDE_MID = 2
PEAK_SIDE_LONG = 3

CONFIRM_DAYS_SHORT = 3
CONFIRM_DAYS_MID = 5
CONFIRM_DAYS_LONG = 10

VOL_PERCENTILE = 0.7
BODY_RATIO_THRESHOLD = 0.6

BALANCE_YIN_BODY_PCT = 3.0
BALANCE_LOOKBACK = 30

PRECISE_MIN_POINTS = 3
PRECISE_PRICE_TOLERANCE = 1.0
PRECISE_LOOKBACK = 120

XIEHENG_MIN_POINTS = 2

BEISHU_RATIO = 2.0
PINGLIANG_TOLERANCE = 0.15
GAOLIANG_LOOKBACK = 20

IMPACT_VS_KEY_VOL_HIGH = 0.8
IMPACT_VS_KEY_VOL_MID = 0.5
IMPACT_TIME_NEAR = 20
IMPACT_TIME_MID = 60

VOL_RATIO_HIGH = 1.5
VOL_RATIO_LOW = 0.7
BODY_RATIO_LONG = 0.6
BODY_RATIO_SHORT = 0.3

POSITION_HIGH = 70
POSITION_LOW = 30
VOL_POS_HIGH = 80
VOL_POS_LOW = 20


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
            big_yin_top = row['open']
            big_yin_bottom = row['close']
            big_yin_date = row['date']
            big_yin_vol = row['volume']
            big_yin_idx = len(df) - lookback_days + i
            
            return big_yin_top, big_yin_bottom, big_yin_date, big_yin_vol, big_yin_idx
    
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
            balance_price = row['open']
            balance_date = row['date']
            return balance_price, balance_date
    
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
# 找峰顶线/谷底线
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
                peaks.append({'price': row['high'], 'date': row['date'], 'volume': row['volume']})
        
        if is_local_low and has_vol:
            future = recent_df.iloc[i+1:i+1+confirm_days]
            confirmed = all(future['close'] > row['low'])
            if confirmed:
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
# 识别量柱形态
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
# 【核心】生成量学理论推导式综合解读
# ============================================================
def generate_interpretation(stock):
    """
    量学理论驱动的逻辑推导式解读
    不是数据罗列，而是一步步推导，形成逻辑闭环
    """
    sections = []
    
    # ========== 【起点】大阴实顶的市场意义 ==========
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
                f"<strong>市场机理</strong>：这是多空双方上次"休战"的警戒点。那天卖方赢了，但休战后买方开始组织反击。",
                f"<strong>推导</strong>：现在价格在大阴实顶<strong>{above_text}</strong> {pct_text}，{conclusion}",
                f"<strong>量学依据</strong>：大阴实顶是回形针看盘法的起点，是多空力量转换的分水岭。"
            ]
        })
    else:
        sections.append({
            'title': '【起点】大阴实顶的市场意义',
            'content': [
                "近60日没有出现中大阴线。",
                "<strong>市场机理</strong>：说明近期没有明显的多空大战分界线，市场处于相对平稳的状态。",
                "<strong>量学依据</strong>：没有大阴实顶，说明多空双方还没有进行过大规模决战。"
            ]
        })
    
    # ========== 【第一步】从右向左看——多空力量对比 ==========
    if stock['yang_count'] + stock['yin_count'] > 0:
        ratio = stock['yang_yin_ratio']
        if ratio > 1.5:
            power = "买方"
            detail = "阳线明显多于阴线，说明买方赢得更频繁，在这个区间有持续性优势。"
        elif ratio < 0.67:
            power = "卖方"
            detail = "阴线明显多于阳线，说明卖方赢得更频繁，在这个区间仍占主动。"
        else:
            power = "多空双方"
            detail = "阴阳数量相当，说明多空双方在这个区间力量均衡，处于拉锯状态。"
        
        sections.append({
            'title': '【第一步】从右向左看——多空力量对比',
            'content': [
                f"从大阴实顶到今天：阳线{stock['yang_count']}根、阴线{stock['yin_count']}根，阴阳比{ratio:.2f}。",
                f"<strong>市场机理</strong>：每根K线都是多空一天的战斗结果。阳线多=买方赢的天数多，阴线多=卖方赢的天数多。",
                f"<strong>推导</strong>：阴阳比{ratio:.2f}，{detail}",
                f"<strong>量学依据</strong>：价柱的阴阳数量对比，是多空力量最直观的体现。"
            ]
        })
    
    # ========== 【第二步】从上往下看——量的真假判断 ==========
    if stock['big_yin_vol']:
        vol_size = stock['yin_vol_size']
        if vol_size == "大量":
            mechanism = "那天多空双方真刀真枪干了一架，卖方放量砸盘，说明卖方是真出货。"
            conclusion = "大阴实顶那天是<strong>大量</strong>，说明上方的抛压是真实的，后面突破起来会比较费劲。"
        elif vol_size == "小量":
            mechanism = "那天虽然价格跌了，但成交很清淡，说明没人接盘的"假跌"，卖方只是虚晃一枪。"
            conclusion = "大阴实顶那天是<strong>小量</strong>，说明那天的下跌是无量空跌，卖方力量其实不强，后面可能要涨。"
        else:
            mechanism = "那天的量和平时差不多，说明是正常的调整，没有明显的多空意图。"
            conclusion = "大阴实顶那天是<strong>平量</strong>，说明那次下跌是正常调整，没有特别的信号意义。"
        
        sections.append({
            'title': '【第二步】从上往下看——量的真假判断',
            'content': [
                f"大阴实顶那天的成交量：{vol_size}。",
                f"<strong>市场机理</strong>：{mechanism}",
                f"<strong>推导</strong>：{conclusion}",
                f"<strong>量学依据</strong>：量是因，价是果。量大说明真有人卖，量小说明跌了也没人接。"
            ]
        })
    
    # ========== 【第三步】从左往右看——量的影响力 ==========
    if stock['big_yin_vol']:
        vol_ratio = stock['today_vs_yin_vol']
        days = stock['days_since_yin']
        
        if vol_ratio > 100:
            vol_judge = f"今天的量比大阴实顶那天还大（{vol_ratio:.1f}%），说明今天的博弈比那天还激烈。"
        elif vol_ratio < 50:
            vol_judge = f"今天的量只有大阴实顶那天的{vol_ratio:.1f}%，说明今天的成交比那天清淡很多。"
        else:
            vol_judge = f"今天的量和大阴实顶那天差不多（{vol_ratio:.1f}%）。"
        
        if days <= 10:
            time_judge = f"时间距离只有{days}天，那个位置的"记忆"还很新鲜。"
        elif days <= 30:
            time_judge = f"时间距离{days}天，那个位置还有一定的影响力。"
        else:
            time_judge = f"时间距离已经{days}天了，那个位置的影响力已经比较弱了。"
        
        sections.append({
            'title': '【第三步】从左往右看——量的影响力',
            'content': [
                f"{vol_judge}",
                f"{time_judge}",
                f"<strong>市场机理</strong>：量越大、时间越近，那个位置的"记忆"就越新鲜，对当下的影响力就越强。就像打仗，刚打完的战场大家都记得住，隔了几个月的战场就没人在乎了。",
                f"<strong>推导</strong>：综合量的大小和时间距离，大阴实顶的量对当下的影响力是<strong>{stock['time_impact']}</strong>。",
                f"<strong>量学依据</strong>：量柱的远近多少，决定了那个量柱对当下的影响力大小。"
            ]
        })
    
    # ========== 【第四步】从下往上看——当下量价建构 ==========
    vol_len = stock['vol_length']
    price_len = stock['price_length']
    body_ratio = stock['body_ratio']
    
    today_direction = "买方" if stock['power'] == "买方占优" else "卖方"
    
    if body_ratio > 60:
        body_judge = f"实体占比{body_ratio:.1f}%，实体较长，说明{today_direction}今天赢了，而且赢得比较彻底。"
    elif body_ratio < 30:
        body_judge = f"实体占比{body_ratio:.1f}%，实体很短，说明今天多空打了个平手，都没占到便宜。"
    else:
        body_judge = f"实体占比{body_ratio:.1f}%，实体中等，说明{today_direction}今天赢了，但赢得不算彻底。"
    
    sections.append({
        'title': '【第四步】从下往上看——当下量价建构',
        'content': [
            f"今天的量柱：{vol_len}；今天的价柱：{price_len}。",
            f"{body_judge}",
            f"<strong>市场机理</strong>：量柱长短=今天多空双方投入了多少兵力；价柱长短=今天战斗的激烈程度；实体长短=今天哪一方赢了，赢得彻不彻底。",
            f"<strong>推导</strong>：今天{vol_len}、{price_len}、{body_judge}",
            f"<strong>量学依据</strong>：量价的长短伸缩，是当下多空力量最直接的体现。"
        ]
    })
    
    # ========== 【第五步】左侧关键位的约束 ==========
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
        key_points.append(f"20日高量柱安全线{stock['safe_20']:.2f}元（{stock['date_20']}）：当前在<strong>{above}</strong>")
    
    if stock['balance_price']:
        above = "上方" if stock['close'] > stock['balance_price'] else "下方"
        key_points.append(f"平衡线{stock['balance_price']:.2f}元（{stock['balance_date']}）：当前在<strong>{above}</strong>")
    
    if key_points:
        sections.append({
            'title': '【第五步】左侧关键位的约束',
            'content': [
                f"当前价格与左侧关键位的关系：",
                *[f"• {kp}" for kp in key_points],
                f"<strong>市场机理</strong>：峰顶线=上次卖方赢了的位置，现在变成压力位；谷底线=上次买方赢了的位置，现在变成支撑位；精准线=多空双方多次在同一价位交手，说明这个位置双方都很看重；高量柱安全线=上次多空最激烈战斗中买方守住的位置。",
                f"<strong>量学依据</strong>：量线是多空双方的"记忆"，每次打到这个位置，都会触发上次的记忆，产生支撑或压力。"
            ]
        })
    
    # ========== 【综合结论】逻辑闭环 ==========
    conclusion_points = []
    
    # 串起前面的推导
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
        conclusion_points.append("大阴实顶那天是小量，说明那次下跌是无量空跌，卖方力量不强")
    elif stock['yin_vol_size'] == "大量":
        conclusion_points.append("大阴实顶那天是大量，说明那次下跌是真出货，上方有真实压力")
    
    conclusion_points.append(f"今天{stock['pct_chg']:+.2f}%，{stock['power']}")
    conclusion_points.append(f"当前在近120日{stock['pos_status']}")
    
    sections.append({
        'title': '【综合结论】逻辑闭环',
        'content': [
            f"把以上五步串起来：",
            *[f"{i+1}. {p}" for i, p in enumerate(conclusion_points)],
            f"<strong>最终判断</strong>：当前价格在{stock['pos_status']}，{stock['power']}，近3日涨跌{stock['pct_3d']:+.2f}%，近5日涨跌{stock['pct_5d']:+.2f}%。",
            f"<strong>注意</strong>：以上是基于量学理论的客观描述，不构成任何交易建议。"
        ]
    })
    
    return sections


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
    
    big_yin_top, big_yin_bottom, big_yin_date, big_yin_vol, big_yin_idx = find_big_yin_top(
        df, YIN_LOOKBACK, YIN_BODY_PCT
    )
    
    if big_yin_top:
        price_vs_yintop = today_price - big_yin_top
        price_vs_yintop_pct = price_vs_yintop / big_yin_top * 100
        price_above_yintop = bool(price_vs_yintop > 0)
    else:
        price_vs_yintop = 0
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
    
    if big_yin_idx:
        days_since_yin = len(df) - 1 - big_yin_idx
    else:
        days_since_yin = 0
    
    if big_yin_vol:
        today_vs_yin_vol = today_volume / big_yin_vol * 100
    else:
        today_vs_yin_vol = 0
    
    if days_since_yin <= 10:
        time_impact = "很近（影响力强）"
    elif days_since_yin <= 30:
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
    
    safe_20, risk_20, type_20, date_20, key_vol_20 = find_gaoliang_lines(recent_20)
    
    safe_60 = risk_60 = type_60 = date_60 = key_vol_60 = None
    recent_60 = df.iloc[-MID_WINDOW:] if len(df) > MID_WINDOW else None
    if recent_60 is not None:
        safe_60, risk_60, type_60, date_60, key_vol_60 = find_gaoliang_lines(recent_60)
    
    safe_120 = risk_120 = type_120 = date_120 = key_vol_120 = None
    recent_120 = df.iloc[-LONG_WINDOW:] if len(df) > LONG_WINDOW else None
    if recent_120 is not None:
        safe_120, risk_120, type_120, date_120, key_vol_120 = find_gaoliang_lines(recent_120)
    
    balance_price, balance_date = find_balance_line(df, BALANCE_LOOKBACK, BALANCE_YIN_BODY_PCT)
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
        'code': f"{market}{code}",
        'date': today['date'],
        'close': today_price,
        'pct_chg': pct_chg,
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
        
        # 峰顶谷底线
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
        
        # 解读HTML
        interp_html = ""
        for section in stock['interpretations']:
            interp_html += f"""
            <div style="margin-bottom: 12px; padding: 10px; background: #0f172a; border-radius: 8px; border-left: 3px solid #fbbf24;">
                <div style="font-weight: bold; color: #fbbf24; margin-bottom: 6px; font-size: 13px;">{section['title']}</div>
            """
            for line in section['content']:
                interp_html += f'                <p style="margin: 4px 0; font-size: 12px; color: #cbd5e1; line-height: 1.7;">{line}</p>\n'
            interp_html += """            </div>"""
        
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
            <div class="note" style="margin-top:10px;font-size:13px;opacity:0.7">量学理论推导版：大阴实顶 + 四维对比 + 左侧关键位 + 逻辑闭环解读</div>
        </div>
        
        <div class="signal-guide">
            <h2>四维看盘法说明</h2>
            
            <div class="signal-item">
                <h3>起点：大阴实顶</h3>
                <p><strong>定义：</strong>从今天往左找最近的中大阴线，其实体顶部就是"大阴实顶"</p>
                <p><strong>原理：</strong>大阴实顶是多空双方上次休战的"警戒点"，下次争夺的"起动点"</p>
                <p class="source">来源：股海明灯（量学官网）</p>
            </div>
            
            <div class="signal-item">
                <h3>① 从右向左看：比较价柱的高低阴阳</h3>
                <p><strong>视线：</strong>从今天往左，往大阴实顶方向看</p>
                <p><strong>对比内容：</strong>价格高低、阴阳数量、阴阳比</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>② 从上往下看：比较量价的真假大小</h3>
                <p><strong>视线：</strong>从大阴实顶的价柱往下看量柱</p>
                <p><strong>对比内容：</strong>量柱大小、量价真假</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>③ 从左往右看：比较量柱的远近多少</h3>
                <p><strong>视线：</strong>从大阴实顶的量柱往右看，看到今天的量柱</p>
                <p><strong>对比内容：</strong>时间距离、量的多少对比</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>④ 从下往上看：比较量价的长短伸缩</h3>
                <p><strong>视线：</strong>从今天的量柱往上看价柱</p>
                <p><strong>对比内容：</strong>量柱长短、价柱伸缩、实体长短</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>⑤ 左侧关键位（量线体系）</h3>
                <p><strong>包含：</strong>平衡线、精准线、斜衡线、峰顶线、谷底线、高量柱安全线/风险线</p>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>综合解读</h3>
                <p><strong>原则：</strong>量学理论驱动的逻辑推导，不是数据罗列</p>
                <p><strong>方法：</strong>每一步都有市场机理、量学依据、推导结论，形成逻辑闭环</p>
            </div>
            
            <div class="signal-item">
                <h3>最高原则</h3>
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
    print("四维循环看盘报告 - HTML版（量学理论推导版）")
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
