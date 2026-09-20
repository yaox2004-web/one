#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
第一层：当日量价形态识别引擎
=================================================
设计思路（为什么这样写）：
  第一层是整个系统的地基。所有第二层（王牌柱）、第三层（关键位）、
  第四层（买入信号）都建立在第一层之上。
  
  第一层的核心原则：
  1. 只看当天数据，不需要右确认
  2. 当天收盘后就能识别
  3. 包括价柱、量柱、量价组合、当日指标、今夕比
  4. 与昨日的对比关系
  5. 连续状态、均线位置、实体质量

硬约束：
  - 绝对不用未来函数
  - 所有参数按"适配量化时代"原则设定
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 配置（适配量化时代）
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"

# 价柱形态阈值
BIG_YANG = 5.0
MID_YANG = 2.0
BIG_YIN = -5.0
MID_YIN = -2.0
SHADOW_RATIO = 2.0
CROSS_TOLERANCE = 0.5

# 量柱形态阈值
BEISHU_RATIO = 1.9
PING_RATIO = 0.05
HIGH_LOW_PERIODS = [10, 20, 60, 120]

# 量价组合阈值
VOL_UP_RATIO = 1.2
VOL_DOWN_RATIO = 0.8

# 跳空阈值
GAP_THRESHOLD = 0.005

# 位置分位周期
POSITION_PERIOD = 120


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
# 第一步：计算当日指标
# ============================================================
def calc_daily_indicators(df):
    df['pct_chg'] = (df['close'] - df['close'].shift(1)) / df['close'].shift(1) * 100
    df['amplitude'] = (df['high'] - df['low']) / df['close'].shift(1) * 100
    df['vol_ratio_yesterday'] = df['volume'] / df['volume'].shift(1)
    
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ratio_ma5'] = df['volume'] / df['vol_ma5']
    
    df['high_120'] = df['high'].rolling(POSITION_PERIOD).max()
    df['low_120'] = df['low'].rolling(POSITION_PERIOD).min()
    df['position_pct'] = (df['close'] - df['low_120']) / (df['high_120'] - df['low_120']) * 100
    
    # 均线位置（MA5/MA10/MA20/MA60）
    df['ma5'] = df['close'].rolling(5).mean()
    df['ma10'] = df['close'].rolling(10).mean()
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['above_ma5'] = df['close'] > df['ma5']
    df['above_ma10'] = df['close'] > df['ma10']
    df['above_ma20'] = df['close'] > df['ma20']
    df['above_ma60'] = df['close'] > df['ma60']
    
    # 实体质量
    body = df['close'] - df['open']
    body_size = abs(body)
    total_range = df['high'] - df['low']
    df['body_ratio'] = body_size / total_range  # 实体占振幅比例
    
    # 阳量/阴量
    df['is_yang_vol'] = df['close'] > df['open']  # 阳量（收阳）
    df['is_yin_vol'] = df['close'] < df['open']   # 阴量（收阴）
    
    return df


# ============================================================
# 第二步：识别价柱形态
# ============================================================
def detect_price_pattern(df):
    body = df['close'] - df['open']
    body_pct = body / df['open'] * 100
    
    upper_shadow = df['high'] - df[['open', 'close']].max(axis=1)
    lower_shadow = df[['open', 'close']].min(axis=1) - df['low']
    body_size = abs(body)
    body_size_safe = body_size.replace(0, 0.01)
    
    df['big_yang'] = (body_pct > BIG_YANG) & (body > 0)
    df['big_yin'] = (body_pct < -BIG_YANG) & (body < 0)
    df['mid_yang'] = (body_pct >= MID_YANG) & (body_pct <= BIG_YANG) & (body > 0)
    df['mid_yin'] = (body_pct <= -MID_YANG) & (body_pct >= -BIG_YANG) & (body < 0)
    df['small_yang'] = (body > 0) & (body_pct < MID_YANG)
    df['small_yin'] = (body < 0) & (body_pct > -MID_YANG)
    
    df['no_upper_shadow'] = upper_shadow / body_size_safe < 0.1
    df['no_lower_shadow'] = lower_shadow / body_size_safe < 0.1
    df['long_upper_shadow'] = upper_shadow / body_size_safe > SHADOW_RATIO
    df['long_lower_shadow'] = lower_shadow / body_size_safe > SHADOW_RATIO
    
    df['doji'] = abs(body_pct) < CROSS_TOLERANCE
    df['long_leg_doji'] = df['doji'] & df['long_upper_shadow'] & df['long_lower_shadow']
    df['dragonfly_doji'] = df['doji'] & df['long_lower_shadow'] & ~df['long_upper_shadow']
    df['gravestone_doji'] = df['doji'] & df['long_upper_shadow'] & ~df['long_lower_shadow']
    
    df['hammer'] = df['long_lower_shadow'] & (upper_shadow / body_size_safe < 0.5) & (body_size < df['high'] - df['low'])
    df['inverted_hammer'] = df['long_upper_shadow'] & (lower_shadow / body_size_safe < 0.5) & (body_size < df['high'] - df['low'])
    
    df['fake_yang_real_yin'] = (df['close'] > df['open']) & (df['close'] < df['close'].shift(1))
    df['fake_yin_real_yang'] = (df['close'] < df['open']) & (df['close'] > df['close'].shift(1))
    
    df['limit_up'] = df['pct_chg'] > 9.5
    df['limit_down'] = df['pct_chg'] < -9.5
    
    return df


# ============================================================
# 第二步半：与昨日的对比
# ============================================================
def detect_yesterday_compare(df):
    prev_open = df['open'].shift(1)
    prev_close = df['close'].shift(1)
    prev_high = df['high'].shift(1)
    prev_low = df['low'].shift(1)
    prev_body_high = df[['open', 'close']].shift(1).max(axis=1)
    prev_body_low = df[['open', 'close']].shift(1).min(axis=1)
    
    df['yang_gai_yin'] = (df['close'] > df['open']) & (df['open'] <= prev_body_low) & (df['close'] >= prev_body_high) & (prev_close < prev_open)
    df['yin_gai_yang'] = (df['close'] < df['open']) & (df['open'] >= prev_body_high) & (df['close'] <= prev_body_low) & (prev_close > prev_open)
    
    df['gap_up'] = df['open'] > prev_high * (1 + GAP_THRESHOLD)
    df['gap_down'] = df['open'] < prev_low * (1 - GAP_THRESHOLD)
    
    df['high_open_high_close'] = (df['open'] > prev_close) & (df['close'] > df['open'])
    df['high_open_low_close'] = (df['open'] > prev_close) & (df['close'] < df['open'])
    df['low_open_high_close'] = (df['open'] < prev_close) & (df['close'] > df['open'])
    df['low_open_low_close'] = (df['open'] < prev_close) & (df['close'] < df['open'])
    
    return df


# ============================================================
# 第二步又半：连续状态（新增4种）
# ============================================================
def detect_consecutive_status(df):
    """识别连续状态"""
    
    # 连续阳线：连续3天收阳
    df['consec_yang_3d'] = (df['close'] > df['open']) & \
                           (df['close'].shift(1) > df['open'].shift(1)) & \
                           (df['close'].shift(2) > df['open'].shift(2))
    
    # 连续阴线：连续3天收阴
    df['consec_yin_3d'] = (df['close'] < df['open']) & \
                          (df['close'].shift(1) < df['open'].shift(1)) & \
                          (df['close'].shift(2) < df['open'].shift(2))
    
    # 连续放量：连续3天放量（vs5日均量）
    df['consec_vol_up_3d'] = (df['vol_ratio_ma5'] > VOL_UP_RATIO) & \
                             (df['vol_ratio_ma5'].shift(1) > VOL_UP_RATIO) & \
                             (df['vol_ratio_ma5'].shift(2) > VOL_UP_RATIO)
    
    # 连续缩量：连续3天缩量（vs5日均量）
    df['consec_vol_down_3d'] = (df['vol_ratio_ma5'] < VOL_DOWN_RATIO) & \
                               (df['vol_ratio_ma5'].shift(1) < VOL_DOWN_RATIO) & \
                               (df['vol_ratio_ma5'].shift(2) < VOL_DOWN_RATIO)
    
    return df


# ============================================================
# 第三步：识别量柱形态
# ============================================================
def detect_volume_pattern(df):
    df['beishu'] = df['vol_ratio_yesterday'] >= BEISHU_RATIO
    df['pingliang'] = (df['vol_ratio_yesterday'] >= 1 - PING_RATIO) & (df['vol_ratio_yesterday'] <= 1 + PING_RATIO)
    
    for period in HIGH_LOW_PERIODS:
        df[f'high_vol_{period}'] = df['volume'] >= df['volume'].rolling(period).max() * 0.999
        df[f'low_vol_{period}'] = df['volume'] <= df['volume'].rolling(period).min() * 1.001
    
    df['suoliang_3d'] = (df['volume'] < df['volume'].shift(1)) & \
                        (df['volume'].shift(1) < df['volume'].shift(2)) & \
                        (df['volume'].shift(2) < df['volume'].shift(3))
    
    df['tiliang_3d'] = (df['volume'] > df['volume'].shift(1)) & \
                       (df['volume'].shift(1) > df['volume'].shift(2)) & \
                       (df['volume'].shift(2) > df['volume'].shift(3))
    
    return df


# ============================================================
# 第四步：识别量价组合
# ============================================================
def detect_volume_price_combo(df):
    price_up = df['close'] > df['close'].shift(1)
    price_down = df['close'] < df['close'].shift(1)
    price_flat = abs(df['pct_chg']) < 1.0
    
    vol_up = df['vol_ratio_ma5'] > VOL_UP_RATIO
    vol_down = df['vol_ratio_ma5'] < VOL_DOWN_RATIO
    
    df['price_up_vol_up'] = price_up & vol_up
    df['price_up_vol_down'] = price_up & vol_down
    df['price_down_vol_up'] = price_down & vol_up
    df['price_down_vol_down'] = price_down & vol_down
    df['price_flat_vol_up'] = price_flat & vol_up
    df['price_flat_vol_down'] = price_flat & vol_down
    df['vol_surge_no_up'] = (df['vol_ratio_ma5'] > 1.5) & (abs(df['pct_chg']) < 1.0)
    df['vol_shrink_no_down'] = vol_down & (df['pct_chg'] > -1.0)
    
    return df


# ============================================================
# 第五步：输出
# ============================================================
def print_daily_pattern(df, idx, date_str=None):
    row = df.iloc[idx]
    
    if date_str is None:
        date_str = row['date']
    
    print(f"\n=== {date_str} ===")
    
    print(f"\n【价柱形态】")
    if row['big_yang']: print(f"  - 大阳线")
    if row['big_yin']: print(f"  - 大阴线")
    if row['mid_yang']: print(f"  - 中阳线")
    if row['mid_yin']: print(f"  - 中阴线")
    if row['small_yang']: print(f"  - 小阳线")
    if row['small_yin']: print(f"  - 小阴线")
    if row['long_upper_shadow']: print(f"  - 长上影线")
    if row['long_lower_shadow']: print(f"  - 长下影线")
    if row['doji']: print(f"  - 十字星")
    if row['hammer']: print(f"  - 锤头线")
    if row['inverted_hammer']: print(f"  - 倒锤头")
    if row['fake_yang_real_yin']: print(f"  - 假阳真阴")
    if row['fake_yin_real_yang']: print(f"  - 假阴真阳")
    if row['limit_up']: print(f"  - 涨停板")
    if row['limit_down']: print(f"  - 跌停板")
    
    print(f"\n【与昨日对比】")
    if row['yang_gai_yin']: print(f"  - 阳盖阴（多头反包）")
    if row['yin_gai_yang']: print(f"  - 阴盖阳（空头反包）")
    if row['gap_up']: print(f"  - 跳空高开")
    if row['gap_down']: print(f"  - 跳空低开")
    if row['high_open_high_close']: print(f"  - 高开高走")
    if row['high_open_low_close']: print(f"  - 高开低走")
    if row['low_open_high_close']: print(f"  - 低开高走")
    if row['low_open_low_close']: print(f"  - 低开低走")
    
    print(f"\n【连续状态】")
    if row['consec_yang_3d']: print(f"  - 连续3天阳线")
    if row['consec_yin_3d']: print(f"  - 连续3天阴线")
    if row['consec_vol_up_3d']: print(f"  - 连续3天放量")
    if row['consec_vol_down_3d']: print(f"  - 连续3天缩量")
    
    print(f"\n【量柱形态】")
    if row['beishu']: print(f"  - 倍量柱（今量/昨量={row['vol_ratio_yesterday']:.2f}）")
    if row['pingliang']: print(f"  - 平量柱（今量/昨量={row['vol_ratio_yesterday']:.2f}）")
    if row['high_vol_20']: print(f"  - 高量柱（近20日最高）")
    if row['low_vol_20']: print(f"  - 低量柱（近20日最低）")
    if row['suoliang_3d']: print(f"  - 缩量柱（连续3天缩小）")
    if row['tiliang_3d']: print(f"  - 梯量柱（连续3天升高）")
    
    print(f"\n【量价组合】")
    if row['price_up_vol_up']: print(f"  - 价升量增")
    if row['price_up_vol_down']: print(f"  - 价升量缩")
    if row['price_down_vol_up']: print(f"  - 价跌量增")
    if row['price_down_vol_down']: print(f"  - 价跌量缩")
    if row['vol_surge_no_up']: print(f"  - 放量滞涨")
    if row['vol_shrink_no_down']: print(f"  - 缩量不跌")
    
    print(f"\n【当日指标】")
    print(f"  - 涨跌幅: {row['pct_chg']:.2f}%")
    print(f"  - 振幅: {row['amplitude']:.2f}%")
    print(f"  - 实体占比: {row['body_ratio']*100:.1f}%")
    print(f"  - 量柱: {'阳量' if row['is_yang_vol'] else '阴量'}")
    print(f"  - 量比(vs5日): {row['vol_ratio_ma5']:.2f}")
    print(f"  - 位置分位: {row['position_pct']:.1f}%")
    print(f"  - MA5: {'之上' if row['above_ma5'] else '之下'}")
    print(f"  - MA10: {'之上' if row['above_ma10'] else '之下'}")
    print(f"  - MA20: {'之上' if row['above_ma20'] else '之下'}")
    print(f"  - MA60: {'之上' if row['above_ma60'] else '之下'}")


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
    
    df = calc_daily_indicators(df)
    df = detect_price_pattern(df)
    df = detect_yesterday_compare(df)
    df = detect_consecutive_status(df)  # 新增：连续状态
    df = detect_volume_pattern(df)
    df = detect_volume_price_combo(df)
    
    print(f"\n=== 最近5天的量价形态 ===")
    for i in range(max(0, len(df)-5), len(df)):
        print_daily_pattern(df, i)


if __name__ == "__main__":
    main()
