#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
八步客观描述报告
=================================================
设计思路（为什么这样写）：
  对着我们推导的八步，每一步都客观描述！
  第八步只描述距当下最近的左侧短中长期数据！

硬约束：
  - 绝对不用未来函数
  - 客观描述，不做主观判断
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


# ============================================================
# 数据读取
# ============================================================
def load_klines(filepath):
    with open(filepath, 'r') as f:
        data = json.load(f)
    
    klines = data.get('klines', [])
    ncols = len(klines[0])
    
    if ncols == 6:
        cols = ['date', 'open', 'close', 'high', 'low', 'volume']
    else:
        cols = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
    
    df = pd.DataFrame(klines)
    df = df.iloc[:, :ncols]
    df.columns = cols[:ncols]
    
    for col in ['open', 'close', 'high', 'low', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    
    df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
    
    return df, data.get('name', filepath.stem)


# ============================================================
# 找测试股票
# ============================================================
def find_test_stocks():
    # 找前几个文件测试
    all_files = []
    for market_dir in DATA_DIR.iterdir():
        if market_dir.is_dir():
            for f in market_dir.glob('*.json'):
                all_files.append(f)
                if len(all_files) >= 3:
                    return all_files
    
    return all_files


# ============================================================
# 生成报告
# ============================================================
def generate_report(filepath):
    df, name = load_klines(filepath)
    
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    
    today_price = today['close']
    today_volume = today['volume']
    
    report = []
    report.append("=" * 60)
    report.append(f"【{name}】")
    report.append(f"日期：{today['date']}")
    report.append("=" * 60)
    
    # ========== 第一步：今日数据 ==========
    report.append("")
    report.append("【第一步：今日数据】")
    report.append(f"  开盘价：{today['open']:.2f}")
    report.append(f"  收盘价：{today_price:.2f}")
    report.append(f"  最高价：{today['high']:.2f}")
    report.append(f"  最低价：{today['low']:.2f}")
    report.append(f"  成交量：{today_volume:.0f}")
    
    # ========== 第二步：今日情况 ==========
    report.append("")
    report.append("【第二步：今日情况】")
    
    pct_chg = (today['close'] - yesterday['close']) / yesterday['close'] * 100
    amplitude = (today['high'] - today['low']) / yesterday['close'] * 100
    body_size = abs(today['close'] - today['open'])
    body_ratio = body_size / (today['high'] - today['low']) * 100
    vol_ratio_yesterday = today_volume / yesterday['volume']
    
    report.append(f"  涨跌幅：{pct_chg:+.2f}%")
    report.append(f"  振幅：{amplitude:.2f}%")
    report.append(f"  实体占比：{body_ratio:.1f}%")
    report.append(f"  量比(vs昨日)：{vol_ratio_yesterday:.2f}")
    
    # ========== 第三步：今日多空力量 ==========
    report.append("")
    report.append("【第三步：今日多空力量】")
    
    if today['close'] > today['open']:
        report.append("  阳线：买方占优")
    else:
        report.append("  阴线：卖方占优")
    
    if vol_ratio_yesterday > 1.5:
        report.append("  放量：成交活跃")
    elif vol_ratio_yesterday < 0.7:
        report.append("  缩量：成交冷清")
    else:
        report.append("  平量：成交正常")
    
    report.append(f"  实体占比{body_ratio:.1f}%：{'实体明确' if body_ratio > 50 else '影线较多'}")
    
    # ========== 第四步：连续趋势 ==========
    report.append("")
    report.append("【第四步：连续趋势】")
    
    for days in [3, 5, 10]:
        if len(df) > days:
            pct = (today['close'] - df.iloc[-days-1]['close']) / df.iloc[-days-1]['close'] * 100
            report.append(f"  近{days}日涨跌幅：{pct:+.2f}%")
    
    # 连续放量/缩量
    if len(df) >= 3:
        v1 = df.iloc[-1]['volume']
        v2 = df.iloc[-2]['volume']
        v3 = df.iloc[-3]['volume']
        
        if v1 > v2 > v3:
            report.append("  连续放量：量能逐步放大")
        elif v1 < v2 < v3:
            report.append("  连续缩量：量能逐步缩小")
        else:
            report.append("  量能无连续趋势")
    
    # ========== 第五步：和历史对比 ==========
    report.append("")
    report.append("【第五步：和历史对比】")
    
    for period in [20, 60, 120]:
        if len(df) > period:
            high = df['high'].iloc[-period:].max()
            low = df['low'].iloc[-period:].min()
            position = (today_price - low) / (high - low) * 100
            report.append(f"  近{period}日位置：{position:.1f}%（最高{high:.2f}，最低{low:.2f}）")
    
    # ========== 第六步：历史重要位置 ==========
    report.append("")
    report.append("【第六步：历史重要位置】")
    
    # 短期（20日）
    recent_20 = df.iloc[-20:]
    recent_high = recent_20['high'].max()
    recent_low = recent_20['low'].min()
    recent_high_date = recent_20.loc[recent_20['high'].idxmax(), 'date']
    recent_low_date = recent_20.loc[recent_20['low'].idxmin(), 'date']
    
    report.append(f"  短期(20日)：")
    report.append(f"    高点：{recent_high:.2f}（{recent_high_date}）")
    report.append(f"    低点：{recent_low:.2f}（{recent_low_date}）")
    
    # 中期（60日）
    if len(df) > 60:
        recent_60 = df.iloc[-60:]
        mid_high = recent_60['high'].max()
        mid_low = recent_60['low'].min()
        mid_high_date = recent_60.loc[recent_60['high'].idxmax(), 'date']
        mid_low_date = recent_60.loc[recent_60['low'].idxmin(), 'date']
        
        report.append(f"  中期(60日)：")
        report.append(f"    高点：{mid_high:.2f}（{mid_high_date}）")
        report.append(f"    低点：{mid_low:.2f}（{mid_low_date}）")
    
    # 长期（120日）
    if len(df) > 120:
        recent_120 = df.iloc[-120:]
        long_high = recent_120['high'].max()
        long_low = recent_120['low'].min()
        long_high_date = recent_120.loc[recent_120['high'].idxmax(), 'date']
        long_low_date = recent_120.loc[recent_120['low'].idxmin(), 'date']
        
        report.append(f"  长期(120日)：")
        report.append(f"    高点：{long_high:.2f}（{long_high_date}）")
        report.append(f"    低点：{long_low:.2f}（{long_low_date}）")
    
    # ========== 第七步：支撑位/压力位 ==========
    report.append("")
    report.append("【第七步：支撑位/压力位】")
    
    # 下方支撑位（最近的）
    supports = []
    
    # 20日低点
    supports.append((recent_low, "20日低点"))
    
    if len(df) > 60:
        supports.append((mid_low, "60日低点"))
    
    if len(df) > 120:
        supports.append((long_low, "120日低点"))
    
    # 过滤出价格下方的支撑位
    supports = [(price, label) for price, label in supports if price < today_price]
    supports.sort(key=lambda x: x[0], reverse=True)
    
    report.append("  下方支撑位：")
    if supports:
        for price, label in supports[:3]:  # 只显示最近3个
            dist = (today_price - price) / today_price * 100
            report.append(f"    {price:.2f}（{label}）距当前{dist:.2f}%")
    else:
        report.append("    无明显支撑位")
    
    # 上方压力位（最近的）
    resistances = []
    
    # 20日高点
    resistances.append((recent_high, "20日高点"))
    
    if len(df) > 60:
        resistances.append((mid_high, "60日高点"))
    
    if len(df) > 120:
        resistances.append((long_high, "120日高点"))
    
    # 过滤出价格上方的压力位
    resistances = [(price, label) for price, label in resistances if price > today_price]
    resistances.sort(key=lambda x: x[0])
    
    report.append("  上方压力位：")
    if resistances:
        for price, label in resistances[:3]:  # 只显示最近3个
            dist = (price - today_price) / today_price * 100
            report.append(f"    {price:.2f}（{label}）距当前{dist:.2f}%")
    else:
        report.append("    无明显压力位")
    
    # ========== 第八步：客观总结 ==========
    report.append("")
    report.append("=" * 60)
    report.append("【第八步：客观总结】")
    report.append("=" * 60)
    
    # 计算近120日位置
    if len(df) > 120:
        position_120 = (today_price - long_low) / (long_high - long_low) * 100
    elif len(df) > 60:
        position_120 = (today_price - mid_low) / (mid_high - mid_low) * 100
    else:
        position_120 = (today_price - recent_low) / (recent_high - recent_low) * 100
    
    report.append(f"  今日{name}{'上涨' if pct_chg > 0 else '下跌'}{abs(pct_chg):.2f}%，{'放量' if vol_ratio_yesterday > 1.5 else '缩量' if vol_ratio_yesterday < 0.7 else '平量'}。")
    report.append(f"  当前价格在近120日{position_120:.1f}%位置。")
    
    if supports:
        report.append(f"  下方最近支撑：{supports[0][0]:.2f}（{supports[0][1]}）。")
    if resistances:
        report.append(f"  上方最近压力：{resistances[0][0]:.2f}（{resistances[0][1]}）。")
    
    return "\n".join(report)


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 60)
    print("八步客观描述报告")
    print("=" * 60)
    
    test_files = find_test_stocks()
    
    for filepath in test_files:
        try:
            report = generate_report(filepath)
            print(report)
            print("\n\n")
        except Exception as e:
            print(f"Error: {filepath} {e}")
            print("\n")


if __name__ == "__main__":
    main()
