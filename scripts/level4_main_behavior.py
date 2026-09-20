#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整系统：第一层~第六层（多股测试版）
=================================================
设计思路（为什么这样写）：
  测试多只不同类型的股票，看看系统判断准不准。
  
  测试股票选择：
  1. 贵州茅台（大盘蓝筹）
  2. 宁德时代（新能源龙头）
  3. 比亚迪（新能源汽车）
  4. 中芯国际（半导体）
  5. 东方财富（券商）

硬约束：
  - 绝对不用未来函数
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

# 测试股票列表
TEST_STOCKS = [
    ("sh", "sh600519", "贵州茅台"),
    ("sz", "sz300750", "宁德时代"),
    ("sz", "sz002594", "比亚迪"),
    ("sh", "sh688981", "中芯国际"),
    ("sz", "sz300059", "东方财富"),
]


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
# 第一层：计算当日指标
# ============================================================
def calc_daily_indicators(df):
    df['pct_chg'] = (df['close'] - df['close'].shift(1)) / df['close'].shift(1) * 100
    df['amplitude'] = (df['high'] - df['low']) / df['close'].shift(1) * 100
    df['vol_ratio_yesterday'] = df['volume'] / df['volume'].shift(1)
    
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ratio_ma5'] = df['volume'] / df['vol_ma5']
    
    df['high_120'] = df['high'].rolling(120).max()
    df['low_120'] = df['low'].rolling(120).min()
    df['position_pct'] = (df['close'] - df['low_120']) / (df['high_120'] - df['low_120']) * 100
    
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['above_ma20'] = df['close'] > df['ma20']
    
    return df


# ============================================================
# 第二三层：找左侧关键位
# ============================================================
def find_key_levels(df):
    current_price = df['close'].iloc[-1]
    
    supports = []
    resistances = []
    
    for i in range(max(0, len(df)-250), len(df)):
        days_ago = len(df) - 1 - i
        
        if days_ago > 250:
            continue
        
        if i >= 20:
            recent_max = df['volume'].iloc[i-20:i].max()
            if df['volume'].iloc[i] >= recent_max * 0.999:
                price = df['close'].iloc[i]
                if price < current_price:
                    supports.append({'price': price, 'type': '高量柱', 'days_ago': days_ago})
                else:
                    resistances.append({'price': price, 'type': '高量柱', 'days_ago': days_ago})
            
            recent_min = df['volume'].iloc[i-20:i].min()
            if df['volume'].iloc[i] <= recent_min * 1.001:
                price = df['close'].iloc[i]
                if price < current_price:
                    supports.append({'price': price, 'type': '低量柱', 'days_ago': days_ago})
                else:
                    resistances.append({'price': price, 'type': '低量柱', 'days_ago': days_ago})
        
        if i >= 20 and i < len(df) - 1:
            recent_high = df['high'].iloc[i-20:i].max()
            if df['high'].iloc[i] >= recent_high:
                price = df['high'].iloc[i]
                if price < current_price:
                    supports.append({'price': price, 'type': '峰顶', 'days_ago': days_ago})
                else:
                    resistances.append({'price': price, 'type': '峰顶', 'days_ago': days_ago})
            
            recent_low = df['low'].iloc[i-20:i].min()
            if df['low'].iloc[i] <= recent_low:
                price = df['low'].iloc[i]
                if price < current_price:
                    supports.append({'price': price, 'type': '谷底', 'days_ago': days_ago})
                else:
                    resistances.append({'price': price, 'type': '谷底', 'days_ago': days_ago})
    
    return supports, resistances


# ============================================================
# 第四层：主力行为意图判断
# ============================================================
def judge_main_behavior(df, supports, resistances):
    latest = df.iloc[-1]
    
    position = latest['position_pct']
    vol_ratio = latest['vol_ratio_ma5']
    pct_chg = latest['pct_chg']
    above_ma20 = latest['above_ma20']
    
    current_price = latest['close']
    nearest_support = min(supports, key=lambda x: abs(x['price'] - current_price))['price'] if supports else current_price * 0.95
    nearest_resistance = min(resistances, key=lambda x: abs(x['price'] - current_price))['price'] if resistances else current_price * 1.05
    
    scores = {'建仓': 0, '洗盘': 0, '拉升': 0, '出货': 0}
    reasons = {'建仓': [], '洗盘': [], '拉升': [], '出货': []}
    
    if position < 30:
        scores['建仓'] += 30
        reasons['建仓'].append(f'位置分位{position:.1f}%（低位）')
    elif position < 50:
        scores['建仓'] += 15
        scores['洗盘'] += 15
        reasons['建仓'].append(f'位置分位{position:.1f}%（中低位）')
    elif position < 70:
        scores['洗盘'] += 30
        reasons['洗盘'].append(f'位置分位{position:.1f}%（中位）')
    else:
        scores['出货'] += 30
        reasons['出货'].append(f'位置分位{position:.1f}%（高位）')
    
    if vol_ratio > 1.5:
        if position < 50:
            scores['建仓'] += 25
            reasons['建仓'].append(f'放量（量比{vol_ratio:.2f}）')
        else:
            scores['出货'] += 25
            reasons['出货'].append(f'高位放量（量比{vol_ratio:.2f}）')
    elif vol_ratio < 0.8:
        if position > 50:
            scores['洗盘'] += 25
            reasons['洗盘'].append(f'缩量（量比{vol_ratio:.2f}）')
        else:
            scores['建仓'] += 10
            reasons['建仓'].append(f'低位缩量（量比{vol_ratio:.2f}）')
    
    if pct_chg > 3:
        if position > 50:
            scores['拉升'] += 25
            reasons['拉升'].append(f'大涨{pct_chg:.2f}%')
        else:
            scores['建仓'] += 15
            reasons['建仓'].append(f'低位涨{pct_chg:.2f}%')
    elif pct_chg < -3:
        if position > 70:
            scores['出货'] += 20
            reasons['出货'].append(f'高位跌{pct_chg:.2f}%')
    elif abs(pct_chg) < 1:
        if position > 50 and vol_ratio < 0.8:
            scores['洗盘'] += 20
            reasons['洗盘'].append(f'缩量横盘')
    
    if above_ma20:
        scores['拉升'] += 10
        reasons['拉升'].append(f'MA20之上')
    else:
        if position < 30:
            scores['建仓'] += 10
            reasons['建仓'].append(f'MA20之下（低位）')
    
    dist_to_support = (current_price - nearest_support) / current_price * 100
    dist_to_resistance = (nearest_resistance - current_price) / current_price * 100
    
    if dist_to_support < 2 and position < 50:
        scores['建仓'] += 10
        reasons['建仓'].append(f'接近支撑位{nearest_support:.2f}')
    
    if dist_to_resistance < 2 and position > 50:
        scores['出货'] += 10
        reasons['出货'].append(f'接近压力位{nearest_resistance:.2f}')
    
    best_stage = max(scores, key=scores.get)
    best_score = scores[best_stage]
    
    total_score = sum(scores.values())
    confidence = best_score / total_score * 100 if total_score > 0 else 0
    
    return best_stage, confidence, reasons[best_stage], scores, position, vol_ratio


# ============================================================
# 主函数：多股测试
# ============================================================
def main():
    print("="*70)
    print("多股测试：看看系统判断准不准")
    print("="*70)
    
    results = []
    
    for market, code, name in TEST_STOCKS:
        filepath = DATA_DIR / market / f"{code}.json"
        
        if not filepath.exists():
            print(f"\n【{name}】文件不存在，跳过")
            continue
        
        df, _ = load_klines(filepath)
        if df is None or len(df) < 60:
            print(f"\n【{name}】数据不够，跳过")
            continue
        
        # 跑系统
        df = calc_daily_indicators(df)
        supports, resistances = find_key_levels(df)
        best_stage, confidence, reasons, scores, position, vol_ratio = judge_main_behavior(df, supports, resistances)
        
        current_price = df['close'].iloc[-1]
        latest_date = df['date'].iloc[-1]
        
        results.append({
            'name': name,
            'price': current_price,
            'position': position,
            'vol_ratio': vol_ratio,
            'stage': best_stage,
            'confidence': confidence,
            'support_count': len(supports),
            'resistance_count': len(resistances),
        })
        
        print(f"\n【{name}】")
        print(f"  价格：{current_price:.2f}元 | 日期：{latest_date}")
        print(f"  位置分位：{position:.1f}% | 量比：{vol_ratio:.2f}")
        print(f"  判断：{best_stage}（置信度{confidence:.1f}%）")
        print(f"  支撑位：{len(supports)}个 | 压力位：{len(resistances)}个")
    
    # 汇总
    print(f"\n{'='*70}")
    print("汇总")
    print(f"{'='*70}")
    print(f"{'股票':<12s} {'价格':>8s} {'位置分位':>8s} {'量比':>6s} {'判断':<6s} {'置信度':>6s}")
    print("-"*70)
    
    for r in results:
        print(f"{r['name']:<12s} {r['price']:>8.2f} {r['position']:>7.1f}% {r['vol_ratio']:>6.2f} {r['stage']:<6s} {r['confidence']:>5.1f}%")


if __name__ == "__main__":
    main()
