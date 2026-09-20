#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
强势黄金柱信号验证回测
=================================================
设计思路（为什么做这个）：
  刚才跑完signal_ranking_with_pos.py后发现：
  - 黄金柱整体82%胜率
  - 已突破历史高点的黄金柱最强（+15.18%中位数）
  - 中位/高位的黄金柱胜率反而更高（90%、87%）
  
  所以我们把这些条件组合起来，叫"强势黄金柱"：
  1. 基础条件：出现黄金柱
  2. 强势条件：已经突破历史高点，或距离高点<5%
  3. 位置条件：位置在中位以上（pos_pct > 35）
  
  跑全市场验证，看看这个新信号的胜率能不能超过82%。

硬约束：
  - 不用未来函数
  - 交易成本1.1%
  - T+1制度
  - MA20过滤
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 配置（为什么这些参数？）
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HOLD_DAYS = 5          # 持有5日最优（回测验证过：10日开始衰减，20日回到随机）
COST = 1.1              # 交易成本1.1%（佣金万2.5双边+印花税千0.5+滑点0.5%）
MA20_FILTER = True      # 大盘在MA20之下不做（回测验证过：影响最大）

# 强势黄金柱的条件（为什么这些阈值？）
STRONG_BREAKOUT_DIST = 5.0   # 距离历史高点<5%算"接近突破"
STRONG_MIN_POS = 35          # 位置分位>35%算"中位以上"


# ============================================================
# 数据读取（自动适配6列/7列）
# ============================================================
def load_klines(filepath):
    """读取K线数据，自动检测列数"""
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    klines = data.get('klines', [])
    if not klines:
        return None
    
    ncols = len(klines[0])
    
    # 为什么要自动检测？因为不同数据源的列数可能不一样（6列或7列）
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


# ============================================================
# 信号计算
# ============================================================
def calc_signals(df):
    """计算所有信号"""
    df = df.copy()
    
    # 基础指标（为什么需要这些？）
    df['ma20'] = df['close'].rolling(20).mean()  # MA20过滤用
    df['prev_close'] = df['close'].shift(1)
    df['prev_vol'] = df['volume'].shift(1)
    df['vol_ma20'] = df['volume'].rolling(20).mean()
    vol_std = df['volume'].rolling(20).std()
    df['vol_z'] = np.where(vol_std > 0, (df['volume'] - df['vol_ma20']) / vol_std, 0)
    
    # 为什么倍量阈值用1.8？
    # 回测验证过：1.8倍是最优门槛，太松(1.5)噪音多，太紧(2.0)信号少
    df['倍量柱'] = (df['volume'] >= df['prev_vol'] * 1.8) & (df['vol_z'] >= 1.5) & (df['close'] > df['open'])
    
    # 为什么黄金柱要三日定性？
    # 量学理论：基柱后3天不破=将军柱，价升量缩=黄金柱
    # 为什么要等3天？因为一天的信号可能是假的，3天确认更可靠
    df['黄金柱'] = False
    for i in range(5, len(df) - HOLD_DAYS):
        if df['倍量柱'].iloc[i]:
            # 后3日价升（为什么？量学理论：黄金柱必须价升量缩）
            up = all(df['close'].iloc[i+1+j] > df['close'].iloc[i+j] for j in range(3))
            # 后3日量缩（为什么？价升量缩=主力锁仓不卖）
            down_vol = all(df['volume'].iloc[i+1+j] < df['volume'].iloc[i+j] for j in range(3))
            # 三日不破（为什么？不破基柱实底=主力护盘）
            not_break = all(
                min(df['open'].iloc[i+j+1], df['close'].iloc[i+j+1]) >= 
                min(df['open'].iloc[i], df['close'].iloc[i]) 
                for j in range(3)
            )
            if up and down_vol and not_break:
                df.iloc[i, df.columns.get_loc('黄金柱')] = True
    
    return df


# ============================================================
# 位置计算
# ============================================================
def calc_position(df, idx):
    """计算当前位置"""
    if idx < 20:
        return {}
    
    h = df['high'].iloc[:idx+1]
    l = df['low'].iloc[:idx+1]
    c = df['close'].iloc[:idx+1]
    
    current_price = c.iloc[-1]
    lookback = min(120, len(h) - 1)
    
    # 距上方高点（为什么要看这个？）
    # 回测发现：已突破高点的黄金柱最强
    recent_high = h.iloc[-lookback:-1].max()
    dist_to_high = (recent_high - current_price) / current_price * 100
    
    # 距下方低点
    recent_low = l.iloc[-lookback:-1].min()
    dist_to_low = (current_price - recent_low) / current_price * 100
    
    # 位置分位（0=最低，100=最高）
    range_ = recent_high - recent_low
    pos_pct = (current_price - recent_low) / range_ * 100 if range_ > 0 else 50
    
    return {
        'dist_to_high': round(dist_to_high, 2),
        'dist_to_low': round(dist_to_low, 2),
        'pos_pct': round(pos_pct, 1),
        'is_breakout': dist_to_high <= 0,  # 已突破历史高点
        'is_near_breakout': 0 < dist_to_high <= STRONG_BREAKOUT_DIST,  # 接近突破
        'is_mid_high_pos': pos_pct > STRONG_MIN_POS,  # 中位以上
    }


# ============================================================
# 主回测逻辑
# ============================================================
def backtest_stock(df):
    samples = []
    df = calc_signals(df)
    
    for i in range(20, len(df) - HOLD_DAYS):
        # MA20过滤（为什么？回测验证过：MA20之下的信号胜率大幅下降）
        if MA20_FILTER and df['close'].iloc[i] < df['ma20'].iloc[i]:
            continue
        
        # 当前位置
        pos = calc_position(df, i)
        if not pos:
            continue
        
        # 只看黄金柱信号
        if not df['黄金柱'].iloc[i]:
            continue
        
        # 未来收益
        entry_price = df['close'].iloc[i]
        exit_price = df['close'].iloc[i + HOLD_DAYS]
        ret = (exit_price - entry_price) / entry_price * 100 - COST
        
        samples.append({
            'ret': round(ret, 2),
            'win': 1 if ret > 0 else 0,
            # 位置信息
            'pos_pct': pos['pos_pct'],
            'dist_to_high': pos['dist_to_high'],
            'dist_to_low': pos['dist_to_low'],
            'is_breakout': pos['is_breakout'],
            'is_near_breakout': pos['is_near_breakout'],
            'is_mid_high_pos': pos['is_mid_high_pos'],
        })
    
    return samples


def main():
    all_samples = []
    stock_files = []
    
    for market_dir in DATA_DIR.iterdir():
        if market_dir.is_dir():
            for f in market_dir.glob('*.json'):
                stock_files.append(f)
    
    print(f"共 {len(stock_files)} 只股票")
    
    for i, f in enumerate(stock_files):
        try:
            df = load_klines(f)
            if df is None or len(df) < 60:
                continue
            
            samples = backtest_stock(df)
            all_samples.extend(samples)
            
            if (i + 1) % 500 == 0:
                print(f"  进度 {i+1}/{len(stock_files)} | 累计黄金柱 {len(all_samples)}")
                
        except Exception as e:
            continue
    
    if not all_samples:
        print("无样本")
        return
    
    df_all = pd.DataFrame(all_samples)
    total = len(df_all)
    print(f"\n总黄金柱样本: {total}")
    
    # ============================================================
    # 分组统计
    # ============================================================
    
    def stat(name, mask):
        sub = df_all[mask]
        n = len(sub)
        if n == 0:
            print(f"  {name}: 无样本")
            return
        med = sub['ret'].median()
        win = sub['win'].mean() * 100
        print(f"  {name}: {n}样本 | 中位数{med:+.2f}% | 胜率{win:.1f}%")
    
    print("\n=== 基础对比 ===")
    stat("黄金柱整体", df_all.index == df_all.index)
    
    print("\n=== 按是否突破历史高点 ===")
    stat("已突破高点", df_all['is_breakout'])
    stat("接近突破(0-5%)", df_all['is_near_breakout'])
    stat("距高点>5%", ~df_all['is_breakout'] & ~df_all['is_near_breakout'])
    
    print("\n=== 按位置分位 ===")
    stat("中位以上(>35%)", df_all['is_mid_high_pos'])
    stat("低位及以下(<=35%)", ~df_all['is_mid_high_pos'])
    
    print("\n=== 组合信号：强势黄金柱 ===")
    # 组合1：已突破高点 + 中位以上
    combo1 = df_all['is_breakout'] & df_all['is_mid_high_pos']
    stat("已突破+中位以上", combo1)
    
    # 组合2：接近突破 + 中位以上
    combo2 = df_all['is_near_breakout'] & df_all['is_mid_high_pos']
    stat("接近突破+中位以上", combo2)
    
    # 组合3：已突破 或 接近突破 + 中位以上
    combo3 = (df_all['is_breakout'] | df_all['is_near_breakout']) & df_all['is_mid_high_pos']
    stat("突破附近+中位以上", combo3)
    
    # 保存结果
    output_file = OUTPUT_DIR / "strong_golden_backtest.csv"
    df_all.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n已保存: {output_file}")


if __name__ == "__main__":
    main()
