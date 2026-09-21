#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
八步客观描述报告 - 持仓股版
=================================================
设计思路（为什么这样写）：
  对着我们推导的八步，每一步都客观描述！
  第八步只描述距当下最近的左侧短中长期数据！
  加上量能位置分析！

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

# 你的持仓股（8只）
HOLDINGS = [
    ("sh", "600584"),  # 长电科技
    ("sz", "002156"),  # 通富微电
    ("sh", "603283"),  # 赛腾股份
    ("sz", "300394"),  # 天孚通信
    ("sh", "601138"),  # 工业富联
    ("sh", "601231"),  # 环旭电子
    ("sz", "300476"),  # 胜宏科技
    ("sh", "603516"),  # 淳中科技
]


# ============================================================
# 数据读取
# ============================================================
def load_klines(market, code):
    # 尝试不同的文件路径
    possible_paths = [
        DATA_DIR / market / f"{code}.json",
        DATA_DIR / market / f"{market}{code}.json",
        DATA_DIR / f"{market}{code}.json",
    ]
    
    for filepath in possible_paths:
        if filepath.exists():
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
            
            return df, data.get('name', code)
    
    return None, None


# ============================================================
# 生成报告
# ============================================================
def generate_report(market, code):
    df, name = load_klines(market, code)
    
    if df is None:
        return f"【{code}】文件未找到\n"
    
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    
    today_price = today['close']
    today_volume = today['volume']
    
    report = []
    report.append("=" * 60)
    report.append(f"【{name} {market}{code}】")
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
            report.append(f"  价格位置：近{period}日{position:.1f}%（最高{high:.2f}，最低{low:.2f}）")
            
            # 量能位置
            vol_high = df['volume'].iloc[-period:].max()
            vol_low = df['volume'].iloc[-period:].min()
            vol_position = (today_volume - vol_low) / (vol_high - vol_low) * 100
            report.append(f"  量能位置：近{period}日{vol_position:.1f}%（天量{vol_high:.0f}，地量{vol_low:.0f}）")
    
    # ========== 第六步：历史重要位置 ==========
    report.append("")
    report.append("【第六步：历史重要位置】")
    
    # 短期（20日）
    recent_20 = df.iloc[-20:]
    recent_high = recent_20['high'].max()
    recent_low = recent_20['low'].min()
    recent_high_date = recent_20.loc[recent_20['high'].idxmax(), 'date']
    recent_low_date = recent_20.loc[recent_20['low'].idxmin(), 'date']
    
    # 量能
    recent_vol_high = recent_20['volume'].max()
    recent_vol_low = recent_20['volume'].min()
    
    report.append(f"  短期(20日)：")
    report.append(f"    价格高点：{recent_high:.2f}（{recent_high_date}）")
    report.append(f"    价格低点：{recent_low:.2f}（{recent_low_date}）")
    report.append(f"    量能天量：{recent_vol_high:.0f}")
    report.append(f"    量能地量：{recent_vol_low:.0f}")
    
    # 中期（60日）
    if len(df) > 60:
        recent_60 = df.iloc[-60:]
        mid_high = recent_60['high'].max()
        mid_low = recent_60['low'].min()
        mid_high_date = recent_60.loc[recent_60['high'].idxmax(), 'date']
        mid_low_date = recent_60.loc[recent_60['low'].idxmin(), 'date']
        
        mid_vol_high = recent_60['volume'].max()
        mid_vol_low = recent_60['volume'].min()
        
        report.append(f"  中期(60日)：")
        report.append(f"    价格高点：{mid_high:.2f}（{mid_high_date}）")
        report.append(f"    价格低点：{mid_low:.2f}（{mid_low_date}）")
        report.append(f"    量能天量：{mid_vol_high:.0f}")
        report.append(f"    量能地量：{mid_vol_low:.0f}")
    
    # 长期（120日）
    if len(df) > 120:
        recent_120 = df.iloc[-120:]
        long_high = recent_120['high'].max()
        long_low = recent_120['low'].min()
        long_high_date = recent_120.loc[recent_120['high'].idxmax(), 'date']
        long_low_date = recent_120.loc[recent_120['low'].idxmin(), 'date']
        
        long_vol_high = recent_120['volume'].max()
        long_vol_low = recent_120['volume'].min()
        
        report.append(f"  长期(120日)：")
        report.append(f"    价格高点：{long_high:.2f}（{long_high_date}）")
        report.append(f"    价格低点：{long_low:.2f}（{long_low_date}）")
        report.append(f"    量能天量：{long_vol_high:.0f}")
        report.append(f"    量能地量：{long_vol_low:.0f}")
    
    # ========== 第七步：支撑位/压力位 ==========
    report.append("")
    report.append("【第七步：支撑位/压力位】")
    
    # 下方支撑位
    supports = []
    supports.append((recent_low, "20日低点"))
    
    if len(df) > 60:
        supports.append((mid_low, "60日低点"))
    
    if len(df) > 120:
        supports.append((long_low, "120日低点"))
    
    supports = [(price, label) for price, label in supports if price < today_price]
    supports.sort(key=lambda x: x[0], reverse=True)
    
    report.append("  下方支撑位：")
    if supports:
        for price, label in supports[:3]:
            dist = (today_price - price) / today_price * 100
            report.append(f"    {price:.2f}（{label}）距当前{dist:.2f}%")
    else:
        report.append("    无明显支撑位")
    
    # 上方压力位
    resistances = []
    resistances.append((recent_high, "20日高点"))
    
    if len(df) > 60:
        resistances.append((mid_high, "60日高点"))
    
    if len(df) > 120:
        resistances.append((long_high, "120日高点"))
    
    resistances = [(price, label) for price, label in resistances if price > today_price]
    resistances.sort(key=lambda x: x[0])
    
    report.append("  上方压力位：")
    if resistances:
        for price, label in resistances[:3]:
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
        vol_position_120 = (today_volume - long_vol_low) / (long_vol_high - long_vol_low) * 100
    elif len(df) > 60:
        position_120 = (today_price - mid_low) / (mid_high - mid_low) * 100
        vol_position_120 = (today_volume - mid_vol_low) / (mid_vol_high - mid_vol_low) * 100
    else:
        position_120 = (today_price - recent_low) / (recent_high - recent_low) * 100
        vol_position_120 = (today_volume - recent_vol_low) / (recent_vol_high - recent_vol_low) * 100
    
    report.append(f"  今日{name}{'上涨' if pct_chg > 0 else '下跌'}{abs(pct_chg):.2f}%，{'放量' if vol_ratio_yesterday > 1.5 else '缩量' if vol_ratio_yesterday < 0.7 else '平量'}。")
    report.append(f"  价格位置：近120日{position_120:.1f}%（{'高位' if position_120 > 70 else '低位' if position_120 < 30 else '中位'}）。")
    report.append(f"  量能位置：近120日{vol_position_120:.1f}%（{'天量' if vol_position_120 > 80 else '地量' if vol_position_120 < 20 else '正常'}）。")
    
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
    print("八步客观描述报告 - 持仓股版")
    print("=" * 60)
    
    for market, code in HOLDINGS:
        try:
            report = generate_report(market, code)
            print(report)
            print("\n\n")
        except Exception as e:
            print(f"Error: {market}{code} {e}")
            print("\n")


if __name__ == "__main__":
    main()
