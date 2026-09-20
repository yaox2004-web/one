#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日主力行为诊断（全市场版）
=================================================
设计思路（为什么这样写）：
  每个交易日收盘后自动跑，扫描全市场所有股票。
  输出各阶段的股票列表。

硬约束：
  - 绝对不用未来函数
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
    df['vol_ratio_yesterday'] = df['volume'] / df['volume'].shift(1)
    
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ratio_ma5'] = df['volume'] / df['vol_ma5']
    
    df['high_120'] = df['high'].rolling(120).max()
    df['low_120'] = df['low'].rolling(120).min()
    df['position_pct'] = (df['close'] - df['low_120']) / (df['high_120'] - df['low_120']) * 100
    
    df['ma20'] = df['close'].rolling(20).mean()
    df['above_ma20'] = df['close'] > df['ma20']
    
    df['pct_20d'] = (df['close'] - df['close'].shift(20)) / df['close'].shift(20) * 100
    
    return df


# ============================================================
# 第四层：主力行为意图判断
# ============================================================
def judge_main_behavior(df):
    latest = df.iloc[-1]
    
    position = latest['position_pct']
    vol_ratio = latest['vol_ratio_ma5']
    pct_chg = latest['pct_chg']
    pct_20d = latest['pct_20d']
    above_ma20 = latest['above_ma20']
    
    if pd.isna(position) or pd.isna(vol_ratio):
        return None  # 直接返回None
    
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
        if pct_20d > 10:
            if position > 50:
                scores['拉升'] += 25
            else:
                scores['建仓后期'] += 15
        elif pct_20d < -10:
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
    
    best_stage = max(scores, key=scores.get)
    best_score = scores[best_stage]
    
    total_score = sum(scores.values())
    confidence = best_score / total_score * 100 if total_score > 0 else 0
    
    return {
        'stage': best_stage,
        'confidence': confidence,
        'position': position,
        'vol_ratio': vol_ratio,
        'pct_20d': pct_20d,
    }


# ============================================================
# 主函数：全市场扫描
# ============================================================
def main():
    print("="*70)
    print("每日主力行为诊断（全市场版）")
    print("="*70)
    
    all_files = []
    for market_dir in DATA_DIR.iterdir():
        if market_dir.is_dir():
            for f in market_dir.glob('*.json'):
                all_files.append(f)
    
    print(f"共{len(all_files)}只股票")
    
    results = []
    total = len(all_files)
    
    for i, filepath in enumerate(all_files):
        if (i + 1) % 500 == 0:
            print(f"  进度 {i+1}/{total} | 已识别 {len(results)}")
        
        df, name = load_klines(filepath)
        if df is None or len(df) < MIN_DATA_DAYS:
            continue
        
        df = calc_daily_indicators(df)
        
        result = judge_main_behavior(df)
        if result is None:
            continue
        
        results.append({
            'code': filepath.stem,
            'name': name,
            'price': df['close'].iloc[-1],
            'position': result['position'],
            'vol_ratio': result['vol_ratio'],
            'pct_20d': result['pct_20d'],
            'stage': result['stage'],
            'confidence': result['confidence'],
            'date': df['date'].iloc[-1],
        })
    
    # 统计分布
    print(f"\n{'='*70}")
    print("今日主力阶段分布")
    print(f"{'='*70}")
    
    df_results = pd.DataFrame(results)
    stage_count = df_results['stage'].value_counts()
    
    for stage in ['建仓初期', '建仓后期', '洗盘', '拉升', '出货']:
        count = stage_count.get(stage, 0)
        pct = count / len(results) * 100 if len(results) > 0 else 0
        bar = '█' * int(pct / 2)
        print(f"  {stage}: {count:4d}只 ({pct:5.1f}%) {bar}")
    
    # 输出各阶段的股票列表
    for stage in ['建仓初期', '建仓后期', '洗盘', '拉升', '出货']:
        stage_df = df_results[df_results['stage'] == stage]
        if len(stage_df) == 0:
            continue
        
        print(f"\n{'='*70}")
        print(f"【{stage}】共{len(stage_df)}只")
        print(f"{'='*70}")
        
        stage_df = stage_df.sort_values('confidence', ascending=False)
        
        for _, row in stage_df.head(10).iterrows():
            print(f"  {row['code']} {row['name']:<12s} | {row['price']:>8.2f}元 | 位置{row['position']:>5.1f}% | 置信度{row['confidence']:>5.1f}%")
    
    # 保存结果
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime('%Y-%m-%d')
    output_file = OUTPUT_DIR / f"daily_main_behavior_{today}.csv"
    df_results.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n已保存: {output_file}")


if __name__ == "__main__":
    main()
