#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法 - 全市场历史回测
=================================================
【无未来函数】：每个信号只用截止到当天收盘的数据
【目的】：验证四维看盘法+量线体系的信号在全市场是否普遍有效
【设计思路】：自动扫描data/kline目录下所有股票，不用手动列股票池
【鲁棒性】：自动适配各种文件名格式（600584.json / sh600584.json等）
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

# ============================================================
# 【配置区】所有参数阈值都在这里，方便调整
# ============================================================

DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

# 回测参数
YIN_BODY_PCT = 3.0        # 中大阴线实体跌幅阈值（%），适配量化时代
YIN_LOOKBACK = 60          # 往前找多少天内的中大阴线
SHORT_WINDOW = 20          # 短期窗口（交易日），约一个月
PEAK_SIDE_SHORT = 2        # 峰边距：左右各2根，共5根（比尔·威廉姆斯分形标准）
CONFIRM_DAYS_SHORT = 3     # 短期：3天确认，适配量化时代快节奏
VOL_PERCENTILE = 0.7       # 前30%以上才算放量（70%分位数），适配量化时代
BEISHU_RATIO = 2.0         # 倍量柱：今天量是昨天的2倍以上

# 持有周期（交易日）
HOLD_DAYS_LIST = [5, 10, 20]


# ============================================================
# 自动扫描所有股票（鲁棒版，适配各种文件名格式）
# ============================================================
def find_all_stocks():
    """
    自动扫描data/kline目录下的所有股票
    不管文件名是 600584.json 还是 sh600584.json，都能正确识别
    """
    stocks = []
    
    if not DATA_DIR.exists():
        print(f"  警告：数据目录不存在！{DATA_DIR}")
        return stocks
    
    # 遍历data/kline下的所有子目录（sh/sz等）
    for market_dir in DATA_DIR.iterdir():
        if not market_dir.is_dir():
            continue
        
        market = market_dir.name  # sh / sz / bj
        
        for f in market_dir.glob("*.json"):
            filename = f.stem  # 去掉.json后缀
            
            # 从文件名提取code：去掉market前缀
            # 可能的情况：600584 / sh600584 / sz002156
            if filename.startswith(market):
                code = filename[len(market):]
            else:
                code = filename
            
            # 只保留6位数字的code
            if len(code) == 6 and code.isdigit():
                stocks.append((market, code))
    
    return stocks


# ============================================================
# 数据读取（和报告脚本完全一致，确保能读到）
# ============================================================
def load_klines(market, code):
    possible_paths = [
        DATA_DIR / market / f"{code}.json",
        DATA_DIR / market / f"{market}{code}.json",
        DATA_DIR / f"{market}{code}.json",
        DATA_DIR / f"{code}.json",
    ]
    
    for filepath in possible_paths:
        if filepath.exists():
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            klines = data.get('klines', [])
            if len(klines) < 150:  # 数据太少的跳过
                return None, None
            
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
# 找大阴实顶（只用截止到当天的数据，无未来函数）
# ============================================================
def find_big_yin_top(df_up_to_today, lookback_days, yin_body_pct):
    """
    找最近的中大阴线实体顶部
    量学理论：大阴实顶是多空双方上次休战的警戒点
    """
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
    """
    找最近的谷底线
    量学理论：谷底线是上次买方赢了的位置，现在变成支撑位
    识别标准：比尔·威廉姆斯分形 + 右确认 + 放量
    """
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
    """
    识别今天的量柱形态
    量学理论：高低平倍梯缩六种基本形态
    """
    if len(df_up_to_today) < 10:
        return "其他"
    
    today_vol = df_up_to_today.iloc[-1]['volume']
    yesterday_vol = df_up_to_today.iloc[-2]['volume']
    
    # 倍量柱：今天量是昨天的2倍以上
    if today_vol / yesterday_vol >= BEISHU_RATIO:
        return "倍量柱"
    
    # 高量柱：20天最高
    recent_20 = df_up_to_today.iloc[-20:] if len(df_up_to_today) >= 20 else df_up_to_today
    if today_vol == recent_20['volume'].max():
        return "高量柱"
    
    # 低量柱：20天最低
    if today_vol == recent_20['volume'].min():
        return "低量柱"
    
    # 梯量柱：连续三天递增
    v1 = df_up_to_today.iloc[-3]['volume']
    v2 = df_up_to_today.iloc[-2]['volume']
    v3 = df_up_to_today.iloc[-1]['volume']
    if v1 < v2 < v3:
        return "梯量柱"
    
    # 缩量柱：连续三天递减
    if v1 > v2 > v3:
        return "缩量柱"
    
    return "其他"


# ============================================================
# 单只股票回测
# ============================================================
def backtest_stock(market, code, hold_days_list):
    """
    对单只股票进行回测
    在每个历史时间点生成信号，统计未来N天的表现
    严格无未来函数：每个信号只用截止到当天的数据
    """
    df, name = load_klines(market, code)
    if df is None:
        return None
    
    # 信号统计：每个信号对应持有N天的收益列表
    results = defaultdict(lambda: {h: [] for h in hold_days_list})
    
    # 从第120天开始（确保有足够数据计算信号）
    # 到倒数第20天结束（确保能看到未来20天）
    start_idx = 120
    end_idx = len(df) - max(hold_days_list)
    
    for t in range(start_idx, end_idx):
        # 关键：只用截止到t日的数据！绝对无未来函数
        df_up_to_today = df.iloc[:t+1]
        today_price = df.iloc[t]['close']
        
        # ========== 信号1：突破大阴实顶 ==========
        big_yin_top, _, _ = find_big_yin_top(df_up_to_today, YIN_LOOKBACK, YIN_BODY_PCT)
        
        if big_yin_top:
            # 前一天还在大阴实顶下方，今天突破上去了
            prev_price = df.iloc[t-1]['close']
            if prev_price < big_yin_top and today_price > big_yin_top:
                for h in hold_days_list:
                    future_price = df.iloc[t+h]['close']
                    ret = (future_price - today_price) / today_price * 100
                    results["突破大阴实顶"][h].append(ret)
        
        # ========== 信号2：回踩谷底线不破 ==========
        valley_price, _ = find_recent_valley(df_up_to_today, SHORT_WINDOW, PEAK_SIDE_SHORT, CONFIRM_DAYS_SHORT, VOL_PERCENTILE)
        
        if valley_price:
            # 今天最低价接近谷底线（±2%），但收盘价在谷底线上方
            today_low = df.iloc[t]['low']
            if abs(today_low - valley_price) / valley_price < 0.02 and today_price > valley_price:
                for h in hold_days_list:
                    future_price = df.iloc[t+h]['close']
                    ret = (future_price - today_price) / today_price * 100
                    results["回踩谷底线不破"][h].append(ret)
        
        # ========== 信号3-5：量柱形态 ==========
        vol_pattern = identify_vol_pattern(df_up_to_today)
        
        if vol_pattern in ["倍量柱", "缩量柱", "低量柱", "高量柱", "梯量柱"]:
            signal_name = vol_pattern if vol_pattern != "低量柱" else "低量柱（地量）"
            for h in hold_days_list:
                future_price = df.iloc[t+h]['close']
                ret = (future_price - today_price) / today_price * 100
                results[signal_name][h].append(ret)
    
    return name, results


# ============================================================
# 打印统计结果
# ============================================================
def print_results(all_results, hold_days_list):
    print("\n" + "=" * 80)
    print("四维循环看盘法 - 全市场历史回测结果")
    print("=" * 80)
    
    # 汇总所有股票的结果
    combined = defaultdict(lambda: {h: [] for h in hold_days_list})
    
    for name, results in all_results:
        for signal_name, returns_dict in results.items():
            for h in hold_days_list:
                combined[signal_name][h].extend(returns_dict[h])
    
    total_samples = sum(len(v[hold_days_list[0]]) for v in combined.values())
    
    print(f"\n回测股票数：{len(all_results)}只")
    print(f"总信号样本数：{total_samples}个")
    print(f"持有周期：{hold_days_list}个交易日\n")
    
    for h in hold_days_list:
        print(f"\n{'='*80}")
        print(f"=== 持有{h}天 ===")
        print(f"{'信号':<20} {'样本数':>8} {'平均收益%':>10} {'中位数%':>10} {'胜率%':>8} {'结论':>10}")
        print("-" * 80)
        
        for signal_name in sorted(combined.keys()):
            returns = combined[signal_name][h]
            if len(returns) < 30:  # 样本太少的不统计
                continue
            
            avg_ret = np.mean(returns)
            median_ret = np.median(returns)
            win_rate = sum(1 for r in returns if r > 0) / len(returns) * 100
            
            # 结论
            if win_rate > 55 and avg_ret > 0:
                conclusion = "✅ 有效"
            elif win_rate > 50:
                conclusion = "⚠️ 一般"
            else:
                conclusion = "❌ 无效"
            
            print(f"{signal_name:<20} {len(returns):>8} {avg_ret:>10.2f} {median_ret:>10.2f} {win_rate:>8.1f} {conclusion:>10}")
    
    print("\n" + "=" * 80)
    print("结论说明：")
    print("- ✅ 胜率>55% 且 平均收益>0：信号有效，有统计意义")
    print("- ⚠️ 胜率50%-55%：信号一般，参考价值有限")
    print("- ❌ 胜率<50%：信号无效，甚至反向使用")
    print("=" * 80)


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 80)
    print("四维循环看盘法 - 全市场历史回测验证")
    print("=" * 80)
    
    # 自动扫描所有股票
    all_stocks = find_all_stocks()
    print(f"\n自动扫描到股票数：{len(all_stocks)}只")
    print(f"数据目录：{DATA_DIR}")
    print(f"持有周期：{HOLD_DAYS_LIST}个交易日")
    print(f"无未来函数：每个信号只用截止到当天的数据\n")
    
    all_results = []
    
    for i, (market, code) in enumerate(all_stocks):
        if (i+1) % 200 == 0:
            print(f"  进度：{i+1}/{len(all_stocks)} 已完成")
        try:
            result = backtest_stock(market, code, HOLD_DAYS_LIST)
            if result:
                all_results.append(result)
        except Exception as e:
            pass  # 个别股票出错跳过
    
    print_results(all_results, HOLD_DAYS_LIST)
    
    # 保存结果
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "backtest_4d_full_market.txt"
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write("四维循环看盘法 - 全市场历史回测结果\n")
        f.write("=" * 80 + "\n\n")
        f.write(f"回测股票数：{len(all_results)}只\n")
        f.write(f"持有周期：{HOLD_DAYS_LIST}个交易日\n\n")
    
    print(f"\n已保存统计结果: {output_file}")


if __name__ == "__main__":
    main()
