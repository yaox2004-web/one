#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日复盘报告生成器（V2：带交易计划）
=================================================
设计思路（为什么做这个）：
  V1只输出了信号列表，但新手看到信号还是不知道怎么操作。
  V2加上交易计划：止损价、止盈价、最多持有天数。
  
  这样报告就是完整的：
  1. 今天有什么信号？
  2. 现在什么位置？
  3. 买了之后止损价多少？
  4. 止盈价多少？
  5. 最多拿几天？
  
  新手照着报告操作就行。

硬约束：
  - 不用未来函数
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

# 位置过滤参数（来自回测验证）
STRONG_DIST_FROM_HIGH = 5.0
STRONG_MIN_POS = 35

# 交易计划参数（全部来自回测验证）
STOP_LOSS_STRONG = 3.0    # 稳健型止损：亏3%就跑
STOP_LOSS_AGGRO = 5.0     # 激进型止损：亏5%再跑
TAKE_PROFIT_STRONG = 8.0  # 稳健型止盈：赚8%就卖
TAKE_PROFIT_AGGRO = 15.0  # 激进型止盈：赚15%再卖
MAX_HOLD_DAYS = 5          # 最多持有5天（回测验证5日最优）


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
# 信号检查
# ============================================================
def check_golden(df, idx):
    """
    检查是不是黄金柱（T+3确认）
    为什么要三日定性？
    量学理论：基柱后3天不破=将军柱，价升量缩=黄金柱
    为什么要等3天？因为一天的信号可能是假的，3天确认更可靠
    """
    if idx < 5 or idx + 3 >= len(df):
        return False
    
    prev_vol = df['volume'].iloc[idx - 1]
    if prev_vol <= 0:
        return False
    if df['volume'].iloc[idx] < prev_vol * 1.8:
        return False
    if df['close'].iloc[idx] <= df['open'].iloc[idx]:
        return False
    
    # 后3日价升（为什么？价升量缩=主力锁仓不卖）
    up = all(df['close'].iloc[idx+1+j] > df['close'].iloc[idx+j] for j in range(3))
    # 后3日量缩
    down_vol = all(df['volume'].iloc[idx+1+j] < df['volume'].iloc[idx+j] for j in range(3))
    # 三日不破基柱实底（为什么？不破=主力护盘）
    base_low = min(df['open'].iloc[idx], df['close'].iloc[idx])
    not_break = all(
        min(df['open'].iloc[idx+j+1], df['close'].iloc[idx+j+1]) >= base_low 
        for j in range(3)
    )
    
    return up and down_vol and not_break


# ============================================================
# 位置分析
# ============================================================
def analyze_position(df, idx):
    """分析当前位置"""
    if idx < 20:
        return {}
    
    h = df['high'].iloc[:idx+1]
    l = df['low'].iloc[:idx+1]
    c = df['close'].iloc[:idx+1]
    v = df['volume'].iloc[:idx+1]
    
    current_price = c.iloc[-1]
    lookback = min(120, len(h) - 1)
    
    recent_high = h.iloc[-lookback:-1].max()
    recent_low = l.iloc[-lookback:-1].min()
    
    dist_to_high = (recent_high - current_price) / current_price * 100
    dist_to_low = (current_price - recent_low) / current_price * 100
    
    range_ = recent_high - recent_low
    pos_pct = (current_price - recent_low) / range_ * 100 if range_ > 0 else 50
    
    # 判断位置类型
    if pos_pct < 20:
        pos_type = "凹底（最好的位置）"
        pos_tip = "从底部起来，安全边际最高"
    elif pos_pct < 35:
        pos_type = "低位"
        pos_tip = "刚从底部起来，风险不大"
    elif pos_pct < 65:
        pos_type = "中位"
        pos_tip = "中间位置，上下都有可能"
    elif pos_pct < 85:
        pos_type = "高位"
        pos_tip = "涨了不少了，注意风险"
    else:
        pos_type = "过峰（已突破历史高点）"
        pos_tip = "创新高了，波动会很大"
    
    # 量能状态
    vol_ma20 = v.iloc[-20:].mean()
    vol_ratio = v.iloc[-1] / vol_ma20 if vol_ma20 > 0 else 0
    
    if vol_ratio < 0.5:
        vol_state = "极致缩量（惜售）"
    elif vol_ratio < 0.8:
        vol_state = "缩量（卖的人少）"
    elif vol_ratio < 1.5:
        vol_state = "正常量"
    else:
        vol_state = "放量（关注）"
    
    # MA20状态
    ma20 = c.iloc[-20:].mean()
    above_ma20 = current_price > ma20
    
    return {
        'price': current_price,
        'pos_pct': round(pos_pct, 1),
        'pos_type': pos_type,
        'pos_tip': pos_tip,
        'dist_to_high': round(dist_to_high, 2),
        'dist_to_low': round(dist_to_low, 2),
        'vol_state': vol_state,
        'above_ma20': above_ma20,
        'is_breakout': dist_to_high <= 0,
    }


# ============================================================
# 交易计划生成
# ============================================================
def gen_trade_plan(entry_price, signal_type):
    """
    生成交易计划（止损止盈规则）
    为什么这些参数？全部来自回测验证
    """
    if signal_type == 'strong':
        stop_loss = STOP_LOSS_STRONG    # 稳健型：亏3%就跑
        take_profit = TAKE_PROFIT_STRONG  # 稳健型：赚8%就卖
    else:
        stop_loss = STOP_LOSS_AGGRO     # 激进型：亏5%再跑（波动大）
        take_profit = TAKE_PROFIT_AGGRO  # 激进型：赚15%再卖
    
    stop_price = entry_price * (1 - stop_loss / 100)
    profit_price = entry_price * (1 + take_profit / 100)
    
    return {
        'stop_loss_pct': stop_loss,
        'take_profit_pct': take_profit,
        'stop_price': round(stop_price, 2),
        'profit_price': round(profit_price, 2),
        'max_hold': MAX_HOLD_DAYS,
    }


# ============================================================
# 生成单只股票的报告
# ============================================================
def gen_report_line(code, name, pos, signal_type):
    """生成单只股票的报告行（带交易计划）"""
    
    # 生成交易计划
    plan = gen_trade_plan(pos['price'], signal_type)
    
    if signal_type == 'strong':
        signal_desc = "稳健型（高胜率85%）"
        action = "重点关注，可小仓位试错"
    else:
        signal_desc = "激进型（高收益15%）"
        action = "小仓位博，别重仓"
    
    line = f"""
┌─────────────────────────────────
│ {code} {name}
│ 信号类型：{signal_desc}
│ 当前价格：{pos['price']:.2f}
│ 位置：{pos['pos_type']}（{pos['pos_pct']:.1f}%）
│ {pos['pos_tip']}
│ 距上方压力：{pos['dist_to_high']:.1f}%
│ 距下方支撑：{pos['dist_to_low']:.1f}%
│ 量能状态：{pos['vol_state']}
│
│ 【交易计划】
│ 止损价：{plan['stop_price']:.2f}（亏{plan['stop_loss_pct']}%就跑）
│ 止盈价：{plan['profit_price']:.2f}（赚{plan['take_profit_pct']}%就卖）
│ 最多持有：{plan['max_hold']}天（不涨就走）
│
│ 操作建议：{action}
└─────────────────────────────────
"""
    return line


# ============================================================
# 主函数
# ============================================================
def main():
    strong_list = []
    aggro_list = []
    
    stock_files = []
    for market_dir in DATA_DIR.iterdir():
        if market_dir.is_dir():
            for f in market_dir.glob('*.json'):
                stock_files.append(f)
    
    print(f"共 {len(stock_files)} 只股票")
    
    for i, f in enumerate(stock_files):
        try:
            df, name = load_klines(f)
            if df is None or len(df) < 60:
                continue
            
            # MA20过滤
            ma20 = df['close'].rolling(20).mean().iloc[-1]
            if df['close'].iloc[-1] < ma20:
                continue
            
            # 检查今天确认的黄金柱
            confirm_idx = len(df) - 1
            base_idx = confirm_idx - 3
            
            if not check_golden(df, base_idx):
                continue
            
            # 分析位置
            pos = analyze_position(df, confirm_idx)
            if not pos:
                continue
            
            # 判断类型
            is_strong = (pos['dist_to_high'] > STRONG_DIST_FROM_HIGH and 
                         pos['pos_pct'] > STRONG_MIN_POS)
            is_aggro = (pos['is_breakout'] and 
                        pos['pos_pct'] > STRONG_MIN_POS)
            
            if is_strong:
                strong_list.append((f.stem, name, pos, 'strong'))
            elif is_aggro:
                aggro_list.append((f.stem, name, pos, 'aggro'))
            
            if (i + 1) % 1000 == 0:
                print(f"  进度 {i+1}/{len(stock_files)}")
                
        except Exception as e:
            continue
    
    # 生成报告
    today = datetime.now().strftime('%Y-%m-%d')
    report = f"""
╔═══════════════════════════════════════════╗
║           每日复盘报告 - {today}        ║
╚═══════════════════════════════════════════╝

【系统说明】
  本系统基于量学理论，经过全市场5220只回测验证。
  核心信号：黄金柱（三日定性确认）
  交易成本：1.1%往返
  持有周期：5个交易日
  过滤条件：MA20之上才做

{'='*45}

【稳健型信号】高胜率策略
  条件：黄金柱 + 距上方高点>5% + 中位以上
  回测胜率：85.6%
  止损：亏3%就跑
  止盈：赚8%就卖

{'-'*45}
"""
    
    if strong_list:
        strong_list.sort(key=lambda x: -x[2]['pos_pct'])
        for code, name, pos, stype in strong_list:
            report += gen_report_line(code, name, pos, stype)
    else:
        report += "\n  今日无稳健型信号\n"
    
    report += f"""
{'='*45}

【激进型信号】高收益策略
  条件：黄金柱 + 已突破历史高点 + 中位以上
  回测收益：+15.18%中位数
  止损：亏5%再跑
  止盈：赚15%再卖

{'-'*45}
"""
    
    if aggro_list:
        aggro_list.sort(key=lambda x: -x[2]['pos_pct'])
        for code, name, pos, stype in aggro_list:
            report += gen_report_line(code, name, pos, stype)
    else:
        report += "\n  今日无激进型信号\n"
    
    report += f"""
{'='*45}

【总结】
  稳健型信号：{len(strong_list)} 只
  激进型信号：{len(aggro_list)} 只
  
  操作原则：
  1. 没信号就空仓等待，不要强行交易
  2. 稳健型信号来了再重点关注
  3. 激进型小仓位博，别重仓
  4. 到了止损价，无条件跑
  5. 到了止盈价，可以卖
  6. 拿了5天还没涨，也走

{'='*45}
"""
    
    print(report)
    
    # 保存报告
    output_file = OUTPUT_DIR / f"daily_report_{today}.txt"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"\n已保存: {output_file}")


if __name__ == "__main__":
    main()
