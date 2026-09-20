#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
按量学理论正确逻辑重写的回测
=================================================
设计思路（为什么这样设计）：
  之前的错误：把"识别信号"当成了"买入信号"
  正确逻辑：
  1. 识别层：识别黄金柱（主力建仓标志）
  2. 定位层：画出黄金线（基柱实底=主力成本线）
  3. 等待层：等价格回踩到黄金线附近
  4. 确认层：缩量不破+阳盖阴=买入信号
  
  一句话：黄金柱是用来识别主力的，回踩黄金线才是买入点。

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

# 回踩黄金线的参数（为什么这些阈值？）
PULLBACK_TOLERANCE = 0.02   # 回踩误差：黄金线±2%内算碰到了
PULLBACK_MAX_DAYS = 20       # 确认黄金柱后，20天内回踩都算有效
SHRINK_RATIO = 0.7           # 缩量：回踩时成交量 < 基柱量的70%
YANG_GAI_YIN = True          # 阳盖阴：确认买入点


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
# 第一步：识别黄金柱（无未来函数）
# ============================================================
def find_golden_columns(df):
    """
    找出所有黄金柱。
    返回：基柱日索引列表 + 黄金线价格列表
    
    黄金柱定义：
    1. 基柱日：倍量+收阳
    2. 后3日：价升量缩+不破基柱实底
    3. 确认日 = 基柱日 + 3
    4. 黄金线 = 基柱实底（min(open, close)）
    """
    golden_list = []
    
    for base_idx in range(5, len(df) - 3):
        # 基柱日必须是倍量柱+收阳
        prev_vol = df['volume'].iloc[base_idx - 1]
        if prev_vol <= 0:
            continue
        if df['volume'].iloc[base_idx] < prev_vol * 1.8:
            continue
        if df['close'].iloc[base_idx] <= df['open'].iloc[base_idx]:
            continue
        
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
        
        if up and down_vol and not_break:
            confirm_idx = base_idx + 3
            golden_price = base_low  # 黄金线 = 基柱实底
            golden_list.append({
                'base_idx': base_idx,
                'confirm_idx': confirm_idx,
                'golden_price': golden_price,
                'base_vol': df['volume'].iloc[base_idx],
            })
    
    return golden_list


# ============================================================
# 第二步：等待回踩黄金线
# ============================================================
def find_pullback_entry(df, golden_info):
    """
    在黄金柱确认后，等待回踩黄金线，找到买入点。
    
    正确逻辑：
    1. 确认日之后，等价格回踩到黄金线附近
    2. 回踩时缩量（成交量 < 基柱量的70%）
    3. 出现阳盖阴（今天收阳且收盘价盖过昨天实体）
    4. 这才是买入点！
    """
    confirm_idx = golden_info['confirm_idx']
    golden_price = golden_info['golden_price']
    base_vol = golden_info['base_vol']
    
    # 从确认日之后开始找，最多等PULLBACK_MAX_DAYS天
    search_start = confirm_idx + 1
    search_end = min(confirm_idx + PULLBACK_MAX_DAYS, len(df) - HOLD_DAYS)
    
    if search_start >= search_end:
        return None
    
    # 在这段时间内找回踩点
    for i in range(search_start, search_end):
        current_price = df['close'].iloc[i]
        
        # 回踩黄金线：价格在黄金线±2%内
        if abs(current_price - golden_price) / golden_price > PULLBACK_TOLERANCE:
            continue
        
        # 缩量：当前成交量 < 基柱量的70%
        if df['volume'].iloc[i] >= base_vol * SHRINK_RATIO:
            continue
        
        # 阳盖阴：今天收阳且收盘价盖过昨天实体顶部
        if not (df['close'].iloc[i] > df['open'].iloc[i]):
            continue
        
        yesterday_top = max(df['open'].iloc[i-1], df['close'].iloc[i-1])
        if df['close'].iloc[i] < yesterday_top:
            continue
        
        # 满足所有条件！这就是买入点
        return i  # 返回买入日索引
    
    return None  # 没有找到回踩买入点


# ============================================================
# 主回测逻辑
# ============================================================
def backtest_stock(code, name, df):
    """
    回测单只股票（按量学理论正确逻辑）
    """
    samples = []
    
    if len(df) < 60:
        return samples
    
    # MA20
    df['ma20'] = df['close'].rolling(20).mean()
    
    # 第一步：找出所有黄金柱
    golden_list = find_golden_columns(df)
    
    for golden in golden_list:
        confirm_idx = golden['confirm_idx']
        
        # MA20过滤（在确认日判断）
        if MA20_FILTER and df['close'].iloc[confirm_idx] < df['ma20'].iloc[confirm_idx]:
            continue
        
        # 第二步：找回踩买入点
        entry_idx = find_pullback_entry(df, golden)
        if entry_idx is None:
            continue
        
        # 买入日之后，持有5天卖出
        entry_price = df['close'].iloc[entry_idx]
        exit_price = df['close'].iloc[entry_idx + HOLD_DAYS]
        ret = (exit_price - entry_price) / entry_price * 100 - COST
        
        # 计算位置（在买入日当天）
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
            'base_date': str(df.index[golden['base_idx']]),
            'confirm_date': str(df.index[confirm_idx]),
            'entry_date': str(df.index[entry_idx]),
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
    print(f"按量学理论正确逻辑回测（回踩黄金线买入）\n")
    
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
    output_file = OUTPUT_DIR / "correct_logic_backtest.csv"
    df_all.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n已保存: {output_file}")


if __name__ == "__main__":
    main()

