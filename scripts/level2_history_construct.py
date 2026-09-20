#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第二层+第三层：左侧历史建构识别 + 影响力评估
=================================================
设计思路（为什么这样写）：
  第二层：找出历史所有重要量柱、价柱、量线
  第三层：给每个关键位打分，评估影响力
  
  打分逻辑（适配量化时代）：
  1. 距离远近（30%）：越近的关键位影响越大
  2. 测试次数（25%）：测试次数越多越重要
  3. 量能大小（25%）：量越大越重要
  4. 时间远近（20%）：越近的历史越重要

硬约束：
  - 绝对不用未来函数
  - 只看过去，不看未来
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 配置
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"

HISTORY_PERIODS = [20, 60, 120, 250]
BEISHU_RATIO = 1.9
BIG_BAR_PCT = 5.0

# 影响力打分权重
WEIGHT_DISTANCE = 0.30   # 距离远近
WEIGHT_TEST_COUNT = 0.25  # 测试次数
WEIGHT_VOLUME = 0.25     # 量能大小
WEIGHT_TIME = 0.20       # 时间远近


# ============================================================
# 数据读取
# ============================================================
def load_klines(filepath):
    with open(filepath, 'r') as f:
        data = json.load(f)
    klines = data.get('klines', [])
    if not klines:
        return None, None
    
    ncols = len(klines[0])
    
    if ncols == 6:
        cols = ['date', 'open', 'close', 'high', 'low', 'volume']
    elif ncols == 7:
        cols = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
    else:
        cols = ['date', 'open', 'close', 'high', 'low', 'volume'] + [f'col{i}' for i in range(7, ncols)]
    
    df = pd.DataFrame(klines)
    df = df.iloc[:, :ncols]
    df.columns = cols[:ncols]
    
    for col in ['open', 'close', 'high', 'low', 'volume']:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
    
    name = data.get('name', filepath.stem)
    return df, name


# ============================================================
# 第一步：识别历史重要量柱（去重版）
# ============================================================
def find_history_vol_columns(df):
    """找出历史所有重要量柱（去重，只保留最长周期）"""
    
    # 先找所有重要量柱
    all_vols = []
    
    for i in range(1, len(df)):
        today_vol = df['volume'].iloc[i]
        prev_vol = df['volume'].iloc[i - 1]
        
        if prev_vol <= 0:
            continue
        
        vol_ratio = today_vol / prev_vol
        date = df['date'].iloc[i]
        days_ago = len(df) - 1 - i
        
        # 倍量柱
        if vol_ratio >= BEISHU_RATIO:
            all_vols.append({
                'type': '倍量柱',
                'date': date,
                'price': df['close'].iloc[i],
                'volume': today_vol,
                'days_ago': days_ago,
                'cycle': 0,  # 倍量柱不区分周期
            })
        
        # 高量柱（找最长周期）
        for period in sorted(HISTORY_PERIODS, reverse=True):  # 从长到短
            if i >= period:
                recent_max = df['volume'].iloc[i-period:i].max()
                if today_vol >= recent_max * 0.999:
                    all_vols.append({
                        'type': f'{period}日高量柱',
                        'date': date,
                        'price': df['close'].iloc[i],
                        'volume': today_vol,
                        'days_ago': days_ago,
                        'cycle': period,
                    })
                    break  # 只保留最长周期
        
        # 低量柱（找最长周期）
        for period in sorted(HISTORY_PERIODS, reverse=True):
            if i >= period:
                recent_min = df['volume'].iloc[i-period:i].min()
                if today_vol <= recent_min * 1.001:
                    all_vols.append({
                        'type': f'{period}日低量柱',
                        'date': date,
                        'price': df['close'].iloc[i],
                        'volume': today_vol,
                        'days_ago': days_ago,
                        'cycle': period,
                    })
                    break
    
    return all_vols


# ============================================================
# 第二步：识别历史重要价柱（去重版）
# ============================================================
def find_history_price_columns(df):
    """找出历史所有重要价柱（去重，只保留最长周期）"""
    
    all_prices = []
    
    for i in range(len(df)):
        date = df['date'].iloc[i]
        days_ago = len(df) - 1 - i
        
        # 大阳线/大阴线
        pct_chg = (df['close'].iloc[i] - df['close'].iloc[i-1]) / df['close'].iloc[i-1] * 100 if i > 0 else 0
        if pct_chg > BIG_BAR_PCT:
            all_prices.append({
                'type': '大阳线',
                'date': date,
                'price': df['close'].iloc[i],
                'high': df['high'].iloc[i],
                'low': df['low'].iloc[i],
                'days_ago': days_ago,
                'cycle': 0,
            })
        if pct_chg < -BIG_BAR_PCT:
            all_prices.append({
                'type': '大阴线',
                'date': date,
                'price': df['close'].iloc[i],
                'high': df['high'].iloc[i],
                'low': df['low'].iloc[i],
                'days_ago': days_ago,
                'cycle': 0,
            })
        
        # 峰顶（找最长周期）
        if i >= max(HISTORY_PERIODS) and i < len(df) - 1:
            for period in sorted(HISTORY_PERIODS, reverse=True):
                if i >= period:
                    recent_high = df['high'].iloc[i-period:i].max()
                    if df['high'].iloc[i] >= recent_high:
                        all_prices.append({
                            'type': f'{period}日峰顶',
                            'date': date,
                            'price': df['high'].iloc[i],
                            'high': df['high'].iloc[i],
                            'low': df['low'].iloc[i],
                            'days_ago': days_ago,
                            'cycle': period,
                        })
                        break
        
        # 谷底（找最长周期）
        if i >= max(HISTORY_PERIODS) and i < len(df) - 1:
            for period in sorted(HISTORY_PERIODS, reverse=True):
                if i >= period:
                    recent_low = df['low'].iloc[i-period:i].min()
                    if df['low'].iloc[i] <= recent_low:
                        all_prices.append({
                            'type': f'{period}日谷底',
                            'date': date,
                            'price': df['low'].iloc[i],
                            'high': df['high'].iloc[i],
                            'low': df['low'].iloc[i],
                            'days_ago': days_ago,
                            'cycle': period,
                        })
                        break
    
    return all_prices


# ============================================================
# 第三步：识别历史重要量线（去重版）
# ============================================================
def find_history_lines(df):
    """找出历史所有重要量线（去重）"""
    
    all_lines = []
    
    for i in range(1, len(df)):
        today_vol = df['volume'].iloc[i]
        prev_vol = df['volume'].iloc[i - 1]
        
        if prev_vol <= 0:
            continue
        
        # 找最长周期的高量柱
        for period in sorted([20, 60], reverse=True):
            if i >= period:
                recent_max = df['volume'].iloc[i-period:i].max()
                if today_vol >= recent_max * 0.999:
                    date = df['date'].iloc[i]
                    days_ago = len(df) - 1 - i
                    
                    # 安全线 = 高量柱实顶
                    body_top = max(df['open'].iloc[i], df['close'].iloc[i])
                    all_lines.append({
                        'type': '高量安全线',
                        'date': date,
                        'price': body_top,
                        'volume': today_vol,
                        'days_ago': days_ago,
                        'cycle': period,
                    })
                    
                    # 风险线 = 高量柱最低价
                    all_lines.append({
                        'type': '高量风险线',
                        'date': date,
                        'price': df['low'].iloc[i],
                        'volume': today_vol,
                        'days_ago': days_ago,
                        'cycle': period,
                    })
                    break
    
    return all_lines


# ============================================================
# 第四步：影响力评估
# ============================================================
def evaluate_influence(all_points, current_price, df):
    """给每个关键位打分，评估影响力"""
    
    if not all_points:
        return []
    
    # 找最大量能（用于归一化）
    max_volume = max(p.get('volume', 0) for p in all_points)
    max_days_ago = max(p['days_ago'] for p in all_points)
    
    scored = []
    
    for point in all_points:
        price = point['price']
        days_ago = point['days_ago']
        volume = point.get('volume', 0)
        
        # 1. 距离分（越近分越高）
        distance = abs(price - current_price) / current_price * 100  # 距离百分比
        distance_score = max(0, 100 - distance * 5)  # 每1%距离扣5分
        
        # 2. 测试次数（简化：周期越长，测试次数越多）
        cycle = point.get('cycle', 0)
        test_score = min(100, cycle / 250 * 100) if cycle > 0 else 50  # 250日=满分
        
        # 3. 量能分
        vol_score = volume / max_volume * 100 if max_volume > 0 else 50
        
        # 4. 时间分（越近分越高）
        time_score = 100 - (days_ago / max_days_ago * 100) if max_days_ago > 0 else 50
        
        # 综合得分
        total_score = (
            distance_score * WEIGHT_DISTANCE +
            test_score * WEIGHT_TEST_COUNT +
            vol_score * WEIGHT_VOLUME +
            time_score * WEIGHT_TIME
        )
        
        # 判断是支撑还是压力
        is_support = price < current_price
        is_resistance = price > current_price
        
        scored.append({
            **point,
            'score': round(total_score, 1),
            'distance_pct': round(distance, 2),
            'is_support': is_support,
            'is_resistance': is_resistance,
        })
    
    return scored


# ============================================================
# 主函数
# ============================================================
def main():
    test_file = DATA_DIR / "sh" / "sh600519.json"
    if not test_file.exists():
        for market_dir in DATA_DIR.iterdir():
            if market_dir.is_dir():
                for f in market_dir.glob('*.json'):
                    test_file = f
                    break
                break
    
    df, name = load_klines(test_file)
    if df is None:
        print("没找到数据")
        return
    
    current_price = df['close'].iloc[-1]
    print(f"股票：{name}")
    print(f"数据量：{len(df)}天")
    print(f"当前价格：{current_price:.2f}")
    
    # 找历史建构
    vol_columns = find_history_vol_columns(df)
    price_columns = find_history_price_columns(df)
    lines = find_history_lines(df)
    
    # 合并所有关键位
    all_points = vol_columns + price_columns + lines
    
    # 影响力评估
    scored_points = evaluate_influence(all_points, current_price, df)
    
    # 分类：支撑位 vs 压力位
    supports = [p for p in scored_points if p['is_support']]
    resistances = [p for p in scored_points if p['is_resistance']]
    
    # 按分数排序
    supports.sort(key=lambda x: x['score'], reverse=True)
    resistances.sort(key=lambda x: x['score'], reverse=True)
    
    print(f"\n{'='*60}")
    print(f"【支撑位排行榜（从强到弱）】共{len(supports)}个")
    print(f"{'='*60}")
    
    for i, s in enumerate(supports[:10]):
        print(f"  {i+1}. {s['price']:.2f}元 | {s['type']} | 强度{s['score']}分 | 距当前{s['distance_pct']}% | {s['days_ago']}天前")
    
    print(f"\n{'='*60}")
    print(f"【压力位排行榜（从强到弱）】共{len(resistances)}个")
    print(f"{'='*60}")
    
    for i, r in enumerate(resistances[:10]):
        print(f"  {i+1}. {r['price']:.2f}元 | {r['type']} | 强度{r['score']}分 | 距当前{r['distance_pct']}% | {r['days_ago']}天前")
    
    # 统计
    print(f"\n{'='*60}")
    print(f"【统计】")
    print(f"{'='*60}")
    print(f"  总关键位：{len(all_points)}个")
    print(f"  支撑位：{len(supports)}个")
    print(f"  压力位：{len(resistances)}个")
    print(f"  当前位置：在{len(supports)}个支撑和{len(resistances)}个压力之间")


if __name__ == "__main__":
    main()
