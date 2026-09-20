#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修正版全市场回测（无未来函数）
=================================================
修正了什么？
  之前的回测有未来函数bug：在基柱日就买入了，
  但实际上黄金柱要等3天后才能确认。
  
  正确的逻辑：
  1. 基柱日 = i
  2. 后3天确认 = i+1, i+2, i+3
  3. 确认日 = i+3
  4. 买入日 = 确认日收盘后 = i+3
  5. 持有5天 = i+3 到 i+8
  6. 卖出日 = i+8

  这样就没有未来函数了。

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
# 配置
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HOLD_DAYS = 5          # 持有5日
COST = 1.1              # 交易成本1.1%
MA20_FILTER = True     # MA20之上才做


# ============================================================
# 数据读取
# ============================================================
def load_klines(filepath):
    """读取K线数据，自动适配6列/7列"""
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
# 黄金柱判断（无未来函数）
# ============================================================
def is_golden_at(df, base_idx):
    """
    判断base_idx那天的柱子，后3天是否确认黄金柱。
    注意：这个函数会用到base_idx+1, base_idx+2, base_idx+3的数据，
    所以确认日是base_idx+3，不是base_idx！
    
    为什么这样设计？
    量学理论：基柱后3天确认。所以信号出现在确认日，不是基柱日。
    """
    # 基柱日本身必须是倍量柱+收阳
    prev_vol = df['volume'].iloc[base_idx - 1]
    if prev_vol <= 0:
        return False
    if df['volume'].iloc[base_idx] < prev_vol * 1.8:
        return False
    if df['close'].iloc[base_idx] <= df['open'].iloc[base_idx]:
        return False
    
    # 后3日价升
    up = all(df['close'].iloc[base_idx+1+j] > df['close'].iloc[base_idx+j] for j in range(3))
    # 后3日量缩
    down_vol = all(df['volume'].iloc[base_idx+1+j] < df['volume'].iloc[base_idx+j] for j in range(3))
    # 三日不破基柱实底
    base_low = min(df['open'].iloc[base_idx], df['close'].iloc[base_idx])
    not_break = all(
        min(df['open'].iloc[base_idx+j+1], df['close'].iloc[base_idx+j+1]) >= base_low 
        for j in range(3)
    )
    
    return up and down_vol and not_break


# ============================================================
# 位置计算（在确认日当天）
# ============================================================
def calc_position_at(df, confirm_idx):
    """
    在确认日当天计算位置。
    只用截止到confirm_idx的数据，不用未来函数。
    """
    if confirm_idx < 20:
        return {}
    
    h = df['high'].iloc[:confirm_idx+1]
    l = df['low'].iloc[:confirm_idx+1]
    c = df['close'].iloc[:confirm_idx+1]
    
    current_price = c.iloc[-1]
    lookback = min(120, len(h) - 1)
    
    recent_high = h.iloc[-lookback:-1].max()
    recent_low = l.iloc[-lookback:-1].min()
    
    dist_to_high = (recent_high - current_price) / current_price * 100
    dist_to_low = (current_price - recent_low) / current_price * 100
    
    range_ = recent_high - recent_low
    pos_pct = (current_price - recent_low) / range_ * 100 if range_ > 0 else 50
    
    return {
        'price': current_price,
        'pos_pct': round(pos_pct, 1),
        'dist_to_high': round(dist_to_high, 2),
        'dist_to_low': round(dist_to_low, 2),
        'is_breakout': dist_to_high <= 0,
    }


# ============================================================
# 主回测逻辑
# ============================================================
def backtest_stock(code, name, df):
    """
    回测单只股票（无未来函数版）
    
    正确逻辑：
    1. 遍历基柱日 base_idx
    2. 检查后3天是否确认黄金柱
    3. 如果确认，确认日 confirm_idx = base_idx + 3
    4. 在确认日收盘后买入
    5. 持有5天卖出
    """
    samples = []
    
    if len(df) < 60:
        return samples
    
    # MA20
    df['ma20'] = df['close'].rolling(20).mean()
    
    # 遍历基柱日
    # 为什么从第5天开始？因为基柱日前一天要有prev_vol
    # 为什么到倒数第8天停止？因为要留3天确认+5天持有
    for base_idx in range(5, len(df) - HOLD_DAYS - 3):
        # 检查是不是黄金柱（后3天确认）
        if not is_golden_at(df, base_idx):
            continue
        
        # 确认日 = base_idx + 3
        confirm_idx = base_idx + 3
        
        # MA20过滤（在确认日判断）
        if MA20_FILTER and df['close'].iloc[confirm_idx] < df['ma20'].iloc[confirm_idx]:
            continue
        
        # 计算位置（在确认日当天）
        pos = calc_position_at(df, confirm_idx)
        if not pos:
            continue
        
        # 买入价格 = 确认日收盘价
        entry_price = df['close'].iloc[confirm_idx]
        # 卖出价格 = 确认日 + HOLD_DAYS 天收盘价
        exit_price = df['close'].iloc[confirm_idx + HOLD_DAYS]
        ret = (exit_price - entry_price) / entry_price * 100 - COST
        
        samples.append({
            'code': code,
            'name': name,
            'base_date': str(df.index[base_idx]),
            'confirm_date': str(df.index[confirm_idx]),
            'ret': round(ret, 2),
            'win': 1 if ret > 0 else 0,
            'pos_pct': pos['pos_pct'],
            'dist_to_high': pos['dist_to_high'],
            'dist_to_low': pos['dist_to_low'],
            'is_breakout': pos['is_breakout'],
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
    print(f"修正版回测（无未来函数）\n")
    
    for i, f in enumerate(stock_files):
        try:
            df, name = load_klines(f)
            if df is None:
                continue
            
            samples = backtest_stock(f.stem, name, df)
            all_samples.extend(samples)
            
            if (i + 1) % 500 == 0:
                print(f"  进度 {i+1}/{len(stock_files)} | 累计黄金柱 {len(all_samples)}")
                
        except Exception as e:
            continue
    
    if not all_samples:
        print("无样本")
        return
    
    df_all = pd.DataFrame(all_samples)
    
    print(f"\n{'='*50}")
    print(f"总黄金柱信号：{len(df_all)} 个")
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
    
    # 按是否突破高点分组
    print(f"\n{'='*50}")
    print(f"【按是否突破历史高点分组】")
    print(f"{'='*50}")
    
    print(f"\n  已突破高点（dist_to_high<=0）：")
    breakout = df_all[df_all['is_breakout']]
    print(f"    数量：{len(breakout)}")
    if len(breakout) > 0:
        print(f"    胜率：{breakout['win'].mean()*100:.1f}%")
        print(f"    中位数：{breakout['ret'].median():+.2f}%")
    
    print(f"\n  未突破高点（dist_to_high>0）：")
    not_breakout = df_all[~df_all['is_breakout']]
    print(f"    数量：{len(not_breakout)}")
    if len(not_breakout) > 0:
        print(f"    胜率：{not_breakout['win'].mean()*100:.1f}%")
        print(f"    中位数：{not_breakout['ret'].median():+.2f}%")
    
    # 按距高点距离分组
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
    output_file = OUTPUT_DIR / "corrected_backtest.csv"
    df_all.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n已保存: {output_file}")


if __name__ == "__main__":
    main()

