#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第二层：左侧历史建构识别
=================================================
设计思路（为什么这样写）：
  第一层是"今天怎么样"，第二层是"过去有什么"。
  
  量学理论强调"立体看盘"，不能只看今天，还要看左侧历史建构。
  左侧的重要量柱、价柱、量线，都会对现在的价格产生支撑或压力。
  
  本层的核心任务：
  1. 找出历史所有重要量柱（倍量/高量/低量...）
  2. 找出历史所有重要价柱（峰顶/谷底/大阳/大阴...）
  3. 找出历史所有重要量线（黄金线/安全线/风险线...）

硬约束：
  - 绝对不用未来函数
  - 只看过去，不看未来
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 配置
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"

# 历史建构的时间周期
HISTORY_PERIODS = [20, 60, 120, 250]  # 近20日/60日/120日/250日

# 量柱阈值
BEISHU_RATIO = 1.9     # 倍量柱
BIG_BAR_PCT = 5.0      # 大阳线/大阴线：涨跌幅>5%

# 重要量柱的最小样本量
MIN_SAMPLE = 5  # 至少要有5个样本才显示


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
# 第一步：识别历史重要量柱
# ============================================================
def find_history_vol_columns(df):
    """找出历史所有重要量柱"""
    
    vol_columns = []
    
    for i in range(1, len(df)):
        today_vol = df['volume'].iloc[i]
        prev_vol = df['volume'].iloc[i - 1]
        
        if prev_vol <= 0:
            continue
        
        vol_ratio = today_vol / prev_vol
        date = df['date'].iloc[i]
        
        # 1. 倍量柱
        if vol_ratio >= BEISHU_RATIO:
            vol_columns.append({
                'type': '倍量柱',
                'date': date,
                'price': df['close'].iloc[i],
                'volume': today_vol,
                'days_ago': len(df) - 1 - i,  # 距今天多少天
            })
        
        # 2. 高量柱（多周期）
        for period in HISTORY_PERIODS:
            if i >= period:
                recent_max = df['volume'].iloc[i-period:i].max()
                if today_vol >= recent_max * 0.999:
                    vol_columns.append({
                        'type': f'{period}日高量柱',
                        'date': date,
                        'price': df['close'].iloc[i],
                        'volume': today_vol,
                        'days_ago': len(df) - 1 - i,
                    })
        
        # 3. 低量柱（多周期）
        for period in HISTORY_PERIODS:
            if i >= period:
                recent_min = df['volume'].iloc[i-period:i].min()
                if today_vol <= recent_min * 1.001:
                    vol_columns.append({
                        'type': f'{period}日低量柱',
                        'date': date,
                        'price': df['close'].iloc[i],
                        'volume': today_vol,
                        'days_ago': len(df) - 1 - i,
                    })
    
    return vol_columns


# ============================================================
# 第二步：识别历史重要价柱
# ============================================================
def find_history_price_columns(df):
    """找出历史所有重要价柱"""
    
    price_columns = []
    
    for i in range(len(df)):
        date = df['date'].iloc[i]
        days_ago = len(df) - 1 - i
        
        # 1. 大阳线
        pct_chg = (df['close'].iloc[i] - df['close'].iloc[i-1]) / df['close'].iloc[i-1] * 100 if i > 0 else 0
        if pct_chg > BIG_BAR_PCT:
            price_columns.append({
                'type': '大阳线',
                'date': date,
                'price': df['close'].iloc[i],
                'high': df['high'].iloc[i],
                'low': df['low'].iloc[i],
                'days_ago': days_ago,
            })
        
        # 2. 大阴线
        if pct_chg < -BIG_BAR_PCT:
            price_columns.append({
                'type': '大阴线',
                'date': date,
                'price': df['close'].iloc[i],
                'high': df['high'].iloc[i],
                'low': df['low'].iloc[i],
                'days_ago': days_ago,
            })
        
        # 3. 阶段最高点（峰顶线）
        for period in HISTORY_PERIODS:
            if i >= period and i < len(df) - 1:
                recent_high = df['high'].iloc[i-period:i].max()
                if df['high'].iloc[i] >= recent_high:
                    price_columns.append({
                        'type': f'{period}日峰顶',
                        'date': date,
                        'price': df['high'].iloc[i],
                        'high': df['high'].iloc[i],
                        'low': df['low'].iloc[i],
                        'days_ago': days_ago,
                    })
        
        # 4. 阶段最低点（谷底线）
        for period in HISTORY_PERIODS:
            if i >= period and i < len(df) - 1:
                recent_low = df['low'].iloc[i-period:i].min()
                if df['low'].iloc[i] <= recent_low:
                    price_columns.append({
                        'type': f'{period}日谷底',
                        'date': date,
                        'price': df['low'].iloc[i],
                        'high': df['high'].iloc[i],
                        'low': df['low'].iloc[i],
                        'days_ago': days_ago,
                    })
    
    return price_columns


# ============================================================
# 第三步：识别历史重要量线
# ============================================================
def find_history_lines(df):
    """找出历史所有重要量线"""
    
    lines = []
    
    # 1. 高量柱的安全线（实顶）和风险线（最低价）
    for i in range(1, len(df)):
        today_vol = df['volume'].iloc[i]
        prev_vol = df['volume'].iloc[i - 1]
        
        if prev_vol <= 0:
            continue
        
        # 找高量柱
        for period in [20, 60]:
            if i >= period:
                recent_max = df['volume'].iloc[i-period:i].max()
                if today_vol >= recent_max * 0.999:
                    date = df['date'].iloc[i]
                    days_ago = len(df) - 1 - i
                    
                    # 安全线 = 高量柱实顶
                    body_top = max(df['open'].iloc[i], df['close'].iloc[i])
                    lines.append({
                        'type': '高量安全线',
                        'date': date,
                        'price': body_top,
                        'days_ago': days_ago,
                    })
                    
                    # 风险线 = 高量柱最低价
                    lines.append({
                        'type': '高量风险线',
                        'date': date,
                        'price': df['low'].iloc[i],
                        'days_ago': days_ago,
                    })
    
    return lines


# ============================================================
# 主函数
# ============================================================
def main():
    test_file = DATA_DIR / "sh" / "sh600519.json"
    if not test_file.exists():
        for market_dir in DATA_DIR.iterdir():
            if market_dir.is_dir():
                for f in market_dir.glob('*.json'):
                    test_file = f
                    break
                break
    
    df, name = load_klines(test_file)
    if df is None:
        print("没找到数据")
        return
    
    print(f"股票：{name}")
    print(f"数据量：{len(df)}天")
    print(f"当前价格：{df['close'].iloc[-1]:.2f}")
    
    # 找历史量柱
    vol_columns = find_history_vol_columns(df)
    print(f"\n{'='*50}")
    print(f"【历史重要量柱】共{len(vol_columns)}个")
    print(f"{'='*50}")
    
    # 按类型分组统计
    vol_df = pd.DataFrame(vol_columns)
    if len(vol_df) > 0:
        type_count = vol_df['type'].value_counts()
        print("\n按类型统计：")
        for t, c in type_count.items():
            print(f"  {t}: {c}个")
        
        # 显示最近的10个
        print(f"\n最近的10个：")
        recent_vol = vol_df.sort_values('days_ago').head(10)
        for _, row in recent_vol.iterrows():
            print(f"  {row['date']} | {row['type']} | 价格{row['price']:.2f} | {row['days_ago']}天前")
    
    # 找历史价柱
    price_columns = find_history_price_columns(df)
    print(f"\n{'='*50}")
    print(f"【历史重要价柱】共{len(price_columns)}个")
    print(f"{'='*50}")
    
    price_df = pd.DataFrame(price_columns)
    if len(price_df) > 0:
        type_count = price_df['type'].value_counts()
        print("\n按类型统计：")
        for t, c in type_count.items():
            print(f"  {t}: {c}个")
        
        # 显示最近的10个
        print(f"\n最近的10个：")
        recent_price = price_df.sort_values('days_ago').head(10)
        for _, row in recent_price.iterrows():
            print(f"  {row['date']} | {row['type']} | 价格{row['price']:.2f} | {row['days_ago']}天前")
    
    # 找历史量线
    lines = find_history_lines(df)
    print(f"\n{'='*50}")
    print(f"【历史重要量线】共{len(lines)}个")
    print(f"{'='*50}")
    
    lines_df = pd.DataFrame(lines)
    if len(lines_df) > 0:
        type_count = lines_df['type'].value_counts()
        print("\n按类型统计：")
        for t, c in type_count.items():
            print(f"  {t}: {c}个")
        
        # 显示最近的10个
        print(f"\n最近的10个：")
        recent_lines = lines_df.sort_values('days_ago').head(10)
        for _, row in recent_lines.iterrows():
            print(f"  {row['date']} | {row['type']} | 价格{row['price']:.2f} | {row['days_ago']}天前")


if __name__ == "__main__":
    main()

