#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法 - 历史回测验证
=================================================
【无未来函数】：每个信号只用截止到当天收盘的数据
【目的】：验证四维看盘法+量线体系的信号有效性
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

# ============================================================
# 【配置区】
# ============================================================

DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

# 回测股票池（全市场抽样，或持仓股）
BACKTEST_HOLDINGS = [
    ("sh", "600584"),  # 长电科技
    ("sz", "002156"),  # 通富微电
    ("sh", "603283"),  # 赛腾股份
    ("sz", "300394"),  # 天孚通信
    ("sh", "601138"),  # 工业富联
    ("sh", "601231"),  # 环旭电子
    ("sz", "300476"),  # 胜宏科技
    ("sh", "603516"),  # 淳中科技
]

# 参数（和报告脚本保持一致）
YIN_BODY_PCT = 3.0
YIN_LOOKBACK = 60
SHORT_WINDOW = 20
MID_WINDOW = 60
LONG_WINDOW = 120
PEAK_SIDE_SHORT = 2
CONFIRM_DAYS_SHORT = 3
VOL_PERCENTILE = 0.7
BEISHU_RATIO = 2.0
VOL_RATIO_HIGH = 1.5
VOL_RATIO_LOW = 0.7

# 持有周期
HOLD_DAYS_LIST = [5, 10, 20]


# ============================================================
# 数据读取
# ============================================================
def load_klines(market, code):
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
            df = df.reset_index(drop=True)
            
            return df, data.get('name', code)
    
    return None, None


# ============================================================
# 找大阴实顶（只用截止到当天的数据）
# ============================================================
def find_big_yin_top(df_up_to_today, lookback_days, yin_body_pct):
    """在df_up_to_today（截止到当天的数据）中找大阴实顶"""
    if len(df_up_to_today) < lookback_days:
        return None, None, None
    
    recent_df = df_up_to_today.iloc[-lookback_days:]
    
    for i in range(len(recent_df)-1, -1, -1):
        row = recent_df.iloc[i]
        
        if row['close'] >= row['open']:
            continue
        
        body_pct = (row['open'] - row['close']) / row['close'] * 100
        
        if body_pct >= yin_body_pct:
            return row['open'], row['date'], i
    
    return None, None, None


# ============================================================
# 找谷底线（只用截止到当天的数据）
# ============================================================
def find_recent_valley(df_up_to_today, lookback_days, peak_side, confirm_days, vol_percentile):
    """在df_up_to_today中找最近的谷底线"""
    min_required = lookback_days + confirm_days + peak_side
    if len(df_up_to_today) < min_required:
        return None, None
    
    recent_df = df_up_to_today.iloc[-lookback_days:]
    vol_threshold = recent_df['volume'].quantile(vol_percentile)
    
    valleys = []
    start = peak_side
    end = len(recent_df) - max(peak_side, confirm_days)
    
    for i in range(start, end):
        row = recent_df.iloc[i]
        window = recent_df.iloc[i-peak_side:i+peak_side+1]
        is_local_low = row['low'] == window['low'].min()
        has_vol = row['volume'] >= vol_threshold
        
        if is_local_low and has_vol:
            future = recent_df.iloc[i+1:i+1+confirm_days]
            confirmed = all(future['close'] > row['low'])
            if confirmed:
                valleys.append({'price': row['low'], 'date': row['date']})
    
    if valleys:
        return valleys[-1]['price'], valleys[-1]['date']
    return None, None


# ============================================================
# 识别量柱形态
# ============================================================
def identify_vol_pattern(df_up_to_today):
    """在df_up_to_today中识别今天的量柱形态"""
    if len(df_up_to_today) < 10:
        return "其他"
    
    today_vol = df_up_to_today.iloc[-1]['volume']
    yesterday_vol = df_up_to_today.iloc[-2]['volume']
    
    if today_vol / yesterday_vol >= BEISHU_RATIO:
        return "倍量柱"
    
    recent_20 = df_up_to_today.iloc[-20:] if len(df_up_to_today) >= 20 else df_up_to_today
    if today_vol == recent_20['volume'].max():
        return "高量柱"
    if today_vol == recent_20['volume'].min():
        return "低量柱"
    
    v1 = df_up_to_today.iloc[-3]['volume']
    v2 = df_up_to_today.iloc[-2]['volume']
    v3 = df_up_to_today.iloc[-1]['volume']
    if v1 < v2 < v3:
        return "梯量柱"
    if v1 > v2 > v3:
        return "缩量柱"
    
    return "其他"


# ============================================================
# 主回测函数
# ============================================================
def backtest_stock(market, code, hold_days_list):
    """
    对单只股票进行回测
    在每个历史时间点，计算信号，然后看未来N天的表现
    """
    df, name = load_klines(market, code)
    if df is None:
        return None
    
    # 信号统计
    results = defaultdict(lambda: {
        'count': 0,
        'returns': {h: [] for h in hold_days_list}
    })
    
    # 从第120天开始（确保有足够数据），到倒数第20天结束（确保能看到未来20天）
    start_idx = 120
    end_idx = len(df) - max(hold_days_list)
    
    for t in range(start_idx, end_idx):
        # 只用截止到t日的数据（无未来函数）
        df_up_to_today = df.iloc[:t+1]
        
        today_price = df.iloc[t]['close']
        
        # ========== 信号1：突破大阴实顶 ==========
        big_yin_top, big_yin_date, _ = find_big_yin_top(df_up_to_today, YIN_LOOKBACK, YIN_BODY_PCT)
        
        if big_yin_top:
            # 前一天还在大阴实顶下方，今天突破上去了
            prev_price = df.iloc[t-1]['close']
            if prev_price < big_yin_top and today_price > big_yin_top:
                signal_name = "突破大阴实顶"
                for h in hold_days_list:
                    future_price = df.iloc[t+h]['close']
                    ret = (future_price - today_price) / today_price * 100
                    results[signal_name]['count'] += 1 if h == hold_days_list[0] else 0
                    results[signal_name]['returns'][h].append(ret)
        
        # ========== 信号2：回踩谷底线不破 ==========
        valley_price, valley_date = find_recent_valley(df_up_to_today, SHORT_WINDOW, PEAK_SIDE_SHORT, CONFIRM_DAYS_SHORT, VOL_PERCENTILE)
        
        if valley_price:
            # 今天最低价接近谷底线（±2%），但收盘价在谷底线上方
            today_low = df.iloc[t]['low']
            if abs(today_low - valley_price) / valley_price < 0.02 and today_price > valley_price:
                signal_name = "回踩谷底线不破"
                for h in hold_days_list:
                    future_price = df.iloc[t+h]['close']
                    ret = (future_price - today_price) / today_price * 100
                    results[signal_name]['count'] += 1 if h == hold_days_list[0] else 0
                    results[signal_name]['returns'][h].append(ret)
        
        # ========== 信号3：倍量柱 ==========
        vol_pattern = identify_vol_pattern(df_up_to_today)
        
        if vol_pattern == "倍量柱":
            signal_name = "倍量柱"
            for h in hold_days_list:
                future_price = df.iloc[t+h]['close']
                ret = (future_price - today_price) / today_price * 100
                results[signal_name]['count'] += 1 if h == hold_days_list[0] else 0
                results[signal_name]['returns'][h].append(ret)
        
        # ========== 信号4：缩量柱 ==========
        if vol_pattern == "缩量柱":
            signal_name = "缩量柱"
            for h in hold_days_list:
                future_price = df.iloc[t+h]['close']
                ret = (future_price - today_price) / today_price * 100
                results[signal_name]['count'] += 1 if h == hold_days_list[0] else 0
                results[signal_name]['returns'][h].append(ret)
        
        # ========== 信号5：低量柱（地量） ==========
        if vol_pattern == "低量柱":
            signal_name = "低量柱（地量）"
            for h in hold_days_list:
                future_price = df.iloc[t+h]['close']
                ret = (future_price - today_price) / today_price * 100
                results[signal_name]['count'] += 1 if h == hold_days_list[0] else 0
                results[signal_name]['returns'][h].append(ret)
    
    return name, results


# ============================================================
# 打印统计结果
# ============================================================
def print_results(all_results, hold_days_list):
    print("\n" + "=" * 70)
    print("四维循环看盘法 - 历史回测结果")
    print("=" * 70)
    
    # 汇总所有股票的结果
    combined = defaultdict(lambda: {
        'count': 0,
        'returns': {h: [] for h in hold_days_list}
    })
    
    for name, results in all_results:
        for signal_name, data in results.items():
            combined[signal_name]['count'] += data['count']
            for h in hold_days_list:
                combined[signal_name]['returns'][h].extend(data['returns'][h])
    
    print(f"\n总股票数：{len(all_results)}只")
    print(f"持有周期：{hold_days_list}个交易日\n")
    
    for h in hold_days_list:
        print(f"\n=== 持有{h}天 ===")
        print(f"{'信号':<20} {'样本数':>8} {'平均收益%':>10} {'中位数%':>10} {'胜率%':>8}")
        print("-" * 70)
        
        for signal_name, data in sorted(combined.items()):
            returns = data['returns'][h]
            if len(returns) == 0:
                continue
            
            avg_ret = np.mean(returns)
            median_ret = np.median(returns)
            win_rate = sum(1 for r in returns if r > 0) / len(returns) * 100
            
            print(f"{signal_name:<20} {len(returns):>8} {avg_ret:>10.2f} {median_ret:>10.2f} {win_rate:>8.1f}")
    
    print("\n" + "=" * 70)
    print("结论说明：")
    print("- 胜率>55%：信号有效，有统计意义")
    print("- 胜率50%-55%：信号一般，参考价值有限")
    print("- 胜率<50%：信号无效，甚至反向")
    print("=" * 70)


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 70)
    print("四维循环看盘法 - 历史回测验证")
    print("=" * 70)
    print(f"\n回测股票数：{len(BACKTEST_HOLDINGS)}只")
    print(f"持有周期：{HOLD_DAYS_LIST}个交易日")
    print(f"无未来函数：每个信号只用截止到当天的数据\n")
    
    all_results = []
    
    for i, (market, code) in enumerate(BACKTEST_HOLDINGS):
        print(f"  回测中 {i+1}/{len(BACKTEST_HOLDINGS)}: {market}{code}")
        result = backtest_stock(market, code, HOLD_DAYS_LIST)
        if result:
            all_results.append(result)
    
    print_results(all_results, HOLD_DAYS_LIST)
    
    # 保存结果
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "backtest_4d_summary.txt"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("四维循环看盘法 - 历史回测结果\n")
        f.write("=" * 70 + "\n\n")
        f.write(f"总股票数：{len(all_results)}只\n")
        f.write(f"持有周期：{HOLD_DAYS_LIST}个交易日\n\n")
    
    print(f"\n已保存统计结果: {output_file}")


if __name__ == "__main__":
    main()

