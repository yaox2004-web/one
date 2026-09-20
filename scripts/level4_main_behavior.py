#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第四层：主力行为意图判断
=================================================
设计思路（为什么这样写）：
  综合第一层（当日快照）+ 第二三层（左侧关键位）
  判断主力现在处于哪个阶段。
  
  四个阶段：
  1. 建仓：低位放量+缩量不跌
  2. 洗盘：高位缩量+不破关键位
  3. 拉升：价升量增+突破关键位
  4. 出货：高位放量+滞涨

硬约束：
  - 绝对不用未来函数
  - 只看过去和当下
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

WEIGHT_DISTANCE = 0.30
WEIGHT_TEST_COUNT = 0.25
WEIGHT_VOLUME = 0.25
WEIGHT_TIME = 0.20


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
    """找出左侧关键位（简化版）"""
    
    current_price = df['close'].iloc[-1]
    
    supports = []
    resistances = []
    
    # 找最近的高量柱和低量柱
    for i in range(max(0, len(df)-120), len(df)):
        days_ago = len(df) - 1 - i
        
        if days_ago > 250:
            continue
        
        # 高量柱
        if i >= 20:
            recent_max = df['volume'].iloc[i-20:i].max()
            if df['volume'].iloc[i] >= recent_max * 0.999:
                price = df['close'].iloc[i]
                if price < current_price:
                    supports.append({'price': price, 'type': '高量柱', 'days_ago': days_ago})
                else:
                    resistances.append({'price': price, 'type': '高量柱', 'days_ago': days_ago})
        
        # 低量柱
        if i >= 20:
            recent_min = df['volume'].iloc[i-20:i].min()
            if df['volume'].iloc[i] <= recent_min * 1.001:
                price = df['close'].iloc[i]
                if price < current_price:
                    supports.append({'price': price, 'type': '低量柱', 'days_ago': days_ago})
                else:
                    resistances.append({'price': price, 'type': '低量柱', 'days_ago': days_ago})
    
    # 找峰顶和谷底
    for i in range(max(0, len(df)-120), len(df)):
        days_ago = len(df) - 1 - i
        
        if days_ago > 250:
            continue
        
        if i >= 20 and i < len(df) - 1:
            # 峰顶
            recent_high = df['high'].iloc[i-20:i].max()
            if df['high'].iloc[i] >= recent_high:
                price = df['high'].iloc[i]
                if price < current_price:
                    supports.append({'price': price, 'type': '峰顶', 'days_ago': days_ago})
                else:
                    resistances.append({'price': price, 'type': '峰顶', 'days_ago': days_ago})
            
            # 谷底
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
    """判断主力现在处于哪个阶段"""
    
    latest = df.iloc[-1]
    
    position = latest['position_pct']  # 位置分位
    vol_ratio = latest['vol_ratio_ma5']  # 量比
    pct_chg = latest['pct_chg']  # 涨跌幅
    above_ma20 = latest['above_ma20']  # MA20之上
    
    # 找最近的支撑和压力
    current_price = latest['close']
    nearest_support = min(supports, key=lambda x: abs(x['price'] - current_price))['price'] if supports else current_price * 0.95
    nearest_resistance = min(resistances, key=lambda x: abs(x['price'] - current_price))['price'] if resistances else current_price * 1.05
    
    # 判断逻辑
    scores = {
        '建仓': 0,
        '洗盘': 0,
        '拉升': 0,
        '出货': 0,
    }
    
    reasons = {
        '建仓': [],
        '洗盘': [],
        '拉升': [],
        '出货': [],
    }
    
    # 1. 位置分位判断
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
    
    # 2. 量能判断
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
    
    # 3. 价格表现
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
    
    # 4. 均线位置
    if above_ma20:
        scores['拉升'] += 10
        reasons['拉升'].append(f'MA20之上')
    else:
        if position < 30:
            scores['建仓'] += 10
            reasons['建仓'].append(f'MA20之下（低位）')
    
    # 5. 距最近支撑/压力
    dist_to_support = (current_price - nearest_support) / current_price * 100
    dist_to_resistance = (nearest_resistance - current_price) / current_price * 100
    
    if dist_to_support < 2 and position < 50:
        scores['建仓'] += 10
        reasons['建仓'].append(f'接近支撑位{nearest_support:.2f}')
    
    if dist_to_resistance < 2 and position > 50:
        scores['出货'] += 10
        reasons['出货'].append(f'接近压力位{nearest_resistance:.2f}')
    
    # 找最高分
    best_stage = max(scores, key=scores.get)
    best_score = scores[best_stage]
    
    # 置信度（归一化）
    total_score = sum(scores.values())
    confidence = best_score / total_score * 100 if total_score > 0 else 0
    
    return best_stage, confidence, reasons[best_stage], scores


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
    
    print(f"股票：{name}")
    print(f"当前价格：{df['close'].iloc[-1]:.2f}")
    
    # 第一层
    df = calc_daily_indicators(df)
    latest = df.iloc[-1]
    
    print(f"\n【当日快照】")
    print(f"  涨跌幅：{latest['pct_chg']:.2f}%")
    print(f"  量比(vs5日)：{latest['vol_ratio_ma5']:.2f}")
    print(f"  位置分位：{latest['position_pct']:.1f}%")
    print(f"  MA20：{'之上' if latest['above_ma20'] else '之下'}")
    
    # 第二三层
    supports, resistances = find_key_levels(df)
    
    print(f"\n【左侧关键位】")
    print(f"  支撑位：{len(supports)}个")
    print(f"  压力位：{len(resistances)}个")
    
    # 第四层
    best_stage, confidence, reasons, scores = judge_main_behavior(df, supports, resistances)
    
    print(f"\n{'='*60}")
    print(f"【主力行为判断】")
    print(f"{'='*60}")
    print(f"  当前阶段：{best_stage}")
    print(f"  置信度：{confidence:.1f}%")
    print(f"  依据：")
    for r in reasons:
        print(f"    - {r}")
    
    print(f"\n  各阶段得分：")
    for stage, score in scores.items():
        bar = '█' * int(score / 5)
        print(f"    {stage}: {score:3d}分 {bar}")


if __name__ == "__main__":
    main()

