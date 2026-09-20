#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主力行为判断逻辑历史回测（V2）
=================================================
设计思路（为什么这样写）：
  用新的判断逻辑跑历史回测！
  新逻辑：量价关系 + 位置 = 主力行为

硬约束：
  - 绝对不用未来函数
  - 只保存统计结果，不保存原始样本数据
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# ============================================================
# 配置
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

MIN_DATA_DAYS = 60
LOOKBACK_DAYS = 250  # 回顾过去250个交易日（约1年）
HOLD_DAYS_LIST = [5, 10, 20]  # 持有5天/10天/20天看收益


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
# 计算当日指标
# ============================================================
def calc_daily_indicators(df):
    df['pct_chg'] = (df['close'] - df['close'].shift(1)) / df['close'].shift(1) * 100
    
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ratio_ma5'] = df['volume'] / df['vol_ma5']
    
    df['high_120'] = df['high'].rolling(120).max()
    df['low_120'] = df['low'].rolling(120).min()
    df['position_pct'] = (df['close'] - df['low_120']) / (df['high_120'] - df['low_120']) * 100
    
    df['pct_20d'] = (df['close'] - df['close'].shift(20)) / df['close'].shift(20) * 100
    
    return df


# ============================================================
# 主力行为判断（V2 - 量价关系+位置）
# ============================================================
def judge_main_behavior(row):
    position = row['position_pct']
    vol_ratio = row['vol_ratio_ma5']
    pct_chg = row['pct_chg']
    pct_20d = row['pct_20d']
    
    if pd.isna(position) or pd.isna(vol_ratio):
        return None
    
    scores = {
        '建仓初期': 0,
        '建仓后期': 0,
        '洗盘': 0,
        '拉升': 0,
        '出货': 0,
    }
    
    # 1. 当日大涨+放量 → 拉升
    if pct_chg > 3 and vol_ratio > 1.5:
        scores['拉升'] += 50
    
    # 2. 当日大跌+放量 → 出货
    elif pct_chg < -3 and vol_ratio > 1.5:
        scores['出货'] += 50
    
    # 3. 当日上涨+放量 → 建仓后期或拉升
    elif pct_chg > 1 and vol_ratio > 1.3:
        if position < 30:
            scores['建仓后期'] += 30
        else:
            scores['拉升'] += 30
    
    # 4. 当日下跌+缩量 → 洗盘或建仓
    elif pct_chg < -1 and vol_ratio < 0.8:
        if position < 30:
            scores['建仓初期'] += 30
        else:
            scores['洗盘'] += 30
    
    # 5. 20日大涨+放量 → 拉升
    if not pd.isna(pct_20d):
        if pct_20d > 15 and vol_ratio > 1.2:
            scores['拉升'] += 30
        
        # 6. 20日大跌 → 建仓初期或出货
        elif pct_20d < -15:
            if position < 30:
                scores['建仓初期'] += 30
            else:
                scores['出货'] += 20
    
    # 7. 位置高的 → 出货
    if position > 80:
        scores['出货'] += 30
    elif position > 70:
        scores['出货'] += 20
    
    # 8. 位置低的 → 建仓
    if position < 10:
        scores['建仓初期'] += 30
    elif position < 30:
        scores['建仓后期'] += 20
    
    # 找最高分
    best_stage = max(scores, key=scores.get)
    total_score = sum(scores.values())
    
    # 如果所有scores都是0，给个默认判断
    if total_score == 0:
        if position < 30:
            best_stage = '建仓后期'
        elif position < 70:
            best_stage = '洗盘'
        else:
            best_stage = '出货'
    
    return best_stage


# ============================================================
# 主函数
# ============================================================
def main():
    print("="*70)
    print("主力行为判断逻辑历史回测（V2）")
    print("="*70)
    
    all_files = []
    for market_dir in DATA_DIR.iterdir():
        if market_dir.is_dir():
            for f in market_dir.glob('*.json'):
                all_files.append(f)
    
    print(f"共{len(all_files)}只股票")
    print(f"回顾过去{LOOKBACK_DAYS}个交易日（约一年）")
    
    # 只统计，不保存原始数据
    stage_stats = {}
    total_samples = 0
    
    total_files = len(all_files)
    
    for i, filepath in enumerate(all_files):
        if (i + 1) % 500 == 0:
            print(f"  进度 {i+1}/{total_files} | 累计样本 {total_samples}")
        
        df, name = load_klines(filepath)
        if df is None or len(df) < MIN_DATA_DAYS + LOOKBACK_DAYS + 20:
            continue
        
        df = calc_daily_indicators(df)
        
        start_idx = len(df) - LOOKBACK_DAYS - 20
        end_idx = len(df) - 20
        
        for idx in range(start_idx, end_idx):
            row = df.iloc[idx]
            
            stage = judge_main_behavior(row)
            if stage is None:
                continue
            
            if stage not in stage_stats:
                stage_stats[stage] = {
                    'count': 0,
                    'rets': {h: [] for h in HOLD_DAYS_LIST}
                }
            
            stage_stats[stage]['count'] += 1
            total_samples += 1
            
            entry_price = row['close']
            
            for hold_days in HOLD_DAYS_LIST:
                future_idx = idx + hold_days
                if future_idx < len(df):
                    future_price = df.iloc[future_idx]['close']
                    ret = (future_price - entry_price) / entry_price * 100
                    stage_stats[stage]['rets'][hold_days].append(ret)
    
    print("\n" + "="*70)
    print("回测结果（V2新逻辑）")
    print("="*70)
    print(f"总样本数：{total_samples}个")
    
    for hold_days in HOLD_DAYS_LIST:
        print(f"\n=== 持有{hold_days}天 ===")
        print(f"{'阶段':<10} {'样本数':>8} {'中位数%':>10} {'均值%':>10} {'胜率%':>10}")
        print("-" * 55)
        
        for stage in ['建仓初期', '建仓后期', '洗盘', '拉升', '出货']:
            if stage not in stage_stats:
                continue
            
            rets = stage_stats[stage]['rets'][hold_days]
            if not rets:
                continue
            
            count = len(rets)
            median = np.median(rets)
            mean = np.mean(rets)
            win_rate = sum(1 for r in rets if r > 0) / count * 100
            
            print(f"{stage:<10} {count:>8} {median:>10.2f} {mean:>10.2f} {win_rate:>10.1f}")
    
    # 保存统计结果
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_file = OUTPUT_DIR / "behavior_backtest_summary_v2.txt"
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("主力行为判断逻辑历史回测结果（V2）\n")
        f.write("="*50 + "\n")
        f.write(f"总样本数：{total_samples}个\n\n")
        
        for hold_days in HOLD_DAYS_LIST:
            f.write(f"\n=== 持有{hold_days}天 ===\n")
            f.write(f"{'阶段':<10} {'样本数':>8} {'中位数%':>10} {'均值%':>10} {'胜率%':>10}\n")
            f.write("-" * 55 + "\n")
            
            for stage in ['建仓初期', '建仓后期', '洗盘', '拉升', '出货']:
                if stage not in stage_stats:
                    continue
                
                rets = stage_stats[stage]['rets'][hold_days]
                if not rets:
                    continue
                
                count = len(rets)
                median = np.median(rets)
                mean = np.mean(rets)
                win_rate = sum(1 for r in rets if r > 0) / count * 100
                
                f.write(f"{stage:<10} {count:>8} {median:>10.2f} {mean:>10.2f} {win_rate:>10.1f}\n")
    
    print(f"\n已保存统计结果: {summary_file}")


if __name__ == "__main__":
    main()
