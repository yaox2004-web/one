#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信号排行 V2：加上位置信息
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HOLD_DAYS = 5
COST = 1.1
MA20_FILTER = True
LIMIT = 0


def load_klines(filepath):
    """读取K线数据，自动适配列数"""
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    klines = data.get('klines', [])
    if not klines:
        return None
    
    # 自动检测列数
    ncols = len(klines[0])
    
    if ncols == 6:
        cols = ['date', 'open', 'close', 'high', 'low', 'volume']
    elif ncols == 7:
        cols = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
    else:
        return None
    
    df = pd.DataFrame(klines, columns=cols[:ncols])
    for col in ['open', 'close', 'high', 'low', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
    return df


def calc_signals(df):
    df = df.copy()
    df['ma20'] = df['close'].rolling(20).mean()
    df['prev_close'] = df['close'].shift(1)
    df['prev_vol'] = df['volume'].shift(1)
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    vol_std = df['volume'].rolling(20).std()
    df['vol_z'] = np.where(vol_std > 0, (df['volume'] - df['vol_ma20']) / vol_std, 0)
    
    df['倍量柱'] = (df['volume'] >= df['prev_vol'] * 1.8) & (df['vol_z'] >= 1.5) & (df['close'] > df['open'])
    df['高量柱'] = (df['volume'] >= df['volume'].rolling(20).max().shift(1)) & (df['close'] > df['open'])
    
    df['黄金柱'] = False
    df['将军柱'] = False
    for i in range(5, len(df) - HOLD_DAYS):
        if df['倍量柱'].iloc[i]:
            up = all(df['close'].iloc[i+1+j] > df['close'].iloc[i+j] for j in range(3))
            down_vol = all(df['volume'].iloc[i+1+j] < df['volume'].iloc[i+j] for j in range(3))
            not_break = all(min(df['open'].iloc[i+j+1], df['close'].iloc[i+j+1]) >= min(df['open'].iloc[i], df['close'].iloc[i]) for j in range(3))
            if up and down_vol and not_break:
                df.iloc[i, df.columns.get_loc('黄金柱')] = True
            elif not_break:
                df.iloc[i, df.columns.get_loc('将军柱')] = True
    
    df['倍量过左峰'] = df['倍量柱'] & (df['close'] > df['high'].rolling(60).max().shift(1))
    df['价升量缩'] = (df['close'] > df['open']) & (df['close'] > df['prev_close']) & (df['volume'] < df['prev_vol'])
    df['缩量回踩'] = (df['volume'] < df['vol_ma20'] * 0.7) & (df['close'] < df['prev_close'])
    df['百日低量'] = df['volume'] <= df['volume'].rolling(100).min() * 1.05
    
    return df


def calc_position(df, idx):
    if idx < 20:
        return {}
    
    o = df['open'].iloc[:idx+1]
    h = df['high'].iloc[:idx+1]
    l = df['low'].iloc[:idx+1]
    c = df['close'].iloc[:idx+1]
    
    current_price = c.iloc[-1]
    lookback = min(120, len(h) - 1)
    
    recent_high = h.iloc[-lookback:-1].max()
    dist_to_high = (recent_high - current_price) / current_price * 100
    
    recent_low = l.iloc[-lookback:-1].min()
    dist_to_low = (current_price - recent_low) / current_price * 100
    
    range_ = recent_high - recent_low
    pos_pct = (current_price - recent_low) / range_ * 100 if range_ > 0 else 50
    
    recent_10_yin = c.iloc[-10:] < o.iloc[-10:]
    if recent_10_yin.any():
        nearest_yin_top = o.iloc[-10:][recent_10_yin].iloc[-1]
        dist_to_yin_top = (nearest_yin_top - current_price) / current_price * 100
    else:
        dist_to_yin_top = 999
    
    return {
        'dist_to_high': round(dist_to_high, 2),
        'dist_to_low': round(dist_to_low, 2),
        'pos_pct': round(pos_pct, 1),
        'dist_to_yin_top': round(dist_to_yin_top, 2),
    }


def classify_position(pos_pct):
    if pos_pct < 20:
        return '凹底'
    elif pos_pct < 35:
        return '低位'
    elif pos_pct < 65:
        return '中位'
    elif pos_pct < 85:
        return '高位'
    else:
        return '过峰'


def backtest_stock(df):
    samples = []
    df = calc_signals(df)
    
    signal_cols = ['倍量柱', '高量柱', '黄金柱', '将军柱', '倍量过左峰', '价升量缩', '缩量回踩', '百日低量']
    
    for i in range(20, len(df) - HOLD_DAYS):
        if MA20_FILTER and df['close'].iloc[i] < df['ma20'].iloc[i]:
            continue
        
        pos = calc_position(df, i)
        if not pos:
            continue
        
        entry_price = df['close'].iloc[i]
        exit_price = df['close'].iloc[i + HOLD_DAYS]
        ret = (exit_price - entry_price) / entry_price * 100 - COST
        
        for sig in signal_cols:
            if df[sig].iloc[i]:
                samples.append({
                    'signal': sig,
                    'ret': round(ret, 2),
                    'win': 1 if ret > 0 else 0,
                    'pos_pct': pos['pos_pct'],
                    'dist_to_high': pos['dist_to_high'],
                    'dist_to_low': pos['dist_to_low'],
                    'dist_to_yin_top': pos['dist_to_yin_top'],
                    'pos_zone': classify_position(pos['pos_pct']),
                })
    
    return samples


def main():
    all_samples = []
    stock_files = []
    
    for market_dir in DATA_DIR.iterdir():
        if market_dir.is_dir():
            for f in market_dir.glob('*.json'):
                stock_files.append(f)
    
    if LIMIT > 0:
        stock_files = stock_files[:LIMIT]
    
    print(f"共 {len(stock_files)} 只股票")
    
    for i, f in enumerate(stock_files):
        try:
            df = load_klines(f)
            if df is None or len(df) < 60:
                continue
            
            samples = backtest_stock(df)
            all_samples.extend(samples)
            
            if (i + 1) % 500 == 0:
                print(f"  进度 {i+1}/{len(stock_files)} | 累计样本 {len(all_samples)}")
                
        except Exception as e:
            continue
    
    if not all_samples:
        print("无样本")
        return
    
    df_all = pd.DataFrame(all_samples)
    
    print("\n=== 总体结果 ===")
    overall = df_all.groupby('signal').agg(
        count=('ret', 'count'),
        median=('ret', 'median'),
        mean=('ret', 'mean'),
        win_rate=('win', 'mean'),
    ).round(2)
    overall = overall.sort_values('median', ascending=False)
    print(overall)
    
    print("\n=== 黄金柱按位置分组 ===")
    golden = df_all[df_all['signal'] == '黄金柱']
    if len(golden) > 0:
        by_pos = golden.groupby('pos_zone').agg(
            count=('ret', 'count'),
            median=('ret', 'median'),
            mean=('ret', 'mean'),
            win_rate=('win', 'mean'),
        ).round(2)
        print(by_pos)
    
    print("\n=== 黄金柱按距上方高点分组 ===")
    if len(golden) > 0:
        golden['high_dist_bucket'] = pd.cut(
            golden['dist_to_high'],
            bins=[-999, 0, 2, 5, 10, 999],
            labels=['已突破', '0-2%', '2-5%', '5-10%', '>10%']
        )
        by_high = golden.groupby('high_dist_bucket', observed=True).agg(
            count=('ret', 'count'),
            median=('ret', 'median'),
            win_rate=('win', 'mean'),
        ).round(2)
        print(by_high)
    
    print("\n=== 黄金柱按距下方低点分组 ===")
    if len(golden) > 0:
        golden['low_dist_bucket'] = pd.cut(
            golden['dist_to_low'],
            bins=[0, 5, 10, 20, 999],
            labels=['0-5%', '5-10%', '10-20%', '>20%']
        )
        by_low = golden.groupby('low_dist_bucket', observed=True).agg(
            count=('ret', 'count'),
            median=('ret', 'median'),
            win_rate=('win', 'mean'),
        ).round(2)
        print(by_low)
    
    output_file = OUTPUT_DIR / "signal_ranking_with_pos.csv"
    df_all.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n已保存: {output_file}")


if __name__ == "__main__":
    main()
