#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整系统：第一层~第六层
=================================================
设计思路（为什么这样写）：
  这是一个完整的主力行为识别系统，包括：
  1. 第一层：当日快照
  2. 第二层：左侧历史建构
  3. 第三层：左侧影响力评估
  4. 第四层：主力行为意图判断
  5. 第五层：环境过滤（大盘）
  6. 第六层：综合输出（诊断报告）

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
    """找出左侧关键位"""
    
    current_price = df['close'].iloc[-1]
    
    supports = []
    resistances = []
    
    for i in range(max(0, len(df)-250), len(df)):
        days_ago = len(df) - 1 - i
        
        if days_ago > 250:
            continue
        
        # 高量柱
        if i >= 20:
            recent_max = df['volume'].iloc[i-20:i].max()
            if df['volume'].iloc[i] >= recent_max * 0.999:
                price = df['close'].iloc[i]
                if price < current_price:
                    supports.append({'price': price, 'type': '高量柱', 'days_ago': days_ago, 'volume': df['volume'].iloc[i]})
                else:
                    resistances.append({'price': price, 'type': '高量柱', 'days_ago': days_ago, 'volume': df['volume'].iloc[i]})
        
        # 低量柱
        if i >= 20:
            recent_min = df['volume'].iloc[i-20:i].min()
            if df['volume'].iloc[i] <= recent_min * 1.001:
                price = df['close'].iloc[i]
                if price < current_price:
                    supports.append({'price': price, 'type': '低量柱', 'days_ago': days_ago, 'volume': df['volume'].iloc[i]})
                else:
                    resistances.append({'price': price, 'type': '低量柱', 'days_ago': days_ago, 'volume': df['volume'].iloc[i]})
        
        # 峰顶
        if i >= 20 and i < len(df) - 1:
            recent_high = df['high'].iloc[i-20:i].max()
            if df['high'].iloc[i] >= recent_high:
                price = df['high'].iloc[i]
                if price < current_price:
                    supports.append({'price': price, 'type': '峰顶', 'days_ago': days_ago, 'volume': df['volume'].iloc[i]})
                else:
                    resistances.append({'price': price, 'type': '峰顶', 'days_ago': days_ago, 'volume': df['volume'].iloc[i]})
            
            # 谷底
            recent_low = df['low'].iloc[i-20:i].min()
            if df['low'].iloc[i] <= recent_low:
                price = df['low'].iloc[i]
                if price < current_price:
                    supports.append({'price': price, 'type': '谷底', 'days_ago': days_ago, 'volume': df['volume'].iloc[i]})
                else:
                    resistances.append({'price': price, 'type': '谷底', 'days_ago': days_ago, 'volume': df['volume'].iloc[i]})
    
    return supports, resistances


# ============================================================
# 第四层：主力行为意图判断
# ============================================================
def judge_main_behavior(df, supports, resistances):
    """判断主力现在处于哪个阶段"""
    
    latest = df.iloc[-1]
    
    position = latest['position_pct']
    vol_ratio = latest['vol_ratio_ma5']
    pct_chg = latest['pct_chg']
    above_ma20 = latest['above_ma20']
    
    current_price = latest['close']
    nearest_support = min(supports, key=lambda x: abs(x['price'] - current_price))['price'] if supports else current_price * 0.95
    nearest_resistance = min(resistances, key=lambda x: abs(x['price'] - current_price))['price'] if resistances else current_price * 1.05
    
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
    
    best_stage = max(scores, key=scores.get)
    best_score = scores[best_stage]
    
    total_score = sum(scores.values())
    confidence = best_score / total_score * 100 if total_score > 0 else 0
    
    return best_stage, confidence, reasons[best_stage], scores


# ============================================================
# 第五层：环境过滤
# ============================================================
def check_market_env():
    """检查大盘环境"""
    
    # 找大盘数据
    market_file = DATA_DIR / "sh" / "sh000001.json"
    if not market_file.exists():
        return None, None
    
    df, _ = load_klines(market_file)
    if df is None or len(df) < 20:
        return None, None
    
    latest = df.iloc[-1]
    
    # 计算MA20
    ma20 = df['close'].rolling(20).mean().iloc[-1]
    above_ma20 = latest['close'] > ma20
    
    # 计算大盘近期趋势
    pct_20 = (latest['close'] - df['close'].iloc[-20]) / df['close'].iloc[-20] * 100
    
    return above_ma20, pct_20


# ============================================================
# 第六层：综合输出
# ============================================================
def print_diagnostic_report(name, df, supports, resistances, best_stage, confidence, reasons, scores):
    """打印完整的主力行为诊断报告"""
    
    latest = df.iloc[-1]
    current_price = latest['close']
    
    print(f"╔════════════════════════════════════════════════════════════╗")
    print(f"║              主力行为诊断报告                              ║")
    print(f"╠════════════════════════════════════════════════════════════╣")
    print(f"║  股票：{name:<48s}║")
    print(f"║  日期：{str(latest['date']):<48s}║")
    print(f"║  价格：{current_price:>10.2f}元                                ║")
    print(f"╚════════════════════════════════════════════════════════════╝")
    
    # 当日快照
    print(f"\n【一、当日快照】")
    print(f"  涨跌幅：{latest['pct_chg']:+.2f}%")
    print(f"  振幅：{latest['amplitude']:.2f}%")
    print(f"  量比(vs5日)：{latest['vol_ratio_ma5']:.2f}")
    print(f"  位置分位：{latest['position_pct']:.1f}%")
    print(f"  MA20：{'之上' if latest['above_ma20'] else '之下'}")
    
    # 左侧关键位
    print(f"\n【二、左侧关键位】")
    print(f"  支撑位（下方）：{len(supports)}个")
    if supports:
        supports_sorted = sorted(supports, key=lambda x: abs(x['price'] - current_price))
        for i, s in enumerate(supports_sorted[:5]):
            dist = (current_price - s['price']) / current_price * 100
            print(f"    {i+1}. {s['price']:.2f}元 | {s['type']} | 距当前{dist:.1f}% | {s['days_ago']}天前")
    
    print(f"\n  压力位（上方）：{len(resistances)}个")
    if resistances:
        resistances_sorted = sorted(resistances, key=lambda x: abs(x['price'] - current_price))
        for i, r in enumerate(resistances_sorted[:5]):
            dist = (r['price'] - current_price) / current_price * 100
            print(f"    {i+1}. {r['price']:.2f}元 | {r['type']} | 距当前{dist:.1f}% | {r['days_ago']}天前")
    
    # 主力阶段
    print(f"\n【三、主力阶段判断】")
    print(f"  当前阶段：{best_stage}")
    print(f"  置信度：{confidence:.1f}%")
    print(f"  依据：")
    for r in reasons:
        print(f"    - {r}")
    
    print(f"\n  各阶段得分：")
    for stage, score in scores.items():
        bar = '█' * int(score / 5)
        print(f"    {stage}: {score:3d}分 {bar}")
    
    # 环境过滤
    above_ma20, pct_20 = check_market_env()
    print(f"\n【四、大盘环境】")
    if above_ma20 is not None:
        print(f"  大盘MA20：{'之上' if above_ma20 else '之下'}")
        print(f"  大盘20日涨跌：{pct_20:+.2f}%")
        if above_ma20 and pct_20 > 0:
            print(f"  环境判断：偏多")
        elif not above_ma20 and pct_20 < 0:
            print(f"  环境判断：偏空")
        else:
            print(f"  环境判断：震荡")
    else:
        print(f"  无大盘数据")
    
    print(f"\n{'═'*60}")
    print(f"总结：当前主力可能处于【{best_stage}】阶段，置信度{confidence:.1f}%")
    print(f"{'═'*60}")


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
    
    # 第一层
    df = calc_daily_indicators(df)
    
    # 第二三层
    supports, resistances = find_key_levels(df)
    
    # 第四层
    best_stage, confidence, reasons, scores = judge_main_behavior(df, supports, resistances)
    
    # 第六层：综合输出
    print_diagnostic_report(name, df, supports, resistances, best_stage, confidence, reasons, scores)


if __name__ == "__main__":
    main()
