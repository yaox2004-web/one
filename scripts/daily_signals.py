#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日信号扫描系统
=================================================
设计思路（为什么做这个）：
  经过全市场5220只回测验证，我们找到了两个有效的信号策略：
  
  【稳健型】高胜率策略
    条件：黄金柱 + 距上方高点>5% + 中位以上 + MA20上
    回测：85.6%胜率，+3.33%中位数
    特点：胜率高、回撤小、适合新手
    
  【激进型】高收益策略  
    条件：黄金柱 + 已突破历史高点 + 中位以上 + MA20上
    回测：73.3%胜率，+15.18%中位数
    特点：收益高、波动大、适合有经验后小仓位博

  每天收盘后自动扫描全市场，输出：
  1. 稳健型信号列表（重点关注）
  2. 激进型信号列表（小仓位博）

硬约束：
  - 不用未来函数（所有信号只用当天及之前的数据）
  - 交易成本1.1%（已在回测中扣除）
  - T+1制度（当天买第二天才能卖）
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
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 为什么这些阈值？（全部来自回测验证）
HOLD_DAYS = 5              # 持有5日最优（10日开始衰减，20日回到随机）
COST = 1.1                  # 交易成本1.1%
MA20_FILTER = True          # MA20之上才做

# 稳健型参数
STRONG_DIST_FROM_HIGH = 5.0   # 距高点>5%（回测：85.6%胜率）
STRONG_MIN_POS = 35           # 位置分位>35%（回测：83.7%胜率）

# 激进型参数
AGGRO_BREAKOUT = True         # 已突破历史高点（回测：+15.18%中位数）


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
    """
    检查第idx天是不是黄金柱
    为什么要三日定性？
    量学理论：基柱后3天不破=将军柱，价升量缩=黄金柱
    为什么要等3天？因为一天的信号可能是假的，3天确认更可靠
    """
    if idx < 5 or idx + 3 >= len(df):
        return False
    
    # 当天必须是倍量柱
    prev_vol = df['volume'].iloc[idx - 1]
    if prev_vol <= 0:
        return False
    if df['volume'].iloc[idx] < prev_vol * 1.8:
        return False
    if df['close'].iloc[idx] <= df['open'].iloc[idx]:  # 必须收阳
        return False
    
    # 后3日价升
    up = all(df['close'].iloc[idx+1+j] > df['close'].iloc[idx+j] for j in range(3))
    # 后3日量缩
    down_vol = all(df['volume'].iloc[idx+1+j] < df['volume'].iloc[idx+j] for j in range(3))
    # 三日不破基柱实底
    base_low = min(df['open'].iloc[idx], df['close'].iloc[idx])
    not_break = all(
        min(df['open'].iloc[idx+j+1], df['close'].iloc[idx+j+1]) >= base_low 
        for j in range(3)
    )
    
    return up and down_vol and not_break


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
    
    recent_high = h.iloc[-lookback:-1].max()
    recent_low = l.iloc[-lookback:-1].min()
    
    dist_to_high = (recent_high - current_price) / current_price * 100
    dist_to_low = (current_price - recent_low) / current_price * 100
    
    range_ = recent_high - recent_low
    pos_pct = (current_price - recent_low) / range_ * 100 if range_ > 0 else 50
    
    return {
        'price': current_price,
        'dist_to_high': round(dist_to_high, 2),
        'dist_to_low': round(dist_to_low, 2),
        'pos_pct': round(pos_pct, 1),
        'is_breakout': dist_to_high <= 0,  # 已突破历史高点
    }


# ============================================================
# 扫描单只股票
# ============================================================
def scan_stock(code, name, df):
    """扫描一只股票，返回今天有没有信号"""
    result = {
        'code': code,
        'name': name,
        'signal_type': None,  # strong=稳健型, aggro=激进型
        'price': None,
        'pos_pct': None,
        'dist_to_high': None,
    }
    
    if len(df) < 60:
        return None
    
    # MA20过滤
    ma20 = df['close'].rolling(20).mean().iloc[-1]
    if MA20_FILTER and df['close'].iloc[-1] < ma20:
        return None
    
    # 检查今天是不是黄金柱（注意：黄金柱是T+3确认的）
    # 所以我们检查的是"3天前"的那根柱子
    # 为什么？因为黄金柱要等3天确认，确认日=今天
    confirm_idx = len(df) - 1  # 确认日=今天
    base_idx = confirm_idx - 3  # 基柱日=3天前
    
    if not check_golden(df, base_idx):
        return None
    
    # 计算当前位置
    pos = calc_position(df, confirm_idx)
    if not pos:
        return None
    
    result['price'] = pos['price']
    result['pos_pct'] = pos['pos_pct']
    result['dist_to_high'] = pos['dist_to_high']
    
    # 判断是稳健型还是激进型
    # 稳健型：距高点>5% + 中位以上
    is_strong = (pos['dist_to_high'] > STRONG_DIST_FROM_HIGH and 
                 pos['pos_pct'] > STRONG_MIN_POS)
    
    # 激进型：已突破高点 + 中位以上
    is_aggro = (pos['is_breakout'] and 
                pos['pos_pct'] > STRONG_MIN_POS)
    
    if is_strong:
        result['signal_type'] = 'strong'  # 稳健型
    elif is_aggro:
        result['signal_type'] = 'aggro'    # 激进型
    else:
        return None
    
    return result


# ============================================================
# 主函数
# ============================================================
def main():
    strong_signals = []  # 稳健型
    aggro_signals = []   # 激进型
    
    stock_files = []
    for market_dir in DATA_DIR.iterdir():
        if market_dir.is_dir():
            for f in market_dir.glob('*.json'):
                stock_files.append(f)
    
    print(f"共 {len(stock_files)} 只股票")
    
    for i, f in enumerate(stock_files):
        try:
            df, name = load_klines(f)
            if df is None:
                continue
            
            result = scan_stock(f.stem, name, df)
            if result is None:
                continue
            
            if result['signal_type'] == 'strong':
                strong_signals.append(result)
            elif result['signal_type'] == 'aggro':
                aggro_signals.append(result)
            
            if (i + 1) % 1000 == 0:
                print(f"  进度 {i+1}/{len(stock_files)}")
                
        except Exception as e:
            continue
    
    # 输出结果
    today = datetime.now().strftime('%Y-%m-%d')
    
    print(f"\n{'='*50}")
    print(f"每日信号扫描结果 - {today}")
    print(f"{'='*50}")
    
    print(f"\n【稳健型信号】高胜率(85.6%)，重点关注")
    print(f"{'-'*50}")
    if strong_signals:
        # 按位置分位排序（越高越强势）
        strong_signals.sort(key=lambda x: -x['pos_pct'])
        for s in strong_signals:
            print(f"  {s['code']} {s['name']}")
            print(f"    价格: {s['price']:.2f} | 位置: {s['pos_pct']:.1f}% | 距高点: {s['dist_to_high']:.1f}%")
    else:
        print("  无")
    
    print(f"\n【激进型信号】高收益(+15%)，小仓位博")
    print(f"{'-'*50}")
    if aggro_signals:
        aggro_signals.sort(key=lambda x: -x['pos_pct'])
        for s in aggro_signals:
            print(f"  {s['code']} {s['name']}")
            print(f"    价格: {s['price']:.2f} | 位置: {s['pos_pct']:.1f}% | 已突破高点")
    else:
        print("  无")
    
    # 统计
    print(f"\n{'='*50}")
    print(f"统计: 稳健型 {len(strong_signals)} 只 | 激进型 {len(aggro_signals)} 只")
    print(f"{'='*50}")
    
    # 保存结果
    all_signals = strong_signals + aggro_signals
    if all_signals:
        df_out = pd.DataFrame(all_signals)
        output_file = OUTPUT_DIR / f"daily_signals_{today}.csv"
        df_out.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"已保存: {output_file}")


if __name__ == "__main__":
    main()

