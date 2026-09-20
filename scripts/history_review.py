#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史信号回顾（回测过去一年的战绩）
=================================================
设计思路（为什么做这个）：
  现在每天都没新信号，用户可能会觉得系统没用。
  所以我们回顾一下过去一年的历史数据：
  1. 过去一年出现了多少个黄金柱信号？
  2. 其中稳健型/激进型各多少个？
  3. 每个信号后来涨了多少？
  4. 总胜率多少？总收益多少？
  
  让用户看到系统的实际效果，建立信心。

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
# 配置
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

HOLD_DAYS = 5          # 持有5日
COST = 1.1              # 交易成本1.1%
MA20_FILTER = True     # MA20之上才做

# 位置过滤参数
STRONG_DIST_FROM_HIGH = 5.0
STRONG_MIN_POS = 35

# 回顾多久的数据？
LOOKBACK_DAYS = 250     # 过去一年（约250个交易日）


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
# 信号计算
# ============================================================
def check_golden(df, idx):
    """检查是不是黄金柱（T+3确认）"""
    if idx < 5 or idx + 3 >= len(df):
        return False
    
    prev_vol = df['volume'].iloc[idx - 1]
    if prev_vol <= 0:
        return False
    if df['volume'].iloc[idx] < prev_vol * 1.8:
        return False
    if df['close'].iloc[idx] <= df['open'].iloc[idx]:
        return False
    
    up = all(df['close'].iloc[idx+1+j] > df['close'].iloc[idx+j] for j in range(3))
    down_vol = all(df['volume'].iloc[idx+1+j] < df['volume'].iloc[idx+j] for j in range(3))
    base_low = min(df['open'].iloc[idx], df['close'].iloc[idx])
    not_break = all(
        min(df['open'].iloc[idx+j+1], df['close'].iloc[idx+j+1]) >= base_low 
        for j in range(3)
    )
    
    return up and down_vol and not_break


def calc_position(df, idx):
    """计算位置"""
    if idx < 20:
        return {}
    
    h = df['high'].iloc[:idx+1]
    l = df['low'].iloc[:idx+1]
    c = df['close'].iloc[:idx+1]
    
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
    """回测单只股票，找出过去一年的所有信号"""
    signals = []
    
    if len(df) < 60:
        return signals
    
    # MA20
    df['ma20'] = df['close'].rolling(20).mean()
    
    # 从第20天开始，到倒数第HOLD_DAYS天
    start_idx = max(20, len(df) - LOOKBACK_DAYS)
    end_idx = len(df) - HOLD_DAYS - 3  # 要留3天确认+5天持有
    
    for i in range(start_idx, end_idx):
        # 确认日
        confirm_idx = i + 3
        base_idx = i
        
        # MA20过滤
        if MA20_FILTER and df['close'].iloc[confirm_idx] < df['ma20'].iloc[confirm_idx]:
            continue
        
        # 检查是不是黄金柱
        if not check_golden(df, base_idx):
            continue
        
        # 计算位置（在确认日当天）
        # 注意：这里要传的是截止到confirm_idx的数据
        h = df['high'].iloc[:confirm_idx+1]
        l = df['low'].iloc[:confirm_idx+1]
        c = df['close'].iloc[:confirm_idx+1]
        
        current_price = c.iloc[-1]
        lookback = min(120, len(h) - 1)
        
        recent_high = h.iloc[-lookback:-1].max()
        recent_low = l.iloc[-lookback:-1].min()
        
        dist_to_high = (recent_high - current_price) / current_price * 100
        range_ = recent_high - recent_low
        pos_pct = (current_price - recent_low) / range_ * 100 if range_ > 0 else 50
        
        # 判断类型
        is_strong = (dist_to_high > STRONG_DIST_FROM_HIGH and pos_pct > STRONG_MIN_POS)
        is_aggro = (dist_to_high <= 0 and pos_pct > STRONG_MIN_POS)
        
        if not is_strong and not is_aggro:
            continue
        
        # 未来收益（确认日买入，持有5天）
        entry_price = df['close'].iloc[confirm_idx]
        exit_price = df['close'].iloc[confirm_idx + HOLD_DAYS]
        ret = (exit_price - entry_price) / entry_price * 100 - COST
        
        signal_type = 'strong' if is_strong else 'aggro'
        
        signals.append({
            'code': code,
            'name': name,
            'date': str(df.index[confirm_idx]),
            'signal_type': signal_type,
            'entry_price': round(entry_price, 2),
            'ret': round(ret, 2),
            'win': 1 if ret > 0 else 0,
            'pos_pct': round(pos_pct, 1),
            'dist_to_high': round(dist_to_high, 2),
        })
    
    return signals


# ============================================================
# 主函数
# ============================================================
def main():
    all_signals = []
    stock_files = []
    
    for market_dir in DATA_DIR.iterdir():
        if market_dir.is_dir():
            for f in market_dir.glob('*.json'):
                stock_files.append(f)
    
    print(f"共 {len(stock_files)} 只股票")
    print(f"回顾过去 {LOOKBACK_DAYS} 个交易日（约一年）\n")
    
    for i, f in enumerate(stock_files):
        try:
            df, name = load_klines(f)
            if df is None:
                continue
            
            signals = backtest_stock(f.stem, name, df)
            all_signals.extend(signals)
            
            if (i + 1) % 500 == 0:
                print(f"  进度 {i+1}/{len(stock_files)} | 累计信号 {len(all_signals)}")
                
        except Exception as e:
            continue
    
    if not all_signals:
        print("无信号")
        return
    
    # 统计
    df_all = pd.DataFrame(all_signals)
    
    print(f"\n{'='*50}")
    print(f"历史信号回顾结果")
    print(f"{'='*50}")
    
    print(f"\n总信号数：{len(df_all)} 个")
    print(f"总胜率：{df_all['win'].mean()*100:.1f}%")
    print(f"总中位数收益：{df_all['ret'].median():+.2f}%")
    print(f"总平均收益：{df_all['ret'].mean():+.2f}%")
    
    # 按类型分
    print(f"\n{'='*50}")
    print(f"【按信号类型】")
    print(f"{'='*50}")
    
    for stype in ['strong', 'aggro']:
        sub = df_all[df_all['signal_type'] == stype]
        if len(sub) == 0:
            continue
        name = '稳健型' if stype == 'strong' else '激进型'
        print(f"\n  {name}：{len(sub)} 个")
        print(f"    胜率：{sub['win'].mean()*100:.1f}%")
        print(f"    中位数：{sub['ret'].median():+.2f}%")
        print(f"    平均：{sub['ret'].mean():+.2f}%")
    
    # 最好的10个信号
    print(f"\n{'='*50}")
    print(f"【最好的10个信号】")
    print(f"{'='*50}")
    top10 = df_all.nlargest(10, 'ret')
    for _, s in top10.iterrows():
        stype = '稳健' if s['signal_type'] == 'strong' else '激进'
        print(f"  {s['code']} {s['name']} | {s['date'][:10]} | {stype} | {s['ret']:+.2f}%")
    
    # 最差的10个信号
    print(f"\n{'='*50}")
    print(f"【最差的10个信号】")
    print(f"{'='*50}")
    bottom10 = df_all.nsmallest(10, 'ret')
    for _, s in bottom10.iterrows():
        stype = '稳健' if s['signal_type'] == 'strong' else '激进'
        print(f"  {s['code']} {s['name']} | {s['date'][:10]} | {stype} | {s['ret']:+.2f}%")
    
    # 保存
    output_file = OUTPUT_DIR / "history_review.csv"
    df_all.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n已保存: {output_file}")


if __name__ == "__main__":
    main()

