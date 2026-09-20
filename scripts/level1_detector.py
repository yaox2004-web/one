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
BIG_YANG = 5.0      # 大阳线：涨幅>5%
MID_YANG = 2.0      # 中阳线：涨幅2%~5%
BIG_YIN = -5.0      # 大阴线：跌幅>5%
MID_YIN = -2.0      # 中阴线：跌幅2%~5%
SHADOW_RATIO = 2.0  # 长影线：影线>实体2倍
CROSS_TOLERANCE = 0.5  # 十字星：开盘收盘差<0.5%

# 量柱形态阈值
BEISHU_RATIO = 1.9     # 倍量柱：今量≥昨量×1.9
PING_RATIO = 0.05      # 平量柱：今量/昨量在0.95~1.05之间
HIGH_LOW_PERIODS = [10, 20, 60, 120]  # 高/低量柱多周期

# 量价组合阈值
VOL_UP_RATIO = 1.2     # 放量：今量>5日均量×1.2
VOL_DOWN_RATIO = 0.8   # 缩量：今量<5日均量×0.8

# 位置分位周期
POSITION_PERIOD = 120  # 位置分位：近120日高低点


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
# 第一步：计算当日指标（E+D类）
# ============================================================
def calc_daily_indicators(df):
    """计算所有当日指标"""
    
    # 基本指标
    df['pct_chg'] = (df['close'] - df['close'].shift(1)) / df['close'].shift(1) * 100  # 涨跌幅
    df['amplitude'] = (df['high'] - df['low']) / df['close'].shift(1) * 100  # 振幅
    
    # 今夕比（E类）
    df['vol_ratio_yesterday'] = df['volume'] / df['volume'].shift(1)  # 今量/昨量
    
    # 量比（相对5日均量）
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ratio_ma5'] = df['volume'] / df['vol_ma5']  # 今量/5日均量
    
    # 位置分位
    df['high_120'] = df['high'].rolling(POSITION_PERIOD).max()
    df['low_120'] = df['low'].rolling(POSITION_PERIOD).min()
    df['position_pct'] = (df['close'] - df['low_120']) / (df['high_120'] - df['low_120']) * 100
    
    # 均线位置
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    df['above_ma20'] = df['close'] > df['ma20']
    df['above_ma60'] = df['close'] > df['ma60']
    
    return df


# ============================================================
# 第二步：识别价柱形态（A类，26种）
# ============================================================
def detect_price_pattern(df):
    """识别所有价柱形态"""
    
    # 实体大小
    body = df['close'] - df['open']
    body_pct = body / df['open'] * 100  # 实体涨跌幅
    
    # 影线
    upper_shadow = df['high'] - df[['open', 'close']].max(axis=1)
    lower_shadow = df[['open', 'close']].min(axis=1) - df['low']
    body_size = abs(body)
    
    # 实体为0时的处理（十字星）
    body_size_safe = body_size.replace(0, 0.01)
    
    # --- 按实体大小分（8种）---
    df['big_yang'] = (body_pct > BIG_YANG) & (body > 0)  # 大阳线
    df['big_yin'] = (body_pct < -BIG_YANG) & (body < 0)  # 大阴线
    df['mid_yang'] = (body_pct >= MID_YANG) & (body_pct <= BIG_YANG) & (body > 0)  # 中阳线
    df['mid_yin'] = (body_pct <= -MID_YANG) & (body_pct >= -BIG_YANG) & (body < 0)  # 中阴线
    df['small_yang'] = (body > 0) & (body_pct < MID_YANG)  # 小阳线
    df['small_yin'] = (body < 0) & (body_pct > -MID_YANG)  # 小阴线
    
    # --- 按影线分（4种）---
    df['no_upper_shadow'] = upper_shadow / body_size_safe < 0.1  # 无上影线
    df['no_lower_shadow'] = lower_shadow / body_size_safe < 0.1  # 无下影线
    df['long_upper_shadow'] = upper_shadow / body_size_safe > SHADOW_RATIO  # 长上影
    df['long_lower_shadow'] = lower_shadow / body_size_safe > SHADOW_RATIO  # 长下影
    
    # --- 光头光脚（4种）---
    df['bare_top_yang'] = df['no_upper_shadow'] & (body > 0)  # 光头阳线
    df['bare_top_yin'] = df['no_upper_shadow'] & (body < 0)  # 光头阴线
    df['bare_bottom_yang'] = df['no_lower_shadow'] & (body > 0)  # 光脚阳线
    df['bare_bottom_yin'] = df['no_lower_shadow'] & (body < 0)  # 光脚阴线
    df['bare_all_yang'] = df['no_upper_shadow'] & df['no_lower_shadow'] & (body > 0)  # 光头光脚阳线
    df['bare_all_yin'] = df['no_upper_shadow'] & df['no_lower_shadow'] & (body < 0)  # 光头光脚阴线
    
    # --- 十字星家族（4种）---
    df['doji'] = abs(body_pct) < CROSS_TOLERANCE  # 十字星
    df['long_leg_doji'] = df['doji'] & df['long_upper_shadow'] & df['long_lower_shadow']  # 长腿十字
    df['dragonfly_doji'] = df['doji'] & df['long_lower_shadow'] & ~df['long_upper_shadow']  # 蜻蜓十字
    df['gravestone_doji'] = df['doji'] & df['long_upper_shadow'] & ~df['long_lower_shadow']  # 墓碑十字
    
    # --- 特殊形态（4种）---
    df['hammer'] = df['long_lower_shadow'] & (df['upper_shadow'] / body_size_safe < 0.5) & (body_size < df['high'] - df['low'])  # 锤头线
    df['inverted_hammer'] = df['long_upper_shadow'] & (df['lower_shadow'] / body_size_safe < 0.5) & (body_size < df['high'] - df['low'])  # 倒锤头
    
    # 假阳真阴/假阴真阳
    df['fake_yang_real_yin'] = (df['close'] > df['open']) & (df['close'] < df['close'].shift(1))  # 假阳真阴
    df['fake_yin_real_yang'] = (df['close'] < df['open']) & (df['close'] > df['close'].shift(1))  # 假阴真阳
    
    # 涨停/跌停（简化版：涨跌幅接近10%/20%）
    df['limit_up'] = df['pct_chg'] > 9.5
    df['limit_down'] = df['pct_chg'] < -9.5
    
    return df


# ============================================================
# 第三步：识别量柱形态（B类，6种）
# ============================================================
def detect_volume_pattern(df):
    """识别所有量柱形态"""
    
    # 倍量柱（基于今夕比）
    df['beishu'] = df['vol_ratio_yesterday'] >= BEISHU_RATIO
    
    # 平量柱（两根及以上持平）
    df['pingliang'] = (df['vol_ratio_yesterday'] >= 1 - PING_RATIO) & (df['vol_ratio_yesterday'] <= 1 + PING_RATIO)
    
    # 高量柱（多周期）
    for period in HIGH_LOW_PERIODS:
        df[f'high_vol_{period}'] = df['volume'] >= df['volume'].rolling(period).max() * 0.999
    
    # 低量柱（多周期）
    for period in HIGH_LOW_PERIODS:
        df[f'low_vol_{period}'] = df['volume'] <= df['volume'].rolling(period).min() * 1.001
    
    # 缩量柱（连续3天逐步缩小）
    df['suoliang_3d'] = (df['volume'] < df['volume'].shift(1)) & \
                        (df['volume'].shift(1) < df['volume'].shift(2)) & \
                        (df['volume'].shift(2) < df['volume'].shift(3))
    
    # 梯量柱（连续3天逐步升高）
    df['tiliang_3d'] = (df['volume'] > df['volume'].shift(1)) & \
                       (df['volume'].shift(1) > df['volume'].shift(2)) & \
                       (df['volume'].shift(2) > df['volume'].shift(3))
    
    return df


# ============================================================
# 第四步：识别量价组合（C类，8种）
# ============================================================
def detect_volume_price_combo(df):
    """识别所有量价组合"""
    
    price_up = df['close'] > df['close'].shift(1)
    price_down = df['close'] < df['close'].shift(1)
    price_flat = abs(df['pct_chg']) < 1.0
    
    vol_up = df['vol_ratio_ma5'] > VOL_UP_RATIO
    vol_down = df['vol_ratio_ma5'] < VOL_DOWN_RATIO
    vol_flat = (df['vol_ratio_ma5'] >= VOL_DOWN_RATIO) & (df['vol_ratio_ma5'] <= VOL_UP_RATIO)
    
    # 价升量增
    df['price_up_vol_up'] = price_up & vol_up
    
    # 价升量缩
    df['price_up_vol_down'] = price_up & vol_down
    
    # 价跌量增
    df['price_down_vol_up'] = price_down & vol_up
    
    # 价跌量缩
    df['price_down_vol_down'] = price_down & vol_down
    
    # 价平量增
    df['price_flat_vol_up'] = price_flat & vol_up
    
    # 价平量缩
    df['price_flat_vol_down'] = price_flat & vol_down
    
    # 放量滞涨（放巨量+不涨）
    df['vol_surge_no_up'] = (df['vol_ratio_ma5'] > 1.5) & (abs(df['pct_chg']) < 1.0)
    
    # 缩量不跌（缩量+不跌）
    df['vol_shrink_no_down'] = vol_down & (df['pct_chg'] > -1.0)
    
    return df


# ============================================================
# 第五步：输出某天的所有形态
# ============================================================
def print_daily_pattern(df, idx, date_str=None):
    """打印某天识别出的所有形态"""
    row = df.iloc[idx]
    
    if date_str is None:
        date_str = row['date']
    
    print(f"\n=== {date_str} ===")
    
    # 价柱形态
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
    
    # 量柱形态
    print(f"\n【量柱形态】")
    if row['beishu']: print(f"  - 倍量柱（今量/昨量={row['vol_ratio_yesterday']:.2f}）")
    if row['pingliang']: print(f"  - 平量柱（今量/昨量={row['vol_ratio_yesterday']:.2f}）")
    if row['high_vol_20']: print(f"  - 高量柱（近20日最高）")
    if row['low_vol_20']: print(f"  - 低量柱（近20日最低）")
    if row['suoliang_3d']: print(f"  - 缩量柱（连续3天缩小）")
    if row['tiliang_3d']: print(f"  - 梯量柱（连续3天升高）")
    
    # 量价组合
    print(f"\n【量价组合】")
    if row['price_up_vol_up']: print(f"  - 价升量增")
    if row['price_up_vol_down']: print(f"  - 价升量缩")
    if row['price_down_vol_up']: print(f"  - 价跌量增")
    if row['price_down_vol_down']: print(f"  - 价跌量缩")
    if row['vol_surge_no_up']: print(f"  - 放量滞涨")
    if row['vol_shrink_no_down']: print(f"  - 缩量不跌")
    
    # 当日指标
    print(f"\n【当日指标】")
    print(f"  - 涨跌幅: {row['pct_chg']:.2f}%")
    print(f"  - 振幅: {row['amplitude']:.2f}%")
    print(f"  - 量比(vs5日): {row['vol_ratio_ma5']:.2f}")
    print(f"  - 位置分位: {row['position_pct']:.1f}%")
    print(f"  - MA20: {'之上' if row['above_ma20'] else '之下'}")
    print(f"  - MA60: {'之上' if row['above_ma60'] else '之下'}")


# ============================================================
# 主函数
# ============================================================
def main():
    # 选一只股票测试
    test_file = DATA_DIR / "sh" / "sh600519.json"  # 贵州茅台
    if not test_file.exists():
        # 找第一只存在的
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
    
    # 计算指标
    df = calc_daily_indicators(df)
    df = detect_price_pattern(df)
    df = detect_volume_pattern(df)
    df = detect_volume_price_combo(df)
    
    # 打印最近5天的形态
    print(f"\n=== 最近5天的量价形态 ===")
    for i in range(max(0, len(df)-5), len(df)):
        print_daily_pattern(df, i)


if __name__ == "__main__":
    main()

