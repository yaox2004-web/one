#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主力行为判断逻辑历史回测
=================================================
设计思路（为什么这样写）：
  验证我们的判断逻辑历史上准不准！
  做法：
  1. 用过去1年的数据，在每个历史日期判断主力阶段
  2. 然后看接下来5天/10天/20天的涨跌幅
  3. 看看：
     - 判断为"拉升"的股票，后来真的涨了吗？
     - 判断为"出货"的股票，后来真的跌了吗？
  4. 算一下各阶段的胜率和收益率

硬约束：
  - 绝对不用未来函数（判断时只用截止到当天的数据）
  - 只保存统计结果，不保存原始样本数据（避免文件太大）
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
    
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['above_ma20'] = df['close'] > df['ma20']
    df['above_ma60'] = df['close'] > df['ma60']
    
    df['pct_20d'] = (df['close'] - df['close'].shift(20)) / df['close'].shift(20) * 100
    
    # 连续状态
    df['consec_vol_up_3d'] = (df['vol_ratio_ma5'] > 1.2) & \
                             (df['vol_ratio_ma5'].shift(1) > 1.2) & \
                             (df['vol_ratio_ma5'].shift(2) > 1.2)
    
    df['consec_vol_down_3d'] = (df['vol_ratio_ma5'] < 0.8) & \
                               (df['vol_ratio_ma5'].shift(1) < 0.8) & \
                               (df['vol_ratio_ma5'].shift(2) < 0.8)
    
    # 量价配合
    df['price_up_vol_up'] = (df['pct_chg'] > 0) & (df['vol_ratio_ma5'] > 1.2)
    df['price_down_vol_down'] = (df['pct_chg'] < 0) & (df['vol_ratio_ma5'] < 0.8)
    
    return df


# ============================================================
# 主力行为意图判断
# ============================================================
def judge_main_behavior(df_row):
    position = df_row['position_pct']
    vol_ratio = df_row['vol_ratio_ma5']
    pct_chg = df_row['pct_chg']
    pct_20d = df_row['pct_20d']
    above_ma20 = df_row['above_ma20']
    above_ma60 = df_row['above_ma60']
    
    if pd.isna(position) or pd.isna(vol_ratio):
        return None
    
    scores = {
        '建仓初期': 0,
        '建仓后期': 0,
        '洗盘': 0,
        '拉升': 0,
        '出货': 0,
    }
    
    # 1. 位置分位
    if position < 10:
        scores['建仓初期'] += 40
    elif position < 30:
        scores['建仓后期'] += 30
    elif position < 50:
        scores['建仓后期'] += 15
        scores['洗盘'] += 15
    elif position < 70:
        scores['洗盘'] += 30
    elif position < 85:
        scores['出货'] += 30
    else:
        scores['出货'] += 40
    
    # 2. 量能
    if vol_ratio > 1.5:
        if position < 30:
            scores['建仓后期'] += 25
        elif position < 70:
            scores['拉升'] += 25
        else:
            scores['出货'] += 25
    elif vol_ratio < 0.7:
        if position < 30:
            scores['建仓初期'] += 25
        elif position < 70:
            scores['洗盘'] += 25
        else:
            scores['出货'] += 10
    
    # 3. 20日涨跌幅
    if not pd.isna(pct_20d):
        if pct_20d > 15:
            if position > 50:
                scores['拉升'] += 25
            else:
                scores['建仓后期'] += 15
        elif pct_20d > 5:
            if position > 50:
                scores['拉升'] += 15
            else:
                scores['建仓后期'] += 10
        elif pct_20d < -15:
            if position < 30:
                scores['建仓初期'] += 15
            else:
                scores['出货'] += 15
    
    # 4. 当日涨跌幅
    if pct_chg > 3:
        if position > 50:
            scores['拉升'] += 15
        else:
            scores['建仓后期'] += 10
    elif pct_chg < -3:
        if position > 70:
            scores['出货'] += 15
    
    # 5. 均线位置
    if above_ma20:
        if position > 50:
            scores['拉升'] += 10
        else:
            scores['建仓后期'] += 5
    else:
        if position < 30:
            scores['建仓初期'] += 10
    
    if above_ma60:
        if position > 50:
            scores['拉升'] += 5
    else:
        if position < 30:
            scores['建仓初期'] += 5
    
    # 6. 连续状态
    if df_row['consec_vol_up_3d']:
        if position < 30:
            scores['建仓后期'] += 15
        elif position < 70:
            scores['拉升'] += 15
        else:
            scores['出货'] += 15
    
    if df_row['consec_vol_down_3d']:
        if position < 30:
            scores['建仓初期'] += 15
        elif position < 70:
            scores['洗盘'] += 15
    
    # 7. 量价配合
    if df_row['price_up_vol_up']:
        if position > 50:
            scores['拉升'] += 10
        else:
            scores['建仓后期'] += 5
    
    if df_row['price_down_vol_down']:
        if position < 30:
            scores['建仓初期'] += 10
        elif position > 70:
            scores['出货'] += 10
    
    best_stage = max(scores, key=scores.get)
    return best_stage


# ============================================================
# 主函数
# ============================================================
def main():
    print("="*70)
    print("主力行为判断逻辑历史回测")
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
        
        # 从倒数第LOOKBACK_DAYS天开始，逐个日期判断
        start_idx = len(df) - LOOKBACK_DAYS - 20
        end_idx = len(df) - 20
        
        for idx in range(start_idx, end_idx):
            row = df.iloc[idx]
            
            # 判断主力阶段
            stage = judge_main_behavior(row)
            if stage is None:
                continue
            
            # 初始化统计
            if stage not in stage_stats:
                stage_stats[stage] = {
                    'count': 0,
                    'rets': {h: [] for h in HOLD_DAYS_LIST}
                }
            
            stage_stats[stage]['count'] += 1
            total_samples += 1
            
            # 计算未来N天的收益
            entry_price = row['close']
            
            for hold_days in HOLD_DAYS_LIST:
                future_idx = idx + hold_days
                if future_idx < len(df):
                    future_price = df.iloc[future_idx]['close']
                    ret = (future_price - entry_price) / entry_price * 100
                    stage_stats[stage]['rets'][hold_days].append(ret)
    
    # 输出结果
    print("\n" + "="*70)
    print("回测结果")
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
    
    # 保存统计结果（小文件）
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary_file = OUTPUT_DIR / "behavior_backtest_summary.txt"
    
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("主力行为判断逻辑历史回测结果\n")
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
