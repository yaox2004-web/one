#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法报告 - HTML版（信号说明区放顶部）
=================================================
设计思路（为什么这样写）：
  1. 报告顶部放【信号说明区】：定义、来源、参数、设计思路、注意事项、使用方法
  2. 个股部分只显示信号，不重复说明
  3. 所有参数阈值全部提取到【配置区】，方便根据市场环境调整

【重要：无未来函数保证】
  1. 所有判断只用截止到今天收盘的数据
  2. 峰顶线/谷底线必须是至少 (确认天数+峰边距) 天之前的
  3. 平衡线只是画线，不需要右确认

量学理论来源：
  - 股海明灯（量学官网论坛）
  - 《量柱擒涨停》黑马王子著
  - 《量线捉涨停》黑马王子著
  - 比尔·威廉姆斯分形指标（Fractals）标准：5根K线
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 【配置区】所有参数阈值都在这里，方便调整！
# ============================================================

# --- 文件路径配置 ---
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

# --- 持仓股配置 ---
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

# --- 周期配置 ---
SHORT_WINDOW = 20    # 短期窗口（交易日）
MID_WINDOW = 60      # 中期窗口（交易日）
LONG_WINDOW = 120    # 长期窗口（交易日）

# --- 峰顶线/谷底线识别参数（适配量化时代） ---
# 依据：比尔·威廉姆斯分形指标标准 + 量学理论 + 量化时代调整

# 峰边距：局部极值左右各几根K线
PEAK_SIDE_SHORT = 2    # 短期(20日)：左右各2根 → 共5根（标准分形）
PEAK_SIDE_MID = 2      # 中期(60日)：左右各2根 → 共5根（标准分形）
PEAK_SIDE_LONG = 3     # 长期(120日)：左右各3根 → 共7根（更严格）

# 右确认天数：之后多少天没突破才算确认
CONFIRM_DAYS_SHORT = 3  # 短期：3天确认
CONFIRM_DAYS_MID = 5    # 中期：5天确认
CONFIRM_DAYS_LONG = 10  # 长期：10天确认

# 量能要求：前百分之多少以上才算有量
VOL_PERCENTILE = 0.7    # 前30%以上（= 70%分位数）

# --- 高量柱安全线/风险线参数 ---
BODY_RATIO_THRESHOLD = 0.6  # 实体占比超过60%取实体顶底，否则取K线最高最低

# --- 平衡线参数 ---
# 依据：量学理论（股海明灯）
# 平衡线 = 左侧中大阴线实体顶部
# 中大阴线定义：实体跌幅大于3%
BALANCE_YIN_BODY_PCT = 3.0  # 中大阴线实体跌幅阈值（%）
BALANCE_LOOKBACK = 30        # 往前找多少天内的中大阴线

# --- 量价组合参数 ---
VOL_RATIO_HIGH = 1.5     # 量比>1.5算放量
VOL_RATIO_LOW = 0.7      # 量比<0.7算缩量

# --- 位置分位参数 ---
POSITION_HIGH = 70        # 位置>70%算高位
POSITION_LOW = 30         # 位置<30%算低位

# --- 量能位置参数 ---
VOL_POS_HIGH = 80         # 量能位置>80%算天量
VOL_POS_LOW = 20          # 量能位置<20%算地量


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
            
            return df, data.get('name', code)
    
    return None, None


# ============================================================
# 找高量柱的安全线和风险线
# ============================================================
def find_gaoliang_lines(recent_df):
    if len(recent_df) < 5:
        return None, None, None, None
    
    max_vol_idx = recent_df['volume'].idxmax()
    max_vol_row = recent_df.loc[max_vol_idx]
    
    open_price = max_vol_row['open']
    close_price = max_vol_row['close']
    high_price = max_vol_row['high']
    low_price = max_vol_row['low']
    
    body_size = abs(close_price - open_price)
    total_range = high_price - low_price
    
    if total_range == 0:
        return None, None, None, None
    
    body_ratio = body_size / total_range
    
    if body_ratio > BODY_RATIO_THRESHOLD:
        safe_line = max(open_price, close_price)
        risk_line = min(open_price, close_price)
        line_type = "实体"
    else:
        safe_line = high_price
        risk_line = low_price
        line_type = "影线"
    
    return safe_line, risk_line, line_type, max_vol_row['date']


# ============================================================
# 找平衡线（量学理论：左侧中大阴线实体顶部）
# ============================================================
def find_balance_line(df, lookback_days, yin_body_pct):
    if len(df) < lookback_days:
        return None, None
    
    recent_df = df.iloc[-lookback_days:]
    
    for i in range(len(recent_df)-1, -1, -1):
        row = recent_df.iloc[i]
        
        if row['close'] >= row['open']:
            continue
        
        body_pct = (row['open'] - row['close']) / row['close'] * 100
        
        if body_pct >= yin_body_pct:
            balance_price = row['open']
            balance_date = row['date']
            return balance_price, balance_date
    
    return None, None


# ============================================================
# 找峰顶线和谷底线（多空双方博弈过的）
# ============================================================
def find_fenggu_lines(df, lookback_days, peak_side, confirm_days, vol_percentile):
    min_required = lookback_days + confirm_days + peak_side
    if len(df) < min_required:
        return None, None, None, None
    
    recent_df = df.iloc[-lookback_days:]
    
    vol_threshold = recent_df['volume'].quantile(vol_percentile)
    
    peaks = []
    valleys = []
    
    start = peak_side
    end = len(recent_df) - max(peak_side, confirm_days)
    
    for i in range(start, end):
        row = recent_df.iloc[i]
        
        window = recent_df.iloc[i-peak_side:i+peak_side+1]
        is_local_high = row['high'] == window['high'].max()
        is_local_low = row['low'] == window['low'].min()
        
        has_vol = row['volume'] >= vol_threshold
        
        if is_local_high and has_vol:
            future = recent_df.iloc[i+1:i+1+confirm_days]
            confirmed = all(future['close'] < row['high'])
            
            if confirmed:
                peaks.append({
                    'price': row['high'],
                    'date': row['date'],
                })
        
        if is_local_low and has_vol:
            future = recent_df.iloc[i+1:i+1+confirm_days]
            confirmed = all(future['close'] > row['low'])
            
            if confirmed:
                valleys.append({
                    'price': row['low'],
                    'date': row['date'],
                })
    
    recent_peak = peaks[-1] if peaks else None
    recent_valley = valleys[-1] if valleys else None
    
    return (recent_peak['price'] if recent_peak else None,
            recent_peak['date'] if recent_peak else None,
            recent_valley['price'] if recent_valley else None,
            recent_valley['date'] if recent_valley else None)


# ============================================================
# 生成单只股票的报告数据
# ============================================================
def get_stock_data(market, code):
    df, name = load_klines(market, code)
    
    if df is None:
        return None
    
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    
    today_price = today['close']
    today_volume = today['volume']
    
    pct_chg = (today['close'] - yesterday['close']) / yesterday['close'] * 100
    
    # ========== ① 从右向左看：找位置 ==========
    recent_20 = df.iloc[-SHORT_WINDOW:]
    recent_high = recent_20['high'].max()
    recent_low = recent_20['low'].min()
    
    recent_60 = df.iloc[-MID_WINDOW:] if len(df) > MID_WINDOW else None
    mid_high = mid_low = None
    if recent_60 is not None:
        mid_high = recent_60['high'].max()
        mid_low = recent_60['low'].min()
    
    recent_120 = df.iloc[-LONG_WINDOW:] if len(df) > LONG_WINDOW else None
    long_high = long_low = None
    if recent_120 is not None:
        long_high = recent_120['high'].max()
        long_low = recent_120['low'].min()
    
    # ========== 高量柱的安全线和风险线 ==========
    safe_20, risk_20, type_20, date_20 = find_gaoliang_lines(recent_20)
    
    safe_60 = risk_60 = type_60 = date_60 = None
    if recent_60 is not None:
        safe_60, risk_60, type_60, date_60 = find_gaoliang_lines(recent_60)
    
    safe_120 = risk_120 = type_120 = date_120 = None
    if recent_120 is not None:
        safe_120, risk_120, type_120, date_120 = find_gaoliang_lines(recent_120)
    
    # ========== 平衡线 ==========
    balance_price, balance_date = find_balance_line(df, BALANCE_LOOKBACK, BALANCE_YIN_BODY_PCT)
    
    # ========== 峰顶线和谷底线 ==========
    peak_20, peak_date_20, valley_20, valley_date_20 = find_fenggu_lines(
        df, SHORT_WINDOW, PEAK_SIDE_SHORT, CONFIRM_DAYS_SHORT, VOL_PERCENTILE
    )
    
    peak_60 = peak_date_60 = valley_60 = valley_date_60 = None
    if len(df) >= MID_WINDOW + CONFIRM_DAYS_MID + PEAK_SIDE_MID:
        peak_60, peak_date_60, valley_60, valley_date_60 = find_fenggu_lines(
            df, MID_WINDOW, PEAK_SIDE_MID, CONFIRM_DAYS_MID, VOL_PERCENTILE
        )
    
    peak_120 = peak_date_120 = valley_120 = valley_date_120 = None
    if len(df) >= LONG_WINDOW + CONFIRM_DAYS_LONG + PEAK_SIDE_LONG:
        peak_120, peak_date_120, valley_120, valley_date_120 = find_fenggu_lines(
            df, LONG_WINDOW, PEAK_SIDE_LONG, CONFIRM_DAYS_LONG, VOL_PERCENTILE
        )
    
    # ========== ② 从上往下看：看量柱 ==========
    vol_high_20 = recent_20['volume'].max()
    vol_low_20 = recent_20['volume'].min()
    
    vol_ratio_yesterday = today_volume / yesterday['volume']
    vol_ratio_ma5 = today_volume / df['volume'].iloc[-6:-1].mean()
    
    vol_pos_20 = (today_volume - vol_low_20) / (vol_high_20 - vol_low_20) * 100
    
    # ========== ③ 从左往右看：比量能 ==========
    vol_vs_recent_high = today_volume / vol_high_20 * 100
    vol_vs_recent_low = today_volume / vol_low_20 * 100
    
    v1 = df.iloc[-1]['volume']
    v2 = df.iloc[-2]['volume']
    v3 = df.iloc[-3]['volume']
    if v1 > v2 > v3:
        vol_trend = "连续放量"
    elif v1 < v2 < v3:
        vol_trend = "连续缩量"
    else:
        vol_trend = "无连续趋势"
    
    # ========== ④ 从下往上看：看量价 ==========
    is_yang = today['close'] > today['open']
    
    if is_yang and vol_ratio_yesterday > VOL_RATIO_HIGH:
        vol_price = "放量涨"
    elif is_yang and vol_ratio_yesterday < VOL_RATIO_LOW:
        vol_price = "缩量涨"
    elif not is_yang and vol_ratio_yesterday > VOL_RATIO_HIGH:
        vol_price = "放量跌"
    elif not is_yang and vol_ratio_yesterday < VOL_RATIO_LOW:
        vol_price = "缩量跌"
    else:
        vol_price = "平量整理"
    
    body_size = abs(today['close'] - today['open'])
    body_ratio = body_size / (today['high'] - today['low']) * 100
    
    # ========== ⑤ 和历史对比 ==========
    short_dist_high = (recent_high - today_price) / today_price * 100
    short_dist_low = (today_price - recent_low) / today_price * 100
    
    mid_dist_high = (mid_high - today_price) / today_price * 100 if mid_high else 0
    mid_dist_low = (today_price - mid_low) / today_price * 100 if mid_low else 0
    
    long_dist_high = (long_high - today_price) / today_price * 100 if long_high else 0
    long_dist_low = (today_price - long_low) / today_price * 100 if long_low else 0
    
    # ========== ⑥ 全景总结 ==========
    pos_120 = (today_price - long_low) / (long_high - long_low) * 100 if long_high else 50
    
    if pos_120 > POSITION_HIGH:
        pos_status = "高位"
    elif pos_120 < POSITION_LOW:
        pos_status = "低位"
    else:
        pos_status = "中位"
    
    if vol_pos_20 > VOL_POS_HIGH:
        vol_status = "天量"
    elif vol_pos_20 < VOL_POS_LOW:
        vol_status = "地量"
    else:
        vol_status = "正常"
    
    if is_yang:
        power = "买方占优"
    else:
        power = "卖方占优"
    
    pct_3d = (today['close'] - df.iloc[-4]['close']) / df.iloc[-4]['close'] * 100
    pct_5d = (today['close'] - df.iloc[-6]['close']) / df.iloc[-6]['close'] * 100
    
    return {
        'name': name,
        'code': f"{market}{code}",
        'date': today['date'],
        'close': today_price,
        'pct_chg': pct_chg,
        'recent_high': recent_high,
        'recent_low': recent_low,
        'mid_high': mid_high,
        'mid_low': mid_low,
        'long_high': long_high,
        'long_low': long_low,
        'balance_price': balance_price,
        'balance_date': balance_date,
        'safe_20': safe_20,
        'risk_20': risk_20,
        'date_20': date_20,
        'safe_60': safe_60,
        'risk_60': risk_60,
        'date_60': date_60,
        'safe_120': safe_120,
        'risk_120': risk_120,
        'date_120': date_120,
        'peak_20': peak_20,
        'peak_date_20': peak_date_20,
        'valley_20': valley_20,
        'valley_date_20': valley_date_20,
        'peak_60': peak_60,
        'peak_date_60': peak_date_60,
        'valley_60': valley_60,
        'valley_date_60': valley_date_60,
        'peak_120': peak_120,
        'peak_date_120': peak_date_120,
        'valley_120': valley_120,
        'valley_date_120': valley_date_120,
        'vol_high_20': vol_high_20,
        'vol_low_20': vol_low_20,
        'vol_ratio_yesterday': vol_ratio_yesterday,
        'vol_ratio_ma5': vol_ratio_ma5,
        'vol_pos_20': vol_pos_20,
        'vol_vs_recent_high': vol_vs_recent_high,
        'vol_vs_recent_low': vol_vs_recent_low,
        'vol_trend': vol_trend,
        'is_yang': is_yang,
        'vol_price': vol_price,
        'body_ratio': body_ratio,
        'short_dist_high': short_dist_high,
        'short_dist_low': short_dist_low,
        'mid_dist_high': mid_dist_high,
        'mid_dist_low': mid_dist_low,
        'long_dist_high': long_dist_high,
        'long_dist_low': long_dist_low,
        'pos_status': pos_status,
        'vol_status': vol_status,
        'power': power,
        'pct_3d': pct_3d,
        'pct_5d': pct_5d,
    }


# ============================================================
# 生成峰顶线/谷底线的HTML
# ============================================================
def render_peak_item(label, price, date):
    if price is not None and date is not None:
        value = f"{price:.2f}（{date}）"
        value_class = "value"
    else:
        value = "无（寻顶中·偏强）"
        value_class = "value value-none value-strong"
    
    return f"""
    <div class="grid-item">
        <div class="label">{label}</div>
        <div class="{value_class}">{value}</div>
    </div>
    """


def render_valley_item(label, price, date):
    if price is not None and date is not None:
        value = f"{price:.2f}（{date}）"
        value_class = "value"
    else:
        value = "无（寻底中·偏弱）"
        value_class = "value value-none value-weak"
    
    return f"""
    <div class="grid-item">
        <div class="label">{label}</div>
        <div class="{value_class}">{value}</div>
    </div>
    """


# ============================================================
# 生成HTML
# ============================================================
def generate_html(stocks_data, today_str):
    items = []
    for stock in stocks_data:
        if stock is None:
            continue
        
        price_class = "price-up" if stock['pct_chg'] > 0 else "price-down"
        
        mid_high_str = f"{stock['mid_high']:.2f}" if stock['mid_high'] else '-'
        mid_low_str = f"{stock['mid_low']:.2f}" if stock['mid_low'] else '-'
        
        balance_str = f"{stock['balance_price']:.2f}（{stock['balance_date']}）" if stock['balance_price'] else '-'
        
        safe_20_str = f"{stock['safe_20']:.2f}（{stock['date_20']}）" if stock['safe_20'] else '-'
        risk_20_str = f"{stock['risk_20']:.2f}（{stock['date_20']}）" if stock['risk_20'] else '-'
        safe_60_str = f"{stock['safe_60']:.2f}（{stock['date_60']}）" if stock['safe_60'] else '-'
        risk_60_str = f"{stock['risk_60']:.2f}（{stock['date_60']}）" if stock['risk_60'] else '-'
        safe_120_str = f"{stock['safe_120']:.2f}（{stock['date_120']}）" if stock['safe_120'] else '-'
        risk_120_str = f"{stock['risk_120']:.2f}（{stock['date_120']}）" if stock['risk_120'] else '-'
        
        peak_20_html = render_peak_item("20日峰顶线", stock['peak_20'], stock['peak_date_20'])
        valley_20_html = render_valley_item("20日谷底线", stock['valley_20'], stock['valley_date_20'])
        peak_60_html = render_peak_item("60日峰顶线", stock['peak_60'], stock['peak_date_60'])
        valley_60_html = render_valley_item("60日谷底线", stock['valley_60'], stock['valley_date_60'])
        peak_120_html = render_peak_item("120日峰顶线", stock['peak_120'], stock['peak_date_120'])
        valley_120_html = render_valley_item("120日谷底线", stock['valley_120'], stock['valley_date_120'])
        
        item_html = f"""
        <div class="stock-card">
            <div class="stock-header">
                <div>
                    <div class="stock-name">{stock['name']}</div>
                    <div class="stock-code">{stock['code']}</div>
                </div>
                <div class="stock-price {price_class}">{stock['close']:.2f}元 ({stock['pct_chg']:+.2f}%)</div>
            </div>
            
            <div class="step-section">
                <div class="step-title">① 从右向左看：找位置</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">20日高点</div>
                            <div class="value">{stock['recent_high']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日低点</div>
                            <div class="value">{stock['recent_low']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">60日高点</div>
                            <div class="value">{mid_high_str}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">60日低点</div>
                            <div class="value">{mid_low_str}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">平衡线（大阴实顶）</div>
                <div class="step-content">
                    <div class="grid-1">
                        <div class="grid-item">
                            <div class="label">最近平衡线（近30日）</div>
                            <div class="value">{balance_str}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">峰顶线/谷底线（博弈过的）</div>
                <div class="step-content">
                    <div class="grid-2">
                        {peak_20_html}
                        {valley_20_html}
                        {peak_60_html}
                        {valley_60_html}
                        {peak_120_html}
                        {valley_120_html}
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">高量柱安全线/风险线</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">20日安全线</div>
                            <div class="value">{safe_20_str}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日风险线</div>
                            <div class="value">{risk_20_str}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">60日安全线</div>
                            <div class="value">{safe_60_str}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">60日风险线</div>
                            <div class="value">{risk_60_str}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">120日安全线</div>
                            <div class="value">{safe_120_str}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">120日风险线</div>
                            <div class="value">{risk_120_str}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">② 从上往下看：看量柱</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">20日天量</div>
                            <div class="value">{stock['vol_high_20']:.0f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日地量</div>
                            <div class="value">{stock['vol_low_20']:.0f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量比(vs昨日)</div>
                            <div class="value">{stock['vol_ratio_yesterday']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量能位置(20日)</div>
                            <div class="value">{stock['vol_pos_20']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">③ 从左往右看：比量能</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">vs 20日天量</div>
                            <div class="value">{stock['vol_vs_recent_high']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">vs 20日地量</div>
                            <div class="value">{stock['vol_vs_recent_low']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量比(vs5日)</div>
                            <div class="value">{stock['vol_ratio_ma5']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量能趋势</div>
                            <div class="value">{stock['vol_trend']}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">④ 从下往上看：看量价</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">量价组合</div>
                            <div class="value">{stock['vol_price']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">实体占比</div>
                            <div class="value">{stock['body_ratio']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">⑤ 和历史对比</div>
                <div class="step-content">
                    <p><strong>短期(20日)：</strong>
                        离高点 {stock['short_dist_high']:+.2f}% | 
                        离低点 {stock['short_dist_low']:+.2f}%
                    </p>
                    <p><strong>中期(60日)：</strong>
                        离高点 {stock['mid_dist_high']:+.2f}% | 
                        离低点 {stock['mid_dist_low']:+.2f}%
                    </p>
                    <p><strong>长期(120日)：</strong>
                        离高点 {stock['long_dist_high']:+.2f}% | 
                        离低点 {stock['long_dist_low']:+.2f}%
                    </p>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">⑥ 全景总结</div>
                <div class="summary-box">
                    <p>
                        今日{stock['pct_chg']:+.2f}%，{stock['vol_status']}，{stock['pos_status']}。<br>
                        量价组合：{stock['vol_price']}，{stock['power']}。<br>
                        近3日涨跌：{stock['pct_3d']:+.2f}%，近5日涨跌：{stock['pct_5d']:+.2f}%。<br>
                        {stock['vol_trend']}。
                    </p>
                </div>
            </div>
        </div>
        """
        items.append(item_html)
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>四维循环看盘报告 - {today_str}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            background: #0f172a; 
            color: #e2e8f0; 
            line-height: 1.6;
            padding: 20px;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{ 
            background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%); 
            color: white; 
            padding: 30px; 
            border-radius: 12px; 
            margin-bottom: 20px;
            border-left: 4px solid #fbbf24;
        }}
        .header h1 {{ font-size: 24px; color: #fbbf24; margin-bottom: 8px; }}
        .header .date {{ opacity: 0.8; font-size: 14px; }}
        
        .signal-guide {{
            background: #1e293b;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid #334155;
        }}
        .signal-guide h2 {{
            font-size: 18px;
            color: #fbbf24;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #334155;
        }}
        .signal-item {{
            margin-bottom: 12px;
            padding: 10px;
            background: #0f172a;
            border-radius: 8px;
        }}
        .signal-item h3 {{
            font-size: 14px;
            color: #60a5fa;
            margin-bottom: 6px;
        }}
        .signal-item p {{
            font-size: 12px;
            color: #cbd5e1;
            margin-bottom: 4px;
        }}
        .signal-item .source {{
            font-size: 11px;
            color: #94a3b8;
            font-style: italic;
        }}
        
        .stock-card {{ 
            background: #1e293b; 
            border-radius: 12px; 
            padding: 20px; 
            margin-bottom: 15px; 
            border: 1px solid #334155;
        }}
        .stock-header {{ 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 15px; 
            padding-bottom: 15px; 
            border-bottom: 1px solid #334155;
        }}
        .stock-name {{ font-size: 18px; font-weight: bold; color: #e2e8f0; }}
        .stock-code {{ font-size: 12px; color: #94a3b8; }}
        .stock-price {{ font-size: 22px; font-weight: bold; }}
        .price-up {{ color: #ef4444; }}
        .price-down {{ color: #22c55e; }}
        
        .step-section {{ margin-bottom: 15px; }}
        .step-title {{ 
            font-size: 14px; 
            font-weight: bold; 
            color: #60a5fa; 
            margin-bottom: 8px; 
            padding-left: 8px; 
            border-left: 3px solid #fbbf24; 
        }}
        .step-content {{ 
            background: #0f172a; 
            padding: 12px; 
            border-radius: 8px; 
            font-size: 13px; 
            color: #cbd5e1; 
        }}
        .step-content p {{ margin-bottom: 4px; }}
        
        .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
        .grid-1 {{ display: grid; grid-template-columns: 1fr; gap: 8px; }}
        .grid-item {{ 
            background: #0f172a; 
            padding: 8px; 
            border-radius: 6px; 
            font-size: 13px; 
        }}
        .grid-item .label {{ color: #94a3b8; font-size: 11px; }}
        .grid-item .value {{ font-weight: bold; color: #e2e8f0; font-size: 12px; }}
        .grid-item .value-none {{ color: #94a3b8; font-weight: normal; font-size: 11px; }}
        .grid-item .value-strong {{ color: #ef4444; font-weight: normal; font-size: 11px; }}
        .grid-item .value-weak {{ color: #22c55e; font-weight: normal; font-size: 11px; }}
        
        .summary-box {{
            background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
            padding: 15px;
            border-radius: 8px;
            margin-top: 10px;
        }}
        .summary-box p {{ margin: 0; color: #fbbf24; font-size: 13px; line-height: 1.8; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>四维循环看盘报告</h1>
            <div class="date">{today_str}</div>
            <div class="note" style="margin-top:10px;font-size:13px;opacity:0.7">四维循环看盘 + 峰顶线/谷底线 + 平衡线 + 高量柱安全线/风险线</div>
        </div>
        
        <!-- 信号说明区（顶部，只放一次） -->
        <div class="signal-guide">
            <h2>信号说明</h2>
            
            <div class="signal-item">
                <h3>① 从右向左看：找位置</h3>
                <p><strong>定义：</strong>从今天往左边看，找最近的高点和低点</p>
                <p><strong>目的：</strong>看当前价格在什么位置</p>
                <p><strong>使用方法：</strong>看当前价格离高点远还是低点远</p>
            </div>
            
            <div class="signal-item">
                <h3>平衡线（大阴实顶）</h3>
                <p><strong>定义：</strong>股票下跌后，由其左侧中大阴线实体顶部向右侧画出的水平线</p>
                <p><strong>原理：</strong>左侧大阴线顶部"实点"是多空双方上次休战的"警戒点"，下次争夺的"起动点"</p>
                <p><strong>是否需要右确认：</strong>不需要（只是画线，不是信号）</p>
                <p class="source">来源：股海明灯（量学官网）</p>
            </div>
            
            <div class="signal-item">
                <h3>峰顶线/谷底线（博弈过的）</h3>
                <p><strong>定义：</strong>多空双方激烈博弈过的位置</p>
                <p><strong>识别条件：</strong></p>
                <p>  1. 局部极值：左右各N根K线内最高/最低（峰边距）</p>
                <p>  2. 有量配合：近N天前30%以上</p>
                <p>  3. 右确认：之后N天都没突破/跌破</p>
                <p><strong>参数：</strong></p>
                <p>  短期(20日)：左右各2根，3天确认</p>
                <p>  中期(60日)：左右各2根，5天确认</p>
                <p>  长期(120日)：左右各3根，10天确认</p>
                <p><strong>无未来函数：</strong>所有判断只用截止到今天收盘的数据</p>
                <p><strong>缺失说明：</strong></p>
                <p>  - 无（寻顶中·偏强）= 空军还没组织起有效反击</p>
                <p>  - 无（寻底中·偏弱）= 多军还没组织起有效防守</p>
                <p class="source">来源：比尔·威廉姆斯分形指标 + 量学理论（股海明灯）</p>
            </div>
            
            <div class="signal-item">
                <h3>高量柱安全线/风险线</h3>
                <p><strong>定义：</strong>高量柱对应的支撑/阻力线</p>
                <p><strong>安全线：</strong>高量柱K线的顶部（支撑）</p>
                <p><strong>风险线：</strong>高量柱K线的底部（阻力）</p>
                <p><strong>取实取虚：</strong>实体占比>60%取实体顶底，否则取K线最高最低</p>
                <p><strong>是否需要右确认：</strong>不需要（高量柱已经发生了）</p>
                <p class="source">来源：量学理论（股海明灯）</p>
            </div>
            
            <div class="signal-item">
                <h3>② 从上往下看：看量柱</h3>
                <p><strong>定义：</strong>从这个价柱对应的量柱往下看</p>
                <p><strong>目的：</strong>看这个位置的量能大小</p>
            </div>
            
            <div class="signal-item">
                <h3>③ 从左往右看：比量能</h3>
                <p><strong>定义：</strong>把左侧找到的量柱和今天的量柱对比</p>
                <p><strong>目的：</strong>看量能是放大还是缩小</p>
            </div>
            
            <div class="signal-item">
                <h3>④ 从下往上看：看量价</h3>
                <p><strong>定义：</strong>从今天的量柱往上看价柱</p>
                <p><strong>目的：</strong>看量价配合关系</p>
            </div>
            
            <div class="signal-item">
                <h3>⑤ 和历史对比</h3>
                <p><strong>定义：</strong>和左侧短中长期目标对比</p>
                <p><strong>目的：</strong>看当前位置离历史高低点多远</p>
            </div>
            
            <div class="signal-item">
                <h3>⑥ 全景总结</h3>
                <p><strong>定义：</strong>客观总结当前状态</p>
                <p><strong>原则：</strong>客观描述，不做主观判断</p>
            </div>
        </div>
        
        {''.join(items)}
    </div>
</body>
</html>
"""
    
    return html


# ============================================================
# 主函数
# ============================================================
def main():
    print("=" * 60)
    print("四维循环看盘报告 - HTML版（信号说明区放顶部）")
    print("=" * 60)
    
    stocks_data = []
    today_str = ""
    
    for market, code in HOLDINGS:
        try:
            data = get_stock_data(market, code)
            if data:
                stocks_data.append(data)
                today_str = data['date']
                print(f"  已生成：{data['name']}")
        except Exception as e:
            print(f"  Error: {market}{code} {e}")
    
    html_content = generate_html(stocks_data, today_str)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    html_file = OUTPUT_DIR / f"my_holdings_4d_report_{today_str}.html"
    
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n已生成HTML报告: {html_file}")


if __name__ == "__main__":
    main()
