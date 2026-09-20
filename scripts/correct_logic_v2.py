#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
正确逻辑回测V2（适配量化时代）
=================================================
设计思路（为什么这样设计）：
  V1的参数太严格，买入点太少（只有35个）。
  V2按"适配当下市场环境"最高原则优化：
  
  1. 缩量用20日均量（市场正常水平），不和基柱比
  2. 回踩范围放宽到±5%
  3. 确认条件只要收阳就行，不必须阳盖阴
  
  这样能找到更多买入点，统计更有意义。

硬约束：
  - 绝对不用未来函数
  - 交易成本1.1%
  - T+1制度
  - MA20过滤
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 配置（全部按适配当下市场原则调整）
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HOLD_DAYS = 5
COST = 1.1
MA20_FILTER = True

# 优化后的参数（适配量化时代）
PULLBACK_TOLERANCE = 0.05   # 回踩范围：黄金线±5%（原来2%太严格）
PULLBACK_MAX_DAYS = 20       # 确认后20天内回踩都算有效
SHRINK_VOL_RATIO = 0.6       # 缩量：成交量 < 20日均量的60%（原来和基柱比太严格）
VOL_MA_PERIOD = 20           # 用20日均量做基准


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
        return None, None
    
    df = pd.DataFrame(klines, columns=cols[:ncols])
    for col in ['open', 'close', 'high', 'low', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
    
    name = data.get('name', filepath.stem)
    return df, name


# ============================================================
# 第一步：识别黄金柱
# ============================================================
def find_golden_columns(df):
    """找出所有黄金柱"""
    golden_list = []
    
    for base_idx in range(5, len(df) - 3):
        prev_vol = df['volume'].iloc[base_idx - 1]
        if prev_vol <= 0:
            continue
        if df['volume'].iloc[base_idx] < prev_vol * 1.8:
            continue
        if df['close'].iloc[base_idx] <= df['open'].iloc[base_idx]:
            continue
        
        up = all(df['close'].iloc[base_idx+1+j] > df['close'].iloc[base_idx+j] for j in range(3))
        down_vol = all(df['volume'].iloc[base_idx+1+j] < df['volume'].iloc[base_idx+j] for j in range(3))
        base_low = min(df['open'].iloc[base_idx], df['close'].iloc[base_idx])
        not_break = all(
            min(df['open'].iloc[base_idx+j+1], df['close'].iloc[base_idx+j+1]) >= base_low 
            for j in range(3)
        )
        
        if up and down_vol and not_break:
            confirm_idx = base_idx + 3
            golden_price = base_low
            golden_list.append({
                'base_idx': base_idx,
                'confirm_idx': confirm_idx,
                'golden_price': golden_price,
            })
    
    return golden_list


# ============================================================
# 第二步：等待回踩黄金线（优化版）
# ============================================================
def find_pullback_entry(df, golden_info):
    """
    在黄金柱确认后，等待回踩黄金线，找到买入点。
    
    优化后的条件（适配量化时代）：
    1. 价格回踩到黄金线±5%内
    2. 成交量 < 20日均量的60%（缩量）
    3. 当天收阳
    """
    confirm_idx = golden_info['confirm_idx']
    golden_price = golden_info['golden_price']
    
    search_start = confirm_idx + 1
    search_end = min(confirm_idx + PULLBACK_MAX_DAYS, len(df) - HOLD_DAYS)
    
    if search_start >= search_end:
        return None
    
    for i in range(search_start, search_end):
        current_price = df['close'].iloc[i]
        
        # 条件1：回踩黄金线±5%内
        if abs(current_price - golden_price) / golden_price > PULLBACK_TOLERANCE:
            continue
        
        # 条件2：缩量（成交量 < 20日均量的60%）
        vol_ma20 = df['volume'].iloc[i-VOL_MA_PERIOD:i].mean() if i >= VOL_MA_PERIOD else df['volume'].iloc[:i].mean()
        if vol_ma20 <= 0:
            continue
        if df['volume'].iloc[i] >= vol_ma20 * SHRINK_VOL_RATIO:
            continue
        
        # 条件3：当天收阳
        if not (df['close'].iloc[i] > df['open'].iloc[i]):
            continue
        
        # 满足所有条件！这就是买入点
        return i
    
    return None


# ============================================================
# 主回测逻辑
# ============================================================
def backtest_stock(code, name, df):
    samples = []
    
    if len(df) < 60:
        return samples
    
    df['ma20'] = df['close'].rolling(20).mean()
    
    golden_list = find_golden_columns(df)
    
    for golden in golden_list:
        confirm_idx = golden['confirm_idx']
        
        if MA20_FILTER and df['close'].iloc[confirm_idx] < df['ma20'].iloc[confirm_idx]:
            continue
        
        entry_idx = find_pullback_entry(df, golden)
        if entry_idx is None:
            continue
        
        entry_price = df['close'].iloc[entry_idx]
        exit_price = df['close'].iloc[entry_idx + HOLD_DAYS]
        ret = (exit_price - entry_price) / entry_price * 100 - COST
        
        # 计算位置
        h = df['high'].iloc[:entry_idx+1]
        l = df['low'].iloc[:entry_idx+1]
        c = df['close'].iloc[:entry_idx+1]
        
        current_price = c.iloc[-1]
        lookback = min(120, len(h) - 1)
        
        recent_high = h.iloc[-lookback:-1].max()
        recent_low = l.iloc[-lookback:-1].min()
        
        dist_to_high = (recent_high - current_price) / current_price * 100
        range_ = recent_high - recent_low
        pos_pct = (current_price - recent_low) / range_ * 100 if range_ > 0 else 50
        
        samples.append({
            'code': code,
            'name': name,
            'entry_price': round(entry_price, 2),
            'ret': round(ret, 2),
            'win': 1 if ret > 0 else 0,
            'pos_pct': round(pos_pct, 1),
            'dist_to_high': round(dist_to_high, 2),
        })
    
    return samples


# ============================================================
# 主函数
# ============================================================
def main():
    all_samples = []
    stock_files = []
    
    for market_dir in DATA_DIR.iterdir():
        if market_dir.is_dir():
            for f in market_dir.glob('*.json'):
                stock_files.append(f)
    
    print(f"共 {len(stock_files)} 只股票")
    print(f"正确逻辑V2（适配量化时代参数）\n")
    
    for i, f in enumerate(stock_files):
        try:
            df, name = load_klines(f)
            if df is None:
                continue
            
            samples = backtest_stock(f.stem, name, df)
            all_samples.extend(samples)
            
            if (i + 1) % 500 == 0:
                print(f"  进度 {i+1}/{len(stock_files)} | 累计买入点 {len(all_samples)}")
                
        except Exception as e:
            continue
    
    if not all_samples:
        print("无样本")
        return
    
    df_all = pd.DataFrame(all_samples)
    
    print(f"\n{'='*50}")
    print(f"总买入点：{len(df_all)} 个")
    print(f"总胜率：{df_all['win'].mean()*100:.1f}%")
    print(f"总中位数：{df_all['ret'].median():+.2f}%")
    print(f"总平均：{df_all['ret'].mean():+.2f}%")
    
    # 按位置分组
    print(f"\n{'='*50}")
    print(f"【按位置分位分组】")
    print(f"{'='*50}")
    
    bins = [0, 20, 35, 65, 85, 101]
    labels = ['凹底(<20%)', '低位(20-35%)', '中位(35-65%)', '高位(65-85%)', '过峰(>85%)']
    df_all['pos_zone'] = pd.cut(df_all['pos_pct'], bins=bins, labels=labels)
    
    by_pos = df_all.groupby('pos_zone', observed=True).agg(
        count=('ret', 'count'),
        median=('ret', 'median'),
        win_rate=('win', 'mean'),
    ).round(2)
    by_pos['win_rate'] = by_pos['win_rate'] * 100
    print(by_pos)
    
    # 按距高点分组
    print(f"\n{'='*50}")
    print(f"【按距上方高点距离分组】")
    print(f"{'='*50}")
    
    bins2 = [-999, 0, 5, 10, 20, 999]
    labels2 = ['已突破', '0-5%', '5-10%', '10-20%', '>20%']
    df_all['high_dist'] = pd.cut(df_all['dist_to_high'], bins=bins2, labels=labels2)
    
    by_high = df_all.groupby('high_dist', observed=True).agg(
        count=('ret', 'count'),
        median=('ret', 'median'),
        win_rate=('win', 'mean'),
    ).round(2)
    by_high['win_rate'] = by_high['win_rate'] * 100
    print(by_high)
    
    # 保存
    output_file = OUTPUT_DIR / "correct_logic_v2.csv"
    df_all.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n已保存: {output_file}")


if __name__ == "__main__":
    main()

