#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法报告 - HTML版（量能自适应版 + AI研判）
=================================================
【无未来函数】
【资料来源】：股海明灯《量柱擒涨停》《量线捉涨停》黑马王子著

【设计原则】
1. 核心定义保留官方（倍量/高量/低量/梯量/缩量/平量）
2. 辅助判断用分位数自适应（大量/小量/基柱要求等）
3. 所有参数全部参数化，方便调整
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 【基础路径配置】
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

HOLDINGS = [
    ("sh", "600584"),
    ("sz", "002156"),
    ("sh", "603283"),
    ("sz", "300394"),
    ("sh", "601138"),
    ("sh", "601231"),
    ("sz", "300476"),
    ("sh", "603516"),
]

# ============================================================
# 【ATR自适应总开关】
# ============================================================
ATR_ADAPTIVE = True
ATR_PERIOD = 14

# ============================================================
# 【价格类参数·ATR倍数】
# ============================================================
YIN_BODY_ATR_MULT = 1.5
YIN_BODY_FALLBACK = 5.0
YIN_LOOKBACK = 60

CHANGYANG_ATR_MULT = 1.5
CHANGYANG_FALLBACK = 5.0

LONG_RANGE_ATR_MULT = 2.0
SHORT_RANGE_ATR_MULT = 0.7

BINGLIN_ATR_MULT = 0.5
BINGLIN_FALLBACK = 2.0

LONG_LEG_ATR_MULT = 1.0
GAP_ATR_MULT = 0.5

# ============================================================
# 【量柱核心定义参数·来源：股海明灯官网】
# ============================================================
BEISHU_RATIO = 1.8
GAOLIANG_LOOKBACK = 20
PINGLIANG_TOLERANCE = 0.15

SMALL_BEISHU_MIN = 1.5
SMALL_BEISHU_MAX = 2.0

# ============================================================
# 【量能自适应参数·分位数·来源：量化行业通用做法】
# ============================================================
VOL_LOOKBACK = 20
VOL_PCTL_HIGH = 0.80
VOL_PCTL_LOW = 0.20
BASE_VOL_PCTL = 0.60

BEISHUO_EXTEND_PCTL = 0.80
BEISHUO_SHRINK_PCTL = 0.20
BEISHUO_LOOKBACK = 5

LONG_YIN_SHORT_VOL_PCTL = 0.30

# ============================================================
# 【涨停板参数】
# ============================================================
LIMIT_UP_MAIN = 9.8
LIMIT_UP_GEM = 19.8

# ============================================================
# 【王牌柱参数·官方定义】
# ============================================================
GENERAL_CONFIRM_DAYS = 3

# ============================================================
# 【峰顶线/谷底线参数】
# ============================================================
SHORT_WINDOW = 20
MID_WINDOW = 60
LONG_WINDOW = 120

PEAK_SIDE_SHORT = 2
PEAK_SIDE_MID = 2
PEAK_SIDE_LONG = 3

CONFIRM_DAYS_SHORT = 2
CONFIRM_DAYS_MID = 3
CONFIRM_DAYS_LONG = 10

VOL_PERCENTILE = 0.7

# ============================================================
# 【量线参数】
# ============================================================
BODY_RATIO_THRESHOLD = 0.6

PRECISE_MIN_POINTS = 3
PRECISE_PRICE_TOLERANCE = 1.0
PRECISE_LOOKBACK = 120

XIEHENG_MIN_POINTS = 2

BALANCE_LOOKBACK = 30

# ============================================================
# 【关键位量影响力参数】
# ============================================================
IMPACT_VS_KEY_VOL_HIGH = 0.8
IMPACT_VS_KEY_VOL_MID = 0.5

IMPACT_TIME_NEAR = 15
IMPACT_TIME_MID = 45

# ============================================================
# 【位置分位参数】
# ============================================================
POSITION_HIGH = 70
POSITION_LOW = 30

VOL_POS_HIGH = 80
VOL_POS_LOW = 20

# ============================================================
# 【实体长短参数】
# ============================================================
BODY_RATIO_LONG = 0.6
BODY_RATIO_SHORT = 0.3

# ============================================================
# 【凹口线参数】
# ============================================================
AOKOU_MIN_GAP = 3
AOKOU_MAX_GAP = 13
AOKOU_PINGLIANG_TOLERANCE = 0.15
AOKOU_MIDDLE_SHADOW = 0.6

# ============================================================
# 【形态信号参数】
# ============================================================
TOUCH_LINE_TOLERANCE = 0.02

JIYIN_PREV_DAYS = 5
CIYANG_REBOUND_PCT = 50

NIUGU_LOOKBACK = 60
NIUGU_TOUCH_TOLERANCE = 0.01

DILIANG_GROUP_DAYS = 100
DILIANG_GROUP_COUNT = 5

JIA_SHENG_LIANG_SUO_DAYS = 3

HUICAI_PRECISION_DAYS = 10

DOUBLE_SWORD_UPPER_RATIO = 2.0
DOUBLE_SWORD_LOWER_RATIO = 2.0

SANYUAN_DAYS = 3

DAYANG_DOUBLE_REST_DAYS = 5

JIELI_DOUBLE_YANG_GAP_MIN = 5
JIELI_DOUBLE_YANG_GAP_MAX = 20

GOLD_CROSS_SHORT_MA = 5
GOLD_CROSS_LONG_MA = 10
GOLD_CROSS_VOL_SHORT = 5
GOLD_CROSS_VOL_LONG = 10

PRECISE_FENGGU_TOLERANCE = 0.01

XIANCHANG_ZHIBIE_DAYS = 10
XIANCHANG_ZHIBIE_AMPLITUDE = 0.05
XIANCHANG_ZHIBIE_VOL = 0.8

XUANYIN31_DAYS = 3

T4_VARIANT_DAYS = 4
T4_VARIANT_UP_PCT = 5.0

# ============================================================
# 【新增：位置分档参数】
# ============================================================
POSITION_LOOKBACK = 120
LOW_PCTL = 0.30
HIGH_PCTL = 0.70

# ============================================================
# 【新增：趋势判断参数】
# ============================================================
TREND_MA_PERIOD = 20

# ============================================================
# 【回测胜率数据】
# ============================================================
def load_winrate_data():
    """加载回测胜率数据，如果文件不存在用默认值兜底"""
    winrate_path = Path(__file__).parent.parent / "data" / "analysis" / "winrate.json"
    
    default_winrate = {
        "低位": {
            "上升趋势": {
                "过左峰": 63.9, "元帅柱": 67.2, "回踩精准线": 51.7,
                "阳包阴": 53.7, "地量群": 47.4, "平量柱": 45.0,
                "黄金柱": 42.6, "将军柱": 35.1,
            },
            "下降趋势": {
                "倍量柱": 57.0, "价升量缩": 55.7, "地量群": 49.2,
                "平量柱": 50.8, "黄金柱": 50.8,
            }
        },
        "中位": {
            "上升趋势": {
                "突破大阴实顶": 68.4, "过左峰": 66.1, "地量群": 65.3,
                "低量柱（地量）": 64.9, "平量柱": 60.0, "黄金柱": 59.8,
                "回踩精准线": 58.1, "倍量伸缩": 58.0, "缩量柱": 57.9,
                "梯量柱": 58.6, "小倍阳（矮将军）": 58.8, "阳胜进": 57.5,
                "阴胜出": 56.9, "将军柱": 55.8, "倍量柱": 55.9,
                "倍量不穿": 55.7, "阳包阴": 51.3,
            },
            "下降趋势": {
                "过左峰": 71.4, "倍量柱": 54.5, "将军柱": 52.9,
                "倍量伸缩": 50.5, "价升量缩": 51.2,
            }
        },
        "高位": {
            "上升趋势": {
                "过左峰": 56.2, "阴胜出": 56.8, "低量柱（地量）": 56.6,
                "平量柱": 51.9, "高量柱": 53.0, "缩量柱": 51.3,
            },
            "下降趋势": {
                "突破大阴实顶": 55.6, "价升量缩": 69.2, "过左峰": 60.0,
                "倍量柱": 54.8,
            }
        }
    }
    
    try:
        if winrate_path.exists():
            with open(winrate_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        else:
            print(f"  提示：未找到 {winrate_path}，使用默认胜率数据")
            return default_winrate
    except Exception as e:
        print(f"  提示：读取胜率文件失败({e})，使用默认胜率数据")
        return default_winrate

BACKTEST_WINRATE = load_winrate_data()


# ============================================================
# 【新增：大盘环境判断】
# ============================================================
def get_market_regime():
    sh_index_path = Path(__file__).parent.parent / "data" / "kline" / "sh" / "sh000001.json"
    if not sh_index_path.exists():
        sh_index_path = Path(__file__).parent.parent / "data" / "kline" / "sh000001.json"
    if not sh_index_path.exists():
        return "未知", None

    try:
        with open(sh_index_path, 'r') as f:
            data = json.load(f)
        klines = data.get('klines', [])
        if len(klines) < 20:
            return "未知", None

        df = pd.DataFrame(klines)
        ncols = len(klines[0])
        cols = ['date', 'open', 'close', 'high', 'low', 'volume'] if ncols == 6 else ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
        df = df.iloc[:, :ncols]
        df.columns = cols[:ncols]
        df['close'] = pd.to_numeric(df['close'], errors='coerce')
        df = df.dropna(subset=['close'])

        ma20 = df.iloc[-20:]['close'].mean()
        today_close = df.iloc[-1]['close']
        vs_ma20_pct = (today_close - ma20) / ma20 * 100

        if today_close > ma20:
            return "多头市场", vs_ma20_pct
        else:
            return "空头市场", vs_ma20_pct

    except Exception as e:
        return "未知", None


# ============================================================
# 【新增：位置计算】
# ============================================================
def get_position_level(df):
    if len(df) < POSITION_LOOKBACK:
        return "未知", 50
    recent_df = df.iloc[-POSITION_LOOKBACK:]
    today_price = df.iloc[-1]['close']
    pct = (recent_df['close'] < today_price).sum() / len(recent_df)
    if pct < LOW_PCTL:
        return "低位", pct * 100
    elif pct > HIGH_PCTL:
        return "高位", pct * 100
    else:
        return "中位", pct * 100


# ============================================================
# 【新增：趋势判断】
# ============================================================
def get_stock_trend(df):
    if len(df) < TREND_MA_PERIOD:
        return "未知"
    ma = df.iloc[-TREND_MA_PERIOD:]['close'].mean()
    today_close = df.iloc[-1]['close']
    if today_close > ma:
        return "上升趋势"
    else:
        return "下降趋势"


# ============================================================
# 【新增：信号有效性查询】
# ============================================================
def get_signal_effectiveness(signal_name, position, trend, is_real=None):
    if position == "未知" or trend == "未知":
        return None, None
    pos_data = BACKTEST_WINRATE.get(position, {})
    trend_data = pos_data.get(trend, {})
    
    winrate_data = None
    if is_real is True:
        winrate_data = trend_data.get(f"{signal_name}_真金")
    elif is_real is False:
        winrate_data = trend_data.get(f"{signal_name}_量化")
    
    if winrate_data is None:
        winrate_data = trend_data.get(signal_name)
    
    if winrate_data is None:
        return None, None
    
    if isinstance(winrate_data, dict):
        win_rate = winrate_data.get("win_rate", 0)
        avg_ret = winrate_data.get("avg_ret", 0)
        if win_rate >= 55 and avg_ret > 0:
            return win_rate, "有效"
        elif win_rate >= 50:
            return win_rate, "一般"
        else:
            return win_rate, "无效"
    else:
        win_rate = winrate_data
        if win_rate >= 55:
            return win_rate, "有效"
        elif win_rate >= 50:
            return win_rate, "一般"
        else:
            return win_rate, "无效"


# ============================================================
# 【新增：识别量化对倒（用1分钟数据）】
# ============================================================
def analyze_1min_volatility(code):
    import os
    one_min_path = Path(__file__).parent.parent / "data" / "kline_1min" / f"{code}.json"
    if not one_min_path.exists():
        return None, None, None, None, None

    try:
        with open(one_min_path, 'r') as f:
            data = json.load(f)
        klines = data.get('klines', [])
        if len(klines) < 60:
            return None, None, None, None, None

        day_klines = klines[-240:] if len(klines) >= 240 else klines
        if len(day_klines) < 30:
            return None, None, None, None, None

        volumes = []
        closes = []
        for k in day_klines:
            try:
                if len(k) > 5:
                    vol = float(k[5])
                    close = float(k[2])
                    volumes.append(vol)
                    closes.append(close)
            except:
                continue

        if not volumes or len(volumes) < 30:
            return None, None, None, None, None

        vol_mean = np.mean(volumes)
        vol_std = np.std(volumes)
        cv = vol_std / vol_mean if vol_mean > 0 else 999

        if len(closes) == len(volumes) and len(closes) > 10:
            price_changes = np.diff(closes)
            vol_changes = np.diff(volumes)
            if np.std(price_changes) > 0 and np.std(vol_changes) > 0:
                corr = np.corrcoef(price_changes, vol_changes)[0, 1]
            else:
                corr = 0
        else:
            corr = 0

        tail_vol = sum(volumes[-30:])
        total_vol = sum(volumes)
        tail_ratio = tail_vol / total_vol if total_vol > 0 else 0

        quant_score = 0
        if cv < 0.5:
            quant_score += 1
        if abs(corr) < 0.3:
            quant_score += 1
        if tail_ratio > 0.3:
            quant_score += 1

        if quant_score >= 2:
            verdict = "量化对倒"
        elif quant_score == 1:
            verdict = "疑似量化"
        else:
            verdict = "真金白银"

        if cv < 0.5:
            cv_contrib = 70
        elif cv < 1.0:
            cv_contrib = 40
        else:
            cv_contrib = 10

        if abs(corr) < 0.2:
            corr_contrib = 60
        elif abs(corr) < 0.5:
            corr_contrib = 30
        else:
            corr_contrib = 10

        if tail_ratio > 0.4:
            tail_contrib = 70
        elif tail_ratio > 0.2:
            tail_contrib = 40
        else:
            tail_contrib = 10

        quant_pct = (cv_contrib + corr_contrib + tail_contrib) / 3

        return verdict, cv, corr, tail_ratio, quant_pct

    except Exception as e:
        return None, None, None, None, None


# ============================================================
# 【新增：筹码集中/分散（用股东户数数据）】
# ============================================================
def get_shareholder_chips(code):
    import os
    holders_dir = Path(__file__).parent.parent / "data" / "holders"
    if not holders_dir.exists():
        return None, None, None

    try:
        import re
        all_files = list(holders_dir.glob("*.json"))
        date_files = [f for f in all_files if re.match(r'^\d{8}$', f.stem)]
        files = sorted(date_files, key=lambda p: p.stem, reverse=True)
        if not files:
            return None, None, None

        with open(files[0], 'r') as f:
            data = json.load(f)

        stock_list = data.get('stocks', {})
        stock_data = stock_list.get(code, [])
        if not stock_data:
            for k in stock_list.keys():
                if code in k:
                    stock_data = stock_list[k]
                    break

        if not stock_data or len(stock_data) < 2:
            return None, None, None

        latest = stock_data[0]
        prev = stock_data[1]

        def find_holders_field(record):
            for key in record.keys():
                key_lower = key.lower()
                if '户' in key or 'holder' in key_lower or 'num' in key_lower:
                    val = record[key]
                    if isinstance(val, (int, float)) and val > 100:
                        return val
            return None

        latest_holders = find_holders_field(latest)
        prev_holders = find_holders_field(prev)

        if latest_holders is None or prev_holders is None:
            return None, None, None

        change_pct = (latest_holders - prev_holders) / prev_holders * 100

        if change_pct < -5:
            verdict = "筹码集中（主力吸筹）"
        elif change_pct > 5:
            verdict = "筹码分散（主力出货）"
        else:
            verdict = "筹码稳定"

        return verdict, latest_holders, change_pct

    except Exception as e:
        return None, None, None


# ============================================================
# 【新增：主力成本区（VWAP）】
# ============================================================
def calc_main_cost(df, lookback=60):
    if len(df) < lookback:
        lookback = len(df)
    recent_df = df.iloc[-lookback:]

    total_vol = recent_df['volume'].sum()
    if total_vol == 0:
        return None, None

    typical_price = (recent_df['high'] + recent_df['low'] + recent_df['close']) / 3
    vwap = (typical_price * recent_df['volume']).sum() / total_vol

    today_price = df.iloc[-1]['close']
    vs_cost_pct = (today_price - vwap) / vwap * 100

    return vwap, vs_cost_pct


# ============================================================
# 【新增：龙虎榜解读】
# ============================================================
def get_lhb_info(code):
    import os
    lhb_dir = Path(__file__).parent.parent / "data" / "lhb"
    if not lhb_dir.exists():
        return None, None

    try:
        files = sorted(lhb_dir.glob("*.json"), reverse=True)
        if not files:
            return None, None

        with open(files[0], 'r') as f:
            data = json.load(f)

        rows = data.get('rows', [])
        code_short = code[2:] if code.startswith(('sh', 'sz')) else code

        for row in rows:
            if str(row.get('SECURITY_CODE', '')) == code_short:
                reason = row.get('EXPLAIN', '未知原因')
                buy_amount = row.get('BUYLIST', 0)
                return reason, buy_amount

        return None, None

    except Exception as e:
        return None, None


# ============================================================
# 【新增：融资融券】
# ============================================================
def get_margin_info(code):
    import os
    margin_dir = Path(__file__).parent.parent / "data" / "margin"
    if not margin_dir.exists():
        return None, None

    try:
        files = sorted(margin_dir.glob("*.json"), reverse=True)
        if not files:
            return None, None

        with open(files[0], 'r') as f:
            data = json.load(f)

        code_short = code[2:] if code.startswith(('sh', 'sz')) else code
        sse_data = data.get('data', {}).get('sse', [])
        szse_data = data.get('data', {}).get('szse', [])

        for record in sse_data + szse_data:
            found_code = False
            for key, val in record.items():
                val_str = str(val)
                if code_short in val_str:
                    found_code = True
                    break

            if found_code:
                max_val = 0
                for key, val in record.items():
                    try:
                        num = float(val)
                        if num > max_val and num > 1e6:
                            max_val = num
                    except:
                        pass
                if max_val > 0:
                    return max_val, "融资余额"

        return None, None

    except Exception as e:
        return None, None


# ============================================================
# 【新增：北向资金】
# ============================================================
def get_north_info(code):
    import os
    north_dir = Path(__file__).parent.parent / "data" / "north"
    if not north_dir.exists():
        return None, None

    try:
        files = sorted(north_dir.glob("*.json"), reverse=True)
        if not files:
            return None, None

        with open(files[0], 'r') as f:
            data = json.load(f)

        rows = data.get('rows', [])
        code_short = code[2:] if code.startswith(('sh', 'sz')) else code

        for row in rows:
            found_code = False
            for key, val in row.items():
                val_str = str(val)
                if code_short in val_str:
                    found_code = True
                    break

            if found_code:
                max_val = 0
                for key, val in row.items():
                    try:
                        num = float(val)
                        if num > max_val and num > 1e4:
                            max_val = num
                    except:
                        pass
                if max_val > 0:
                    return max_val, "北向持仓"

        return None, None

    except Exception as e:
        return None, None


# ============================================================
# 【新增：限售解禁】
# ============================================================
def get_restricted_info(code):
    import os
    restricted_dir = Path(__file__).parent.parent / "data" / "restricted"
    if not restricted_dir.exists():
        return None, None

    try:
        files = sorted(restricted_dir.glob("*.json"), reverse=True)
        if not files:
            return None, None

        with open(files[0], 'r') as f:
            data = json.load(f)

        rows = data.get('data', [])
        code_short = code[2:] if code.startswith(('sh', 'sz')) else code

        for row in rows:
            if str(row.get('股票代码', '')) == code_short:
                date = row.get('上市时间', '未知')
                amount = row.get('实际解禁数量', 0)
                return date, amount

        return None, None

    except Exception as e:
        return None, None


# ============================================================
# 【新增：周线共振】
# ============================================================
def get_weekly_resonance(df):
    if len(df) < 60:
        return None, None

    df = df.copy()
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)
    weekly = df.resample('W').agg({
        'open': 'first',
        'high': 'max',
        'low': 'min',
        'close': 'last',
        'volume': 'sum'
    }).dropna()

    if len(weekly) < 10:
        return None, None

    closes = weekly['close'].values
    if len(closes) < 26:
        return None, None

    ema12 = pd.Series(closes).ewm(span=12).mean().values
    ema26 = pd.Series(closes).ewm(span=26).mean().values
    dif = ema12 - ema26
    dea = pd.Series(dif).ewm(span=9).mean().values
    macd = (dif - dea) * 2

    if macd[-1] > 0 and macd[-2] <= 0:
        return "金叉", "周线MACD金叉！"
    elif macd[-1] < 0 and macd[-2] >= 0:
        return "死叉", "周线MACD死叉！"
    elif macd[-1] > 0:
        return "多头", "周线MACD多头"
    else:
        return "空头", "周线MACD空头"


# ============================================================
# 【新增：王牌线（黄金线/将军线/元帅线）】
# ============================================================
def get_ace_lines(df, pillar_type, pillar_idx):
    if pillar_type is None or pillar_idx is None or pillar_idx < 0:
        return None, None, None

    row = df.iloc[pillar_idx]
    open_price = row['open']
    close_price = row['close']
    low_price = row['low']

    ace_line = min(open_price, close_price)

    today_price = df.iloc[-1]['close']
    vs_ace_pct = (today_price - ace_line) / ace_line * 100

    return ace_line, vs_ace_pct, pillar_type


# ============================================================
# 【新增：价柱形态识别】
# ============================================================
def identify_price_pattern(df):
    if len(df) < 2:
        return "未知"
    today = df.iloc[-1]
    open_price = today['open']
    close_price = today['close']
    high_price = today['high']
    low_price = today['low']
    body = abs(close_price - open_price)
    total_range = high_price - low_price
    upper_shadow = high_price - max(open_price, close_price)
    lower_shadow = min(open_price, close_price) - low_price

    if total_range == 0:
        return "十字星"

    body_ratio = body / total_range
    lower_ratio = lower_shadow / total_range
    upper_ratio = upper_shadow / total_range

    if body_ratio > 0.7 and (close_price - open_price) / open_price * 100 > 3:
        return "长阳"
    if body_ratio > 0.7 and (open_price - close_price) / open_price * 100 > 3:
        return "长阴"

    if body_ratio < 0.1:
        return "十字星"

    if lower_ratio > 0.6 and body_ratio < 0.3 and close_price > open_price:
        return "锤头线"

    if upper_ratio > 0.6 and body_ratio < 0.3 and close_price < open_price:
        return "上吊线"

    yesterday = df.iloc[-2]
    if close_price < open_price and yesterday['close'] > yesterday['open']:
        if open_price > yesterday['close'] and close_price < yesterday['open']:
            return "阴包阳"

    return "普通"


# ============================================================
# 【新增：组合信号】
# ============================================================
def get_combined_signals(df, vol_pattern, peak_20):
    signals = []
    today_price = df.iloc[-1]['close']
    today_vol = df.iloc[-1]['volume']
    yesterday_vol = df.iloc[-2]['volume']

    if vol_pattern == "倍量柱" and peak_20 and today_price > peak_20:
        signals.append("倍量过左峰")

    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    if today['close'] > yesterday['open'] and today['open'] < yesterday['close'] and today['close'] > today['open']:
        signals.append("阳包阴")

    if len(df) >= 2:
        pct_1d = (today_price - df.iloc[-2]['close']) / df.iloc[-2]['close'] * 100
        vol_change = (today_vol - yesterday_vol) / yesterday_vol * 100 if yesterday_vol > 0 else 0
        if pct_1d > 0 and vol_change < -20:
            signals.append("价升量缩")

    return signals


# ============================================================
# 【新增：峰谷线】
# ============================================================
def get_fenggu_line(peaks, valleys):
    if len(peaks) < 1 or len(valleys) < 1:
        return None

    recent_peak = peaks[-1]['price'] if peaks else None
    recent_valley = valleys[-1]['price'] if valleys else None

    if recent_peak and recent_valley:
        fenggu_line = (recent_peak + recent_valley) / 2
        return fenggu_line

    return None


# ============================================================
# 【新增：量价背离】
# ============================================================
def get_volume_price_divergence(df):
    if len(df) < 10:
        return None

    recent_10 = df.iloc[-10:]
    price_change = (recent_10.iloc[-1]['close'] - recent_10.iloc[0]['close']) / recent_10.iloc[0]['close'] * 100
    vol_change = (recent_10.iloc[-1]['volume'] - recent_10.iloc[0]['volume']) / recent_10.iloc[0]['volume'] * 100

    if price_change > 5 and vol_change < -20:
        return "顶背离（价涨量缩）"
    if price_change < -5 and vol_change > 20:
        return "底背离（价跌量增）"

    return None


# ============================================================
# 【新增：风险信号提示】
# ============================================================
def get_risk_signals(position, stock_trend, vol_pattern):
    risks = []

    if position == "高位" and vol_pattern == "倍量柱":
        risks.append("⚠️ 高位倍量柱（出货信号）")

    if stock_trend == "下降趋势" and "突破大阴实顶" in str(vol_pattern):
        risks.append("⚠️ 下降趋势突破（假突破）")

    return risks


# ============================================================
# 【新增：凹口淘金】
# ============================================================
def get_ao_kou(df):
    if len(df) < 30:
        return None

    recent_30 = df.iloc[-30:]
    recent_high = recent_30['high'].max()
    recent_low = recent_30['low'].min()
    today_price = df.iloc[-1]['close']

    low_idx = recent_30['low'].idxmin()
    low_price = recent_30.loc[low_idx, 'low']
    rise_pct = (today_price - low_price) / low_price * 100

    if 10 < rise_pct < 20:
        after_low = recent_30.loc[low_idx:]
        if len(after_low) > 5:
            mid_high = after_low.iloc[5:]['high'].max() if len(after_low) > 5 else 0
            if mid_high > 0 and today_price < mid_high * 0.95:
                return f"凹口淘金（从底部上涨{rise_pct:.1f}%）"

    return None


# ============================================================
# 【新增：三阴选股】
# ============================================================
def get_san_yin(df):
    if len(df) < 4:
        return None

    last_3 = df.iloc[-3:]
    all_yin = all(row['close'] < row['open'] for _, row in last_3.iterrows())

    if all_yin:
        total_drop = (last_3.iloc[-1]['close'] - df.iloc[-4]['close']) / df.iloc[-4]['close'] * 100
        if total_drop < -5:
            return f"三阴杀跌（累计{total_drop:.1f}%）"

    return None


# ============================================================
# 【新增：主力意图识别】
# ============================================================
def get_main_force_intent(position, stock_trend, vol_pattern, pillar_type, vol_verdict, price_pattern):
    signals = []

    if position == "低位" and vol_pattern == "倍量柱" and vol_verdict == "真金白银" and stock_trend == "上升趋势":
        signals.append(("建仓中", "#10b981", "低位+倍量+真金白银+上升=主力建仓！"))

    if position == "中位" and pillar_type == "黄金柱" and stock_trend == "上升趋势":
        signals.append(("洗盘", "#f59e0b", "中位+黄金柱+上升=主力洗盘！"))

    if position == "中位" and pillar_type == "元帅柱" and vol_pattern == "倍量柱":
        signals.append(("拉升", "#10b981", "中位+元帅柱+倍量=主力拉升！"))

    if position == "高位" and vol_pattern == "倍量柱" and vol_verdict == "量化对倒":
        signals.append(("出货", "#ef4444", "高位+倍量+量化对倒=主力出货！"))

    if position == "高位" and price_pattern == "长阴" and vol_pattern in ["倍量柱", "高量柱"]:
        signals.append(("出逃", "#ef4444", "高位+长阴+放量=主力出逃！"))

    if position == "低位" and vol_pattern == "地量群" and vol_verdict == "真金白银":
        signals.append(("吸筹", "#10b981", "低位+地量群+真金白银=主力吸筹！"))

    if position in ["中位", "高位"] and vol_pattern == "倍量柱" and vol_verdict == "量化对倒":
        signals.append(("诱多", "#f97316", "倍量+量化对倒=主力诱多！"))

    if signals:
        return signals
    else:
        return [("观望", "#94a3b8", "暂无明显主力意图")]


# ============================================================
# 【ATR计算】
# ============================================================
def calculate_atr(df, period=14):
    if len(df) < period + 1:
        return None, None
    high = df['high'].values
    low = df['low'].values
    close = df['close'].values
    tr = np.maximum(
        high[1:] - low[1:],
        np.maximum(
            np.abs(high[1:] - close[:-1]),
            np.abs(low[1:] - close[:-1])
        )
    )
    atr = np.mean(tr[-period:])
    atr_pct = atr / close[-1] * 100
    return atr, atr_pct


def get_atr_threshold(atr_pct, mult, fallback):
    if ATR_ADAPTIVE and atr_pct is not None:
        return atr_pct * mult
    else:
        return fallback


def is_gem_star(code):
    pure = code[2:] if code.startswith(('sh', 'sz')) else code
    if pure.startswith('300') or pure.startswith('301') or pure.startswith('688'):
        return True
    return False


# ============================================================
# 【量能分位数工具函数】
# ============================================================
def get_vol_percentile(df, lookback=20):
    if len(df) < lookback:
        lookback = len(df)
    recent_vols = df.iloc[-lookback:]['volume']
    today_vol = df.iloc[-1]['volume']
    pct = (recent_vols < today_vol).sum() / len(recent_vols)
    return pct


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
            cols = ['date', 'open', 'close', 'high', 'low', 'volume'] if ncols == 6 else ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
            df = pd.DataFrame(klines)
            df = df.iloc[:, :ncols]
            df.columns = cols[:ncols]
            for col in ['open', 'close', 'high', 'low', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
            return df, data.get('name', code)
    return None, None


# ============================================================
# 找大阴实顶
# ============================================================
def find_big_yin_top(df, lookback_days, yin_body_pct):
    if len(df) < lookback_days:
        return None, None, None, None, None, None
    recent_df = df.iloc[-lookback_days:]
    for i in range(len(recent_df)-1, -1, -1):
        row = recent_df.iloc[i]
        if row['close'] >= row['open']:
            continue
        body_pct = (row['open'] - row['close']) / row['close'] * 100
        if body_pct >= yin_body_pct:
            return row['open'], row['close'], row['date'], row['volume'], len(df) - lookback_days + i
    return None, None, None, None, None, None


# ============================================================
# 找高量柱安全线/风险线
# ============================================================
def find_gaoliang_lines(recent_df):
    if len(recent_df) < 5:
        return None, None, None, None, None, None
    max_vol_idx = recent_df['volume'].idxmax()
    max_vol_row = recent_df.loc[max_vol_idx]
    open_price = max_vol_row['open']
    close_price = max_vol_row['close']
    high_price = max_vol_row['high']
    low_price = max_vol_row['low']
    body_size = abs(close_price - open_price)
    total_range = high_price - low_price
    if total_range == 0:
        return None, None, None, None, None, None
    body_ratio = body_size / total_range
    if body_ratio > BODY_RATIO_THRESHOLD:
        safe_line = max(open_price, close_price)
        risk_line = min(open_price, close_price)
        line_type = "实体"
    else:
        safe_line = high_price
        risk_line = low_price
        line_type = "影线"
    return safe_line, risk_line, line_type, max_vol_row['date'], max_vol_row['volume']


# ============================================================
# 找平衡线
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
            return row['open'], row['date']
    return None, None


# ============================================================
# 找精准线
# ============================================================
def find_precise_lines(df, lookback_days, min_points, price_tolerance):
    if len(df) < lookback_days:
        return []
    recent_df = df.iloc[-lookback_days:]
    prices = recent_df['close'].values
    precise_lines = []
    used_indices = set()
    for i in range(len(prices)):
        if i in used_indices:
            continue
        price_i = prices[i]
        cluster_indices = [i]
        for j in range(len(prices)):
            if i == j or j in used_indices:
                continue
            diff_pct = abs(price_i - prices[j]) / price_i * 100
            if diff_pct <= price_tolerance:
                cluster_indices.append(j)
        if len(cluster_indices) >= min_points:
            avg_price = np.mean([prices[idx] for idx in cluster_indices])
            dates = [recent_df.iloc[idx]['date'] for idx in cluster_indices]
            precise_lines.append({
                'price': avg_price,
                'points': len(cluster_indices),
                'first_date': min(dates),
                'last_date': max(dates),
            })
            for idx in cluster_indices:
                used_indices.add(idx)
    precise_lines.sort(key=lambda x: x['points'], reverse=True)
    return precise_lines[:3]


# ============================================================
# 找峰顶线/谷底线
# ============================================================
def find_fenggu_lines(df, lookback_days, peak_side, confirm_days, vol_percentile):
    min_required = lookback_days + confirm_days + peak_side
    if len(df) < min_required:
        return None, None, None, None, None, [], []
    recent_df = df.iloc[-lookback_days:]
    vol_threshold = recent_df['volume'].quantile(vol_percentile)
    peaks, valleys = [], []
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
            if all(future['close'] < row['high']):
                peaks.append({'price': row['high'], 'date': row['date'], 'volume': row['volume']})
        if is_local_low and has_vol:
            future = recent_df.iloc[i+1:i+1+confirm_days]
            if all(future['close'] > row['low']):
                valleys.append({'price': row['low'], 'date': row['date'], 'volume': row['volume']})
    recent_peak = peaks[-1] if peaks else None
    recent_valley = valleys[-1] if valleys else None
    return (recent_peak['price'] if recent_peak else None,
            recent_peak['date'] if recent_peak else None,
            recent_valley['price'] if recent_valley else None,
            recent_valley['date'] if recent_valley else None,
            peaks, valleys)


# ============================================================
# 找斜衡线
# ============================================================
def find_xieheng_line(peaks, valleys, today_price):
    up_line = None
    down_line = None
    if len(valleys) >= XIEHENG_MIN_POINTS:
        v1 = valleys[-2]
        v2 = valleys[-1]
        if v2['price'] > v1['price']:
            up_line = {
                'type': '上升',
                'point1_price': v1['price'],
                'point1_date': v1['date'],
                'point2_price': v2['price'],
                'point2_date': v2['date'],
                'above_line': today_price > v2['price'],
            }
    if len(peaks) >= XIEHENG_MIN_POINTS:
        p1 = peaks[-2]
        p2 = peaks[-1]
        if p2['price'] < p1['price']:
            down_line = {
                'type': '下降',
                'point1_price': p1['price'],
                'point1_date': p1['date'],
                'point2_price': p2['price'],
                'point2_date': p2['date'],
                'above_line': today_price > p2['price'],
            }
    return up_line, down_line


# ============================================================
# 识别量柱形态（核心定义，保留官方）
# ============================================================
def identify_vol_pattern(df):
    if len(df) < 10:
        return "未知"
    today_vol = df.iloc[-1]['volume']
    yesterday_vol = df.iloc[-2]['volume']
    
    if yesterday_vol > 0 and today_vol / yesterday_vol >= BEISHU_RATIO:
        return "倍量柱"
    
    recent_20 = df.iloc[-GAOLIANG_LOOKBACK:] if len(df) >= GAOLIANG_LOOKBACK else df
    if today_vol == recent_20['volume'].max():
        return "高量柱"
    if today_vol == recent_20['volume'].min():
        return "低量柱"
    
    v1, v2, v3 = df.iloc[-3]['volume'], df.iloc[-2]['volume'], df.iloc[-1]['volume']
    if v1 < v2 < v3:
        return "梯量柱"
    if v1 > v2 > v3:
        return "缩量柱"
    
    recent_5_avg = df.iloc[-6:-1]['volume'].mean()
    if recent_5_avg > 0:
        diff_pct = abs(today_vol - recent_5_avg) / recent_5_avg
        if diff_pct <= PINGLIANG_TOLERANCE:
            return "平量柱"
    
    return "普通量柱"


# ============================================================
# 关键位量影响力判断
# ============================================================
def judge_key_vol_impact(df, key_vol, key_date):
    if key_vol is None or key_date is None:
        return "无关键位", 0, 0
    today_vol = df.iloc[-1]['volume']
    vol_ratio = today_vol / key_vol * 100
    key_idx = None
    for i in range(len(df)-1, -1, -1):
        if df.iloc[i]['date'] == key_date:
            key_idx = i
            break
    time_distance = len(df) - 1 - key_idx if key_idx else 0
    if vol_ratio >= IMPACT_VS_KEY_VOL_HIGH * 100:
        vol_impact = "强"
    elif vol_ratio >= IMPACT_VS_KEY_VOL_MID * 100:
        vol_impact = "中"
    else:
        vol_impact = "弱"
    if time_distance <= IMPACT_TIME_NEAR:
        time_impact = "近"
    elif time_distance <= IMPACT_TIME_MID:
        time_impact = "中"
    else:
        time_impact = "远"
    if vol_impact == "强" and time_impact == "近":
        impact = "强"
    elif vol_impact == "弱" and time_impact == "远":
        impact = "弱"
    else:
        impact = "中"
    return impact, vol_ratio, time_distance


# ============================================================
# 【王牌柱官方版·优先级搜索·基柱用量分位数】
# ============================================================
def find_pillars_official(df, lookback_days=60):
    if len(df) < lookback_days + GENERAL_CONFIRM_DAYS + 20:
        return "无", None, None, None
    
    recent_df = df.iloc[-lookback_days:]
    df_offset = len(df) - lookback_days
    
    marshals = []
    goldens = []
    generals = []
    
    for i in range(len(recent_df) - GENERAL_CONFIRM_DAYS - 1, 5, -1):
        row = recent_df.iloc[i]
        
        if row['close'] <= row['open']:
            continue
        
        if i < 20:
            continue
        start_idx = max(0, i - 20)
        vol_window = recent_df.iloc[start_idx:i]['volume']
        vol_pctl = (vol_window < row['volume']).sum() / len(vol_window)
        if vol_pctl < BASE_VOL_PCTL:
            continue
        
        future = recent_df.iloc[i+1:i+1+GENERAL_CONFIRM_DAYS]
        if len(future) < GENERAL_CONFIRM_DAYS:
            continue
        
        base_open = row['open']
        base_close = row['close']
        base_vol = row['volume']
        
        future_avg_close = future['close'].mean()
        if future_avg_close < base_open:
            continue
        
        future_last_vol = future.iloc[-1]['volume']
        if future_last_vol >= base_vol:
            continue
        
        is_golden = future_avg_close >= base_close
        
        if i > 0:
            prev_row = recent_df.iloc[i-1]
            is_gap_up = row['open'] > prev_row['high']
        else:
            is_gap_up = False
        
        df_idx = df_offset + i
        pillar = (row['date'], row['low'], df_idx)
        
        if is_golden and is_gap_up:
            marshals.append(pillar)
        elif is_golden:
            goldens.append(pillar)
        else:
            generals.append(pillar)
    
    if marshals:
        return "元帅柱", marshals[0][0], marshals[0][1], marshals[0][2]
    elif goldens:
        return "黄金柱", goldens[0][0], goldens[0][1], goldens[0][2]
    elif generals:
        return "将军柱", generals[0][0], generals[0][1], generals[0][2]
    else:
        return "无", None, None, None


# ============================================================
# 找凹口线
# ============================================================
def find_aokou_line(df, lookback_days=60):
    if len(df) < lookback_days:
        return None, None, None
    recent_df = df.iloc[-lookback_days:]
    vols = recent_df['volume'].values
    best_gap = None
    best_price = None
    best_date = None
    for gap in range(AOKOU_MIN_GAP, AOKOU_MAX_GAP + 1, 2):
        for i in range(gap, len(vols)):
            vol_left = vols[i - gap]
            vol_right = vols[i]
            vol_diff = abs(vol_left - vol_right) / max(vol_left, vol_right)
            if vol_diff > AOKOU_PINGLIANG_TOLERANCE:
                continue
            middle_vols = vols[i - gap + 1:i]
            if len(middle_vols) == 0:
                continue
            min_middle_vol = middle_vols.min()
            avg_side_vol = (vol_left + vol_right) / 2
            if min_middle_vol > avg_side_vol * AOKOU_MIDDLE_SHADOW:
                continue
            min_idx = i - gap + 1 + middle_vols.argmin()
            aokou_price = recent_df.iloc[min_idx]['low']
            aokou_date = recent_df.iloc[min_idx]['date']
            if best_gap is None or gap > best_gap:
                best_gap = gap
                best_price = aokou_price
                best_date = aokou_date
    if best_price:
        return best_price, best_date, best_gap
    else:
        return None, None, None


# ============================================================
# 识别所有形态信号
# ============================================================
def identify_all_signals(df, valley_price, safe_line, precise_price, big_yin_top, peak_20,
                         atr_pct, changyang_threshold, binglin_threshold, code):
    signals = []
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    today_open = today['open']
    today_close = today['close']
    today_high = today['high']
    today_low = today['low']
    today_vol = today['volume']
    yesterday_open = yesterday['open']
    yesterday_close = yesterday['close']
    yesterday_vol = yesterday['volume']
    
    today_vol_pctl = get_vol_percentile(df, VOL_LOOKBACK)
    
    if today_close > today_open and today_vol > yesterday_vol and today_close > yesterday_close:
        signals.append("阳胜进")
    if today_close < today_open and today_vol > yesterday_vol and today_close < yesterday_close:
        signals.append("阴胜出")
    
    body_pct = (today_close - today_open) / today_open * 100
    vol_ratio = today_vol / yesterday_vol if yesterday_vol > 0 else 0
    if 0 < body_pct < 3 and SMALL_BEISHU_MIN <= vol_ratio < SMALL_BEISHU_MAX:
        signals.append("小倍阳（矮将军）")
    
    body_size = abs(today_close - today_open)
    lower_shadow = min(today_open, today_close) - today_low
    touched_line = None
    if valley_price and abs(today_low - valley_price) / valley_price < TOUCH_LINE_TOLERANCE:
        touched_line = "谷底线"
    elif safe_line and abs(today_low - safe_line) / safe_line < TOUCH_LINE_TOLERANCE:
        touched_line = "安全线"
    elif precise_price and abs(today_low - precise_price) / precise_price < TOUCH_LINE_TOLERANCE:
        touched_line = "精准线"
    elif big_yin_top and abs(today_low - big_yin_top) / big_yin_top < TOUCH_LINE_TOLERANCE:
        touched_line = "大阴实顶线"
    
    if body_size > 0:
        lower_shadow_atr = lower_shadow / today_close * 100
        if atr_pct and lower_shadow_atr > atr_pct * LONG_LEG_ATR_MULT:
            if touched_line:
                signals.append(f"长腿踩线（{touched_line}）")
            else:
                signals.append("长腿（未踩线）")
        elif lower_shadow / body_size > 2.0:
            if touched_line:
                signals.append(f"长腿踩线（{touched_line}）")
            else:
                signals.append("长腿（未踩线）")
    
    body_pct_down = (today_open - today_close) / today_close * 100
    if body_pct_down > changyang_threshold and today_vol_pctl < LONG_YIN_SHORT_VOL_PCTL:
        signals.append("长阴短柱")
    
    if today_close > yesterday_open and today_open < yesterday_close and today_close > today_open:
        signals.append("阳包阴")
    if today_close < yesterday_open and today_open > yesterday_close and today_close < today_open:
        signals.append("阴包阳")
    
    gap_up_pct = (today_open - yesterday['high']) / yesterday['high'] * 100
    gap_down_pct = (yesterday['low'] - today_open) / yesterday['low'] * 100
    gap_threshold = atr_pct * GAP_ATR_MULT if atr_pct else 0.5
    if gap_up_pct > gap_threshold:
        signals.append("跳空高开")
    if gap_down_pct > gap_threshold:
        signals.append("跳空低开")
    
    today_range = today_high - today_low
    if today_range > 0 and body_size / today_range < 0.1:
        signals.append("十字星")
    
    if peak_20 and today_close > peak_20:
        signals.append("过左峰")
    
    if today_close < today_open and today_close > yesterday_close and today_vol > yesterday_vol:
        signals.append("假阴真阳")
    
    if len(df) >= JIYIN_PREV_DAYS:
        prev_5 = df.iloc[-JIYIN_PREV_DAYS:]
        for i in range(len(prev_5)-2, 0, -1):
            row = prev_5.iloc[i]
            drop_pct = (row['close'] - row['open']) / row['open'] * 100
            if drop_pct < changyang_threshold:
                if today_close > today_open:
                    yin_body_size = row['open'] - row['close']
                    rebound_size = today_close - row['close']
                    if yin_body_size > 0 and rebound_size / yin_body_size > CIYANG_REBOUND_PCT / 100:
                        signals.append("极阴次阳")
                break
    
    chongyang_up_pct = (today_close - yesterday_close) / yesterday_close * 100
    if chongyang_up_pct > changyang_threshold and today_vol_pctl < 0.5:
        signals.append("长阳矮柱")
    
    if len(df) >= NIUGU_LOOKBACK:
        recent_60 = df.iloc[-NIUGU_LOOKBACK:]
        for i in range(len(recent_60)-1, 5, -1):
            row = recent_60.iloc[i]
            prev_row = recent_60.iloc[i-1]
            if prev_row['volume'] > 0 and row['volume'] / prev_row['volume'] >= BEISHU_RATIO and row['close'] > row['open']:
                beiliang_bottom = row['open']
                future = recent_60.iloc[i+1:]
                if len(future) > 0 and all(future['low'] >= beiliang_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
                    signals.append("倍量不穿")
                break
    
    if len(df) >= NIUGU_LOOKBACK:
        recent_60 = df.iloc[-NIUGU_LOOKBACK:]
        max_vol_idx = recent_60['volume'].idxmax()
        max_vol_row = recent_60.loc[max_vol_idx]
        gaoliang_bottom = max_vol_row['low']
        future = recent_60.iloc[max_vol_idx + 1:]
        if len(future) > 0 and all(future['low'] >= gaoliang_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
            signals.append("高量不破")
    
    if len(df) >= 10:
        recent_10 = df.iloc[-10:]
        for i in range(len(recent_10)-1, 1, -1):
            row = recent_10.iloc[i]
            prev_row = recent_10.iloc[i-1]
            if row['open'] > prev_row['high']:
                gap_bottom = prev_row['high']
                future = recent_10.iloc[i+1:]
                if len(future) > 0 and all(future['low'] >= gap_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
                    signals.append("跳空不补")
                break
    
    if len(df) >= DILIANG_GROUP_DAYS:
        recent_100 = df.iloc[-DILIANG_GROUP_DAYS:]
        vol_low_pctl = recent_100['volume'].quantile(VOL_PCTL_LOW)
        low_vol_count = sum(recent_100['volume'] <= vol_low_pctl)
        if low_vol_count >= DILIANG_GROUP_COUNT:
            signals.append("地量群")
    
    if len(df) >= JIA_SHENG_LIANG_SUO_DAYS:
        recent_3 = df.iloc[-JIA_SHENG_LIANG_SUO_DAYS:]
        prices_up = all(recent_3.iloc[i]['close'] > recent_3.iloc[i-1]['close'] for i in range(1, len(recent_3)))
        vols_down = all(recent_3.iloc[i]['volume'] < recent_3.iloc[i-1]['volume'] for i in range(1, len(recent_3)))
        if prices_up and vols_down:
            signals.append("价升量缩")
    
    if precise_price and len(df) >= HUICAI_PRECISION_DAYS:
        recent_10 = df.iloc[-HUICAI_PRECISION_DAYS:]
        touched = any(abs(row['low'] - precise_price) / precise_price < TOUCH_LINE_TOLERANCE for _, row in recent_10.iterrows())
        if touched:
            signals.append("回踩精准线")
    
    upper_shadow = today_high - max(today_open, today_close)
    if body_size > 0:
        if upper_shadow / body_size > DOUBLE_SWORD_UPPER_RATIO and lower_shadow / body_size > DOUBLE_SWORD_LOWER_RATIO:
            signals.append("双剑霸天地")
    
    if len(df) >= SANYUAN_DAYS:
        recent_3 = df.iloc[-SANYUAN_DAYS:]
        prices_up = all(recent_3.iloc[i]['close'] > recent_3.iloc[i-1]['close'] for i in range(1, len(recent_3)))
        vols_down = all(recent_3.iloc[i]['volume'] < recent_3.iloc[i-1]['volume'] for i in range(1, len(recent_3)))
        if prices_up and vols_down:
            signals.append("三元连动")
    
    if peak_20:
        distance_to_peak = (peak_20 - today_close) / today_close * 100
        if 0 < distance_to_peak < binglin_threshold and today_close > today_open:
            signals.append("兵临城下")
    
    if len(df) >= DAYANG_DOUBLE_REST_DAYS:
        recent_5 = df.iloc[-DAYANG_DOUBLE_REST_DAYS:]
        for i in range(len(recent_5)-1, 0, -1):
            row = recent_5.iloc[i]
            body_pct_up = (row['close'] - row['open']) / row['open'] * 100
            if body_pct_up > changyang_threshold:
                yang_bottom = row['open']
                yang_mid = (yang_bottom + row['close']) / 2
                future = recent_5.iloc[i+1:]
                if len(future) > 0 and all(future['low'] >= yang_mid):
                    signals.append("大阳双休")
                break
    
    if len(df) >= JIELI_DOUBLE_YANG_GAP_MAX + 5:
        recent_30 = df.iloc[-30:]
        big_yangs = []
        for i in range(len(recent_30)):
            row = recent_30.iloc[i]
            body_pct_up = (row['close'] - row['open']) / row['open'] * 100
            if body_pct_up > changyang_threshold:
                big_yangs.append(i)
        if len(big_yangs) >= 2:
            gap = big_yangs[-1] - big_yangs[-2]
            if JIELI_DOUBLE_YANG_GAP_MIN <= gap <= JIELI_DOUBLE_YANG_GAP_MAX:
                signals.append("接力双阳")
    
    today_pct = (today_close - yesterday_close) / yesterday_close * 100
    limit_up_pct = LIMIT_UP_GEM if is_gem_star(code) else LIMIT_UP_MAIN
    if today_pct >= limit_up_pct:
        signals.append("涨停板")
    
    if len(df) >= BEISHUO_LOOKBACK:
        recent_5 = df.iloc[-BEISHUO_LOOKBACK:]
        vols_pctl = (recent_5['volume'].rank(pct=True)).values
        has_beishuo = False
        for i in range(1, len(vols_pctl)):
            if vols_pctl[i] >= BEISHUO_EXTEND_PCTL and vols_pctl[i-1] <= BEISHUO_SHRINK_PCTL:
                has_beishuo = True
                break
        if has_beishuo:
            signals.append("倍量伸缩")
    
    if len(df) >= GOLD_CROSS_LONG_MA + 1:
        ma5_today = df.iloc[-GOLD_CROSS_SHORT_MA:]['close'].mean()
        ma5_yesterday = df.iloc[-GOLD_CROSS_SHORT_MA-1:-1]['close'].mean()
        ma10_today = df.iloc[-GOLD_CROSS_LONG_MA:]['close'].mean()
        ma10_yesterday = df.iloc[-GOLD_CROSS_LONG_MA-1:-1]['close'].mean()
        vol_ma5_today = df.iloc[-GOLD_CROSS_VOL_SHORT:]['volume'].mean()
        vol_ma5_yesterday = df.iloc[-GOLD_CROSS_VOL_SHORT-1:-1]['volume'].mean()
        vol_ma10_today = df.iloc[-GOLD_CROSS_VOL_LONG:]['volume'].mean()
        vol_ma10_yesterday = df.iloc[-GOLD_CROSS_VOL_LONG-1:-1]['volume'].mean()
        price_cross = ma5_yesterday <= ma10_yesterday and ma5_today > ma10_today
        vol_cross = vol_ma5_yesterday <= vol_ma10_yesterday and vol_ma5_today > vol_ma10_today
        if price_cross and vol_cross:
            signals.append("黄金十字架")
    
    if peak_20 and valley_price and precise_price:
        near_peak = abs(precise_price - peak_20) / peak_20 < PRECISE_FENGGU_TOLERANCE
        near_valley = abs(precise_price - valley_price) / valley_price < PRECISE_FENGGU_TOLERANCE
        if near_peak and near_valley:
            signals.append("精准峰谷线")
    
    if len(df) >= XIANCHANG_ZHIBIE_DAYS:
        recent_10 = df.iloc[-XIANCHANG_ZHIBIE_DAYS:]
        high_max = recent_10['high'].max()
        low_min = recent_10['low'].min()
        amplitude = (high_max - low_min) / low_min
        first_half_avg = recent_10.iloc[:5]['volume'].mean()
        second_half_avg = recent_10.iloc[5:]['volume'].mean()
        if amplitude < XIANCHANG_ZHIBIE_AMPLITUDE and second_half_avg < first_half_avg * XIANCHANG_ZHIBIE_VOL:
            signals.append("现场直憋")
    
    if len(df) >= XUANYIN31_DAYS:
        recent_3 = df.iloc[-XUANYIN31_DAYS:]
        all_yin = all(recent_3.iloc[i]['close'] < recent_3.iloc[i]['open'] for i in range(len(recent_3)))
        vols_desc = all(recent_3.iloc[i]['volume'] < recent_3.iloc[i-1]['volume'] for i in range(1, len(recent_3)))
        if all_yin and vols_desc:
            signals.append("悬阴31")
    
    if len(df) >= T4_VARIANT_DAYS:
        recent_4 = df.iloc[-T4_VARIANT_DAYS:]
        day1_up_pct = (recent_4.iloc[0]['close'] - recent_4.iloc[0]['open']) / recent_4.iloc[0]['open'] * 100
        day2_down = recent_4.iloc[1]['close'] < recent_4.iloc[1]['open']
        day3_up = recent_4.iloc[2]['close'] > recent_4.iloc[2]['open']
        day4_up_pct = (recent_4.iloc[3]['close'] - recent_4.iloc[3]['open']) / recent_4.iloc[3]['open'] * 100
        if day1_up_pct > changyang_threshold and day2_down and day3_up and day4_up_pct > T4_VARIANT_UP_PCT:
            signals.append("T4变异")
    
    return signals


# ============================================================
# 生成综合解读
# ============================================================
def generate_interpretation(stock):
    sections = []
    
    main_intent = stock.get('main_intent', [])
    if main_intent:
        intent_lines = []
        for intent, color, desc in main_intent:
            intent_lines.append(f"🎯 {intent}：{desc}")
        
        advice_lines = []
        for intent, color, desc in main_intent:
            if "建仓" in intent or "吸筹" in intent:
                advice_lines.append("✅ 操作建议：可以逢低买入！")
            elif "洗盘" in intent:
                advice_lines.append("✅ 操作建议：可以加仓！")
            elif "拉升" in intent:
                advice_lines.append("✅ 操作建议：持有！")
            elif "出货" in intent or "出逃" in intent:
                advice_lines.append("🔴 操作建议：卖出！")
            elif "诱多" in intent:
                advice_lines.append("⚠️ 操作建议：不要追高！")
            else:
                advice_lines.append("⏸️ 操作建议：观望！")
        
        sections.append({
            'title': '【总结论】主力意图 + 操作建议',
            'content': intent_lines + advice_lines + [
                '<strong>怎么看的？</strong>：接下来我一步步给你拆解！'
            ]
        })
    
    market = stock.get('market_regime', '未知')
    vs_ma20 = stock.get('vs_ma20_pct', 0)
    if market == "多头市场":
        market_desc = f"上证指数在20日线上方{vs_ma20:+.1f}%，大盘走强！"
        market_logic = "大盘好的时候，大部分股票都能涨！顺风局！"
    elif market == "空头市场":
        market_desc = f"上证指数在20日线下方{vs_ma20:+.1f}%，大盘走弱！"
        market_logic = "大盘差的时候，大部分股票都难涨！逆风局！"
    else:
        market_desc = "大盘数据未知。"
        market_logic = "无法判断大盘环境。"
    
    sections.append({
        'title': '【第一步】天时：大盘环境怎么样？',
        'content': [
            f"📊 {market_desc}",
            f"<strong>市场机理</strong>：{market_logic}",
            "<strong>量学依据</strong>：大盘是水，个股是船！水涨船高，水落船低！"
        ]
    })
    
    position = stock.get('position', '未知')
    position_pct = stock.get('position_pct', 0)
    trend = stock.get('stock_trend', '未知')
    
    if position == "低位":
        pos_desc = f"股价在近120天的低位区域（{position_pct:.0f}%分位）"
        pos_logic = "低位意味着风险小，上涨空间大！主力最喜欢在低位建仓！"
    elif position == "中位":
        pos_desc = f"股价在近120天的中位区域（{position_pct:.0f}%分位）"
        pos_logic = "中位比较尴尬，要看主力意图！"
    else:
        pos_desc = f"股价在近120天的高位区域（{position_pct:.0f}%分位）"
        pos_logic = "高位意味着风险大，下跌空间大！主力最喜欢在高位出货！"
    
    if trend == "上升趋势":
        trend_desc = "均线多头排列，股价在均线上方！"
        trend_logic = "上升趋势说明主力在往上做！"
    else:
        trend_desc = "均线空头排列，股价在均线下方！"
        trend_logic = "下降趋势说明主力在往下做！"
    
    sections.append({
        'title': '【第二步】地利：股价在什么位置？趋势怎么样？',
        'content': [
            f"📍 位置：{pos_desc}",
            f"<strong>市场机理</strong>：{pos_logic}",
            f"\n📈 趋势：{trend_desc}",
            f"<strong>市场机理</strong>：{trend_logic}",
            "<strong>量学依据</strong>：位置决定风险！趋势决定方向！"
        ]
    })
    
    vol = stock.get('vol_pattern', '未知')
    pillar = stock.get('pillar_type', '无')
    
    sections.append({
        'title': '【第三步】人和：今天是什么量柱？有没有王牌柱？',
        'content': [
            f"📊 今日量柱：{vol}",
            f"👑 王牌柱：{pillar}",
            "<strong>市场机理</strong>：量柱是主力的脚印！王牌柱是主力留下的重要标记！",
            "<strong>量学依据</strong>：有王牌柱的股票才有主力！没王牌柱的股票没人管！"
        ]
    })
    
    vol_verdict = stock.get('vol_verdict', '未知')
    quant_pct = stock.get('quant_pct', 0)
    cv = stock.get('vol_cv', 0)
    corr = stock.get('vol_corr', 0)
    tail = stock.get('vol_tail', 0)
    
    if vol_verdict == "真金白银":
        vol_logic = "成交量忽大忽小，量价配合，是真金白银在交易！"
    elif vol_verdict == "量化对倒":
        vol_logic = "成交量太均匀，量价没关系，是量化机器在对倒！"
    else:
        vol_logic = "有一点量化，但不多！"
    
    sections.append({
        'title': '【第四步】去伪：这个量柱是真的还是假的？',
        'content': [
            f"🤖 量能判断：{vol_verdict}（估算占比{quant_pct:.0f}%）",
            f"📊 指标：CV={cv:.2f} · 量价相关={corr:.2f} · 尾盘占比={tail*100:.0f}%",
            f"<strong>市场机理</strong>：{vol_logic}",
            "<strong>量学依据</strong>：量化对倒出来的量柱是假的！真金白银的量柱才是真的！"
        ]
    })
    
    ace_line = stock.get('ace_line', 0)
    vs_ace = stock.get('vs_ace_pct', 0)
    divergence = stock.get('divergence', '')
    risks = stock.get('risks', [])
    
    extra_lines = []
    if ace_line:
        extra_lines.append(f"🛡️ 王牌线：{ace_line:.2f}元（当前{vs_ace:+.1f}%）")
    if divergence:
        extra_lines.append(f"⚠️ {divergence}")
    for risk in risks:
        extra_lines.append(f"⚠️ {risk}")
    
    if extra_lines:
        sections.append({
            'title': '【第五步】验证：其他信号确认',
            'content': extra_lines + [
                "<strong>量学依据</strong>：多一个信号确认，胜率就高一分！"
            ]
        })
    
    if main_intent:
        why_lines = []
        for intent, color, desc in main_intent:
            why_lines.append(f"为什么判断是<strong>{intent}</strong>？因为：{desc}")
        
        sections.append({
            'title': '【第六步】为什么得出这个结论？',
            'content': why_lines + [
                "<strong>推理逻辑</strong>：天时（大盘）+ 地利（位置趋势）+ 人和（量柱王牌柱）+ 去伪（真假量柱）= 主力意图！",
                "<strong>量学依据</strong>：四维循环看盘法，就是从这四个维度综合判断！"
            ]
        })
    
    if stock['big_yin_top']:
        above_text = "上方" if bool(stock['price_above_yintop']) else "下方"
        pct_text = f"{stock['price_vs_yintop_pct']:+.2f}%"
        if bool(stock['price_above_yintop']):
            conclusion = "说明买方已经把那天卖方的成果抢回来了，买方在这个区间占优。"
        else:
            conclusion = "说明买方还没能收复那天卖方的失地，卖方在这个区间仍占优。"
        sections.append({
            'title': '【补充】大阴实顶的市场意义',
            'content': [
                f"大阴实顶发生在{stock['days_since_yin']}天前（{stock['big_yin_date']}），价格{stock['big_yin_top']:.2f}元。",
                '<strong>市场机理</strong>：这是多空双方上次「休战」的警戒点。',
                f'<strong>推导</strong>：现在价格在大阴实顶<strong>{above_text}</strong> {pct_text}，{conclusion}',
                '<strong>量学依据</strong>：大阴实顶是回形针看盘法的起点。'
            ]
        })
    else:
        sections.append({
            'title': '【补充】大阴实顶的市场意义',
            'content': [
                '近60日没有出现中大阴线。',
                '<strong>市场机理</strong>：说明近期没有明显的多空大战分界线。',
                '<strong>量学依据</strong>：没有大阴实顶，说明多空双方还没有进行过大规模决战。'
            ]
        })
    
    return sections


# ============================================================
# 生成单只股票数据
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
    
    atr_value, atr_pct = calculate_atr(df, ATR_PERIOD)
    
    yin_body_threshold = get_atr_threshold(atr_pct, YIN_BODY_ATR_MULT, YIN_BODY_FALLBACK)
    changyang_threshold = get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK)
    binglin_threshold = get_atr_threshold(atr_pct, BINGLIN_ATR_MULT, BINGLIN_FALLBACK)
    
    big_yin_top, big_yin_bottom, big_yin_date, big_yin_vol, big_yin_idx = find_big_yin_top(
        df, YIN_LOOKBACK, yin_body_threshold
    )
    
    if big_yin_top:
        price_vs_yintop_pct = (today_price - big_yin_top) / big_yin_top * 100
        price_above_yintop = bool(price_vs_yintop_pct > 0)
    else:
        price_vs_yintop_pct = 0
        price_above_yintop = None
    
    if big_yin_idx:
        period_df = df.iloc[big_yin_idx:]
        yang_count = int(sum(period_df['close'] > period_df['open']))
        yin_count = int(sum(period_df['close'] < period_df['open']))
        yang_yin_ratio = yang_count / max(yin_count, 1)
    else:
        yang_count = 0
        yin_count = 0
        yang_yin_ratio = 0
    
    recent_20 = df.iloc[-SHORT_WINDOW:]
    recent_high = recent_20['high'].max()
    recent_low = recent_20['low'].min()
    
    if big_yin_vol:
        big_yin_idx_in_df = None
        for i in range(len(df)):
            if df.iloc[i]['date'] == big_yin_date:
                big_yin_idx_in_df = i
                break
        if big_yin_idx_in_df and big_yin_idx_in_df >= 20:
            vol_window = df.iloc[big_yin_idx_in_df-20:big_yin_idx_in_df]['volume']
            yin_vol_pctl = (vol_window < big_yin_vol).sum() / len(vol_window)
            if yin_vol_pctl >= VOL_PCTL_HIGH:
                yin_vol_size = "大量"
            elif yin_vol_pctl <= VOL_PCTL_LOW:
                yin_vol_size = "小量"
            else:
                yin_vol_size = "平量"
        else:
            yin_vol_size = "未知"
    else:
        yin_vol_size = "未知"
    
    if big_yin_idx:
        days_since_yin = len(df) - 1 - big_yin_idx
    else:
        days_since_yin = 0
    
    if big_yin_vol:
        today_vs_yin_vol = today_volume / big_yin_vol * 100
    else:
        today_vs_yin_vol = 0
    
    if days_since_yin <= IMPACT_TIME_NEAR:
        time_impact = "很近（影响力强）"
    elif days_since_yin <= IMPACT_TIME_MID:
        time_impact = "中等（影响力一般）"
    else:
        time_impact = "很远（影响力弱）"
    
    vol_high_20 = recent_20['volume'].max()
    vol_low_20 = recent_20['volume'].min()
    vol_pos_20 = (today_volume - vol_low_20) / (vol_high_20 - vol_low_20) * 100
    if vol_pos_20 > VOL_POS_HIGH:
        vol_length = "长量柱（天量）"
    elif vol_pos_20 < VOL_POS_LOW:
        vol_length = "短量柱（地量）"
    else:
        vol_length = "中等量柱"
    
    today_range = today['high'] - today['low']
    today_range_pct = today_range / today_price * 100
    long_range_threshold = get_atr_threshold(atr_pct, LONG_RANGE_ATR_MULT, 3.0)
    short_range_threshold = get_atr_threshold(atr_pct, SHORT_RANGE_ATR_MULT, 1.0)
    if atr_pct and today_range_pct > long_range_threshold:
        price_length = "长价柱（振幅大）"
    elif atr_pct and today_range_pct < short_range_threshold:
        price_length = "短价柱（振幅小）"
    else:
        price_length = "中等价柱"
    
    body_size = abs(today['close'] - today['open'])
    body_ratio = body_size / today_range * 100 if today_range > 0 else 0
    if body_ratio > BODY_RATIO_LONG * 100:
        body_length = "长实体"
    elif body_ratio < BODY_RATIO_SHORT * 100:
        body_length = "短实体（十字星）"
    else:
        body_length = "中等实体"
    
    safe_20, risk_20, type_20, date_20, key_vol_20 = find_gaoliang_lines(recent_20)
    
    safe_60 = risk_60 = type_60 = date_60 = key_vol_60 = None
    recent_60 = df.iloc[-MID_WINDOW:] if len(df) > MID_WINDOW else None
    if recent_60 is not None:
        safe_60, risk_60, type_60, date_60, key_vol_60 = find_gaoliang_lines(recent_60)
    
    safe_120 = risk_120 = type_120 = date_120 = key_vol_120 = None
    recent_120 = df.iloc[-LONG_WINDOW:] if len(df) > LONG_WINDOW else None
    if recent_120 is not None:
        safe_120, risk_120, type_120, date_120, key_vol_120 = find_gaoliang_lines(recent_120)
    
    balance_price, balance_date = find_balance_line(df, BALANCE_LOOKBACK, yin_body_threshold)
    precise_lines = find_precise_lines(df, PRECISE_LOOKBACK, PRECISE_MIN_POINTS, PRECISE_PRICE_TOLERANCE)
    
    peak_20, peak_date_20, valley_20, valley_date_20, peaks_20, valleys_20 = find_fenggu_lines(
        df, SHORT_WINDOW, PEAK_SIDE_SHORT, CONFIRM_DAYS_SHORT, VOL_PERCENTILE
    )
    
    peak_60 = peak_date_60 = valley_60 = valley_date_60 = None
    peaks_60 = []
    valleys_60 = []
    if len(df) >= MID_WINDOW + CONFIRM_DAYS_MID + PEAK_SIDE_MID:
        peak_60, peak_date_60, valley_60, valley_date_60, peaks_60, valleys_60 = find_fenggu_lines(
            df, MID_WINDOW, PEAK_SIDE_MID, CONFIRM_DAYS_MID, VOL_PERCENTILE
        )
    
    peak_120 = peak_date_120 = valley_120 = valley_date_120 = None
    peaks_120 = []
    valleys_120 = []
    if len(df) >= LONG_WINDOW + CONFIRM_DAYS_LONG + PEAK_SIDE_LONG:
        peak_120, peak_date_120, valley_120, valley_date_120, peaks_120, valleys_120 = find_fenggu_lines(
            df, LONG_WINDOW, PEAK_SIDE_LONG, CONFIRM_DAYS_LONG, VOL_PERCENTILE
        )
    
    up_line, down_line = find_xieheng_line(peaks_120, valleys_120, today_price)
    vol_pattern = identify_vol_pattern(df)
    impact_20, vol_ratio_20, time_dist_20 = judge_key_vol_impact(df, key_vol_20, date_20)
    
    pillar_type, pillar_date, golden_line, pillar_idx = find_pillars_official(df)
    
    aokou_price, aokou_date, aokou_gap = find_aokou_line(df)
    
    precise_price = precise_lines[0]['price'] if precise_lines else None
    full_code = f"{market}{code}"
    extra_signals = identify_all_signals(
        df, valley_20, safe_20, precise_price, big_yin_top, peak_20,
        atr_pct, changyang_threshold, binglin_threshold, full_code
    )
    
    short_dist_high = (recent_high - today_price) / today_price * 100
    short_dist_low = (today_price - recent_low) / today_price * 100
    
    mid_high = mid_low = None
    mid_dist_high = mid_dist_low = None
    if recent_60 is not None:
        mid_high = recent_60['high'].max()
        mid_low = recent_60['low'].min()
        mid_dist_high = (mid_high - today_price) / today_price * 100
        mid_dist_low = (today_price - mid_low) / today_price * 100
    
    long_high = long_low = None
    long_dist_high = long_dist_low = None
    if recent_120 is not None:
        long_high = recent_120['high'].max()
        long_low = recent_120['low'].min()
        long_dist_high = (long_high - today_price) / today_price * 100
        long_dist_low = (today_price - long_low) / today_price * 100
    
    pos_120 = (today_price - long_low) / (long_high - long_low) * 100 if long_high else 50
    if pos_120 > POSITION_HIGH:
        pos_status = "高位"
    elif pos_120 < POSITION_LOW:
        pos_status = "低位"
    else:
        pos_status = "中位"
    
    power = "买方占优" if today['close'] > today['open'] else "卖方占优"
    
    pct_3d = (today['close'] - df.iloc[-4]['close']) / df.iloc[-4]['close'] * 100
    pct_5d = (today['close'] - df.iloc[-6]['close']) / df.iloc[-6]['close'] * 100
    
    stock_data = {
        'name': name,
        'code': full_code,
        'date': today['date'],
        'close': today_price,
        'pct_chg': pct_chg,
        'atr_pct': atr_pct,
        'yin_body_threshold': yin_body_threshold,
        'big_yin_top': big_yin_top,
        'big_yin_date': big_yin_date,
        'big_yin_vol': big_yin_vol,
        'price_above_yintop': price_above_yintop,
        'price_vs_yintop_pct': price_vs_yintop_pct,
        'yang_count': yang_count,
        'yin_count': yin_count,
        'yang_yin_ratio': yang_yin_ratio,
        'recent_high': recent_high,
        'recent_low': recent_low,
        'yin_vol_size': yin_vol_size,
        'days_since_yin': days_since_yin,
        'today_vs_yin_vol': today_vs_yin_vol,
        'time_impact': time_impact,
        'vol_pos_20': vol_pos_20,
        'vol_length': vol_length,
        'price_length': price_length,
        'body_length': body_length,
        'body_ratio': body_ratio,
        'safe_20': safe_20,
        'risk_20': risk_20,
        'date_20': date_20,
        'safe_60': safe_60,
        'risk_60': risk_60,
        'date_60': date_60,
        'safe_120': safe_120,
        'risk_120': risk_120,
        'date_120': date_120,
        'balance_price': balance_price,
        'balance_date': balance_date,
        'precise_lines': precise_lines,
        'up_line': up_line,
        'down_line': down_line,
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
        'vol_pattern': vol_pattern,
        'impact_20': impact_20,
        'vol_ratio_20': vol_ratio_20,
        'short_dist_high': short_dist_high,
        'short_dist_low': short_dist_low,
        'mid_high': mid_high,
        'mid_low': mid_low,
        'mid_dist_high': mid_dist_high,
        'mid_dist_low': mid_dist_low,
        'long_high': long_high,
        'long_low': long_low,
        'long_dist_high': long_dist_high,
        'long_dist_low': long_dist_low,
        'pos_status': pos_status,
        'power': power,
        'pct_3d': pct_3d,
        'pct_5d': pct_5d,
        'pillar_type': pillar_type,
        'pillar_date': pillar_date,
        'golden_line': golden_line,
        'pillar_idx': pillar_idx,
        'aokou_price': aokou_price,
        'aokou_date': aokou_date,
        'aokou_gap': aokou_gap,
        'extra_signals': extra_signals,
    }
    
    market_regime, vs_ma20_pct = get_market_regime()
    stock_data['market_regime'] = market_regime
    stock_data['vs_ma20_pct'] = vs_ma20_pct
    
    position, position_pct = get_position_level(df)
    stock_trend = get_stock_trend(df)
    stock_data['position'] = position
    stock_data['position_pct'] = position_pct
    stock_data['stock_trend'] = stock_trend
    
    vol_verdict, vol_cv, vol_corr, vol_tail, quant_pct = analyze_1min_volatility(market + code)
    stock_data['vol_verdict'] = vol_verdict
    stock_data['vol_cv'] = vol_cv
    stock_data['vol_corr'] = vol_corr
    stock_data['vol_tail'] = vol_tail
    stock_data['quant_pct'] = quant_pct
    
    if vol_verdict == "真金白银":
        is_real = True
    elif vol_verdict == "量化对倒":
        is_real = False
    else:
        is_real = None
    
    signals_with_effectiveness = []
    for sig in extra_signals:
        winrate, effectiveness = get_signal_effectiveness(sig, position, stock_trend, is_real)
        
        score = 50
        score_details = []
        
        if position == "低位":
            score += 15
            score_details.append("低位+15")
        elif position == "中位":
            score += 5
            score_details.append("中位+5")
        else:
            score -= 5
            score_details.append("高位-5")
        
        if stock_trend == "上升趋势":
            score += 15
            score_details.append("上升+15")
        else:
            score -= 5
            score_details.append("下降-5")
        
        if stock_data.get('market_regime') == "多头市场":
            score += 10
            score_details.append("多头+10")
        elif stock_data.get('market_regime') == "空头市场":
            score -= 5
            score_details.append("空头-5")
        
        pillar_type = stock_data.get('pillar_type', '')
        if pillar_type == "元帅柱":
            score += 15
            score_details.append("元帅柱+15")
        elif pillar_type == "黄金柱":
            score += 10
            score_details.append("黄金柱+10")
        elif pillar_type == "将军柱":
            score += 5
            score_details.append("将军柱+5")
        
        if vol_pattern == "倍量柱":
            score += 10
            score_details.append("倍量+10")
        elif vol_pattern == "平量柱":
            score += 5
            score_details.append("平量+5")
        elif vol_pattern == "缩量柱":
            score += 0
            score_details.append("缩量+0")
        
        if effectiveness == "有效":
            score += 10
            score_details.append("有效+10")
        elif effectiveness == "无效":
            score -= 10
            score_details.append("无效-10")
        
        vol_verdict = stock_data.get('vol_verdict', '')
        if vol_verdict == "量化对倒":
            score -= 20
            score_details.append("量化对倒-20")
        elif vol_verdict == "疑似量化":
            score -= 10
            score_details.append("疑似量化-10")
        elif vol_verdict == "真金白银":
            score += 5
            score_details.append("真金白银+5")
        
        stars = min(5, max(1, round(score / 20)))
        
        signals_with_effectiveness.append({
            'name': sig,
            'winrate': winrate,
            'effectiveness': effectiveness,
            'score': score,
            'stars': stars,
            'score_details': score_details
        })
    
    stock_data['signals_with_effectiveness'] = signals_with_effectiveness
    
    resonance = ""
    if position == "低位" and stock_trend == "上升趋势" and stock_data.get('market_regime') == "多头市场":
        resonance = "✅ 最佳买点！低位+上升+多头"
    elif position == "高位" and stock_trend == "下降趋势" and stock_data.get('market_regime') == "空头市场":
        resonance = "❌ 最佳卖点！高位+下降+空头"
    elif position == "低位" and stock_trend == "上升趋势":
        resonance = "📈 较好买点！低位+上升"
    elif position == "高位" and stock_trend == "下降趋势":
        resonance = "📉 较好卖点！高位+下降"
    stock_data['resonance'] = resonance
    
    chips_verdict, latest_holders, holders_change = get_shareholder_chips(code)
    stock_data['chips_verdict'] = chips_verdict
    stock_data['latest_holders'] = latest_holders
    stock_data['holders_change'] = holders_change
    
    main_cost, vs_cost_pct = calc_main_cost(df)
    stock_data['main_cost'] = main_cost
    stock_data['vs_cost_pct'] = vs_cost_pct
    
    lhb_reason, lhb_amount = get_lhb_info(market + code)
    stock_data['lhb_reason'] = lhb_reason
    stock_data['lhb_amount'] = lhb_amount
    
    margin_balance, margin_label = get_margin_info(market + code)
    stock_data['margin_balance'] = margin_balance
    stock_data['margin_label'] = margin_label
    
    north_hold, north_label = get_north_info(market + code)
    stock_data['north_hold'] = north_hold
    stock_data['north_label'] = north_label
    
    restricted_date, restricted_amount = get_restricted_info(market + code)
    stock_data['restricted_date'] = restricted_date
    stock_data['restricted_amount'] = restricted_amount
    
    weekly_signal, weekly_desc = get_weekly_resonance(df)
    stock_data['weekly_signal'] = weekly_signal
    stock_data['weekly_desc'] = weekly_desc
    
    ace_line, vs_ace_pct, ace_type = get_ace_lines(df, stock_data.get('pillar_type'), stock_data.get('pillar_idx'))
    stock_data['ace_line'] = ace_line
    stock_data['vs_ace_pct'] = vs_ace_pct
    stock_data['ace_type'] = ace_type
    
    price_pattern = identify_price_pattern(df)
    stock_data['price_pattern'] = price_pattern
    
    combined_signals = get_combined_signals(df, vol_pattern, peak_20)
    stock_data['combined_signals'] = combined_signals
    
    fenggu_line = get_fenggu_line(peaks_60, valleys_60)
    stock_data['fenggu_line'] = fenggu_line
    
    divergence = get_volume_price_divergence(df)
    stock_data['divergence'] = divergence
    
    risks = get_risk_signals(position, stock_trend, vol_pattern)
    stock_data['risks'] = risks
    
    ao_kou = get_ao_kou(df)
    stock_data['ao_kou'] = ao_kou
    
    san_yin = get_san_yin(df)
    stock_data['san_yin'] = san_yin
    
    main_intent = get_main_force_intent(position, stock_trend, vol_pattern, 
                                        stock_data.get('pillar_type', ''), 
                                        stock_data.get('vol_verdict', ''),
                                        stock_data.get('price_pattern', ''))
    stock_data['main_intent'] = main_intent
    
    stock_data['interpretations'] = generate_interpretation(stock_data)
    
    return stock_data


# ============================================================
# 生成HTML
# ============================================================
def generate_html(stocks_data, today_str):
    items = []
    
    # ========== 新增：加载 AI 研判数据 ==========
    ai_comments = {}
    ai_path = OUTPUT_DIR / f"ai_comment_{today_str.replace('-', '')}.json"
    if ai_path.exists():
        try:
            with open(ai_path, 'r', encoding='utf-8') as f:
                ai_data = json.load(f)
            ai_comments = ai_data.get('stocks', {})
            print(f"  [AI研判] 已加载 {len(ai_comments)} 只股票的 AI 分析")
        except Exception as e:
            print(f"  [AI研判] 读取失败: {e}")
    else:
        print(f"  [AI研判] 未找到 {ai_path}，跳过 AI 研判渲染")
    # ============================================

    for stock in stocks_data:
        if stock is None:
            continue
        
        price_class = "price-up" if stock['pct_chg'] > 0 else "price-down"
        
        if stock['big_yin_top']:
            yintop_text = f"{stock['big_yin_top']:.2f}（{stock['big_yin_date']}）"
        else:
            yintop_text = "无（近60日无中大阴线）"
        
        if stock['price_above_yintop'] is None:
            yintop_status = "未知"
            yintop_color = "#94a3b8"
        elif bool(stock['price_above_yintop']):
            yintop_status = "上方（强势）"
            yintop_color = "#ef4444"
        else:
            yintop_status = "下方（弱势）"
            yintop_color = "#22c55e"
        
        precise_html = ""
        if stock['precise_lines']:
            for i, line in enumerate(stock['precise_lines']):
                precise_html += f"""
                <div class="grid-item">
                    <div class="label">精准线{i+1}（{line['points']}点）</div>
                    <div class="value">{line['price']:.2f}（{line['first_date']}~{line['last_date']}）</div>
                </div>
                """
        else:
            precise_html = """
            <div class="grid-item">
                <div class="label">精准线</div>
                <div class="value value-none">无</div>
            </div>
            """
        
        def peak_html(label, price, date):
            if price is not None and date is not None:
                return f"""
                <div class="grid-item">
                    <div class="label">{label}</div>
                    <div class="value">{price:.2f}（{date}）</div>
                </div>
                """
            else:
                return f"""
                <div class="grid-item">
                    <div class="label">{label}</div>
                    <div class="value value-none value-strong">无（寻顶中·偏强）</div>
                </div>
                """
        
        def valley_html(label, price, date):
            if price is not None and date is not None:
                return f"""
                <div class="grid-item">
                    <div class="label">{label}</div>
                    <div class="value">{price:.2f}（{date}）</div>
                </div>
                """
            else:
                return f"""
                <div class="grid-item">
                    <div class="label">{label}</div>
                    <div class="value value-none value-weak">无（寻底中·偏弱）</div>
                </div>
                """
        
        if stock['pillar_type'] == "元帅柱":
            pillar_html = f"""
            <div class="grid-item" style="border:2px solid #fbbf24;">
                <div class="label">👑 元帅柱</div>
                <div class="value" style="color:#fbbf24;">{stock['pillar_date']}</div>
            </div>
            """
        elif stock['pillar_type'] == "黄金柱":
            pillar_html = f"""
            <div class="grid-item" style="border:2px solid #fbbf24;">
                <div class="label">⭐ 黄金柱</div>
                <div class="value" style="color:#fbbf24;">{stock['pillar_date']}</div>
            </div>
            """
        elif stock['pillar_type'] == "将军柱":
            pillar_html = f"""
            <div class="grid-item" style="border:2px solid #60a5fa;">
                <div class="label">将军柱</div>
                <div class="value" style="color:#60a5fa;">{stock['pillar_date']}</div>
            </div>
            """
        else:
            pillar_html = """
            <div class="grid-item">
                <div class="label">王牌柱</div>
                <div class="value value-none">无</div>
            </div>
            """
        
        if stock['aokou_price']:
            aokou_html = f"""
            <div class="grid-item" style="border:2px solid #a78bfa;">
                <div class="label">🎯 凹口线</div>
                <div class="value" style="color:#a78bfa;">{stock['aokou_price']:.2f}（{stock['aokou_date']}，间隔{stock['aokou_gap']}天）</div>
            </div>
            """
        else:
            aokou_html = """
            <div class="grid-item">
                <div class="label">凹口线</div>
                <div class="value value-none">无</div>
            </div>
            """
        
        extra_html = ""
        if stock.get('signals_with_effectiveness'):
            for sig_info in stock['signals_with_effectiveness']:
                sig_name = sig_info['name']
                winrate = sig_info['winrate']
                effectiveness = sig_info['effectiveness']
                score = sig_info.get('score', 50)
                stars = sig_info.get('stars', 3)
                if effectiveness == "有效":
                    badge_color = "#22c55e"
                    badge_text = "✅"
                elif effectiveness == "一般":
                    badge_color = "#eab308"
                    badge_text = "⚠️"
                elif effectiveness == "无效":
                    badge_color = "#ef4444"
                    badge_text = "❌"
                else:
                    badge_color = "#60a5fa"
                    badge_text = ""
                
                stars_text = "⭐" * stars
                
                if winrate is not None:
                    vol_verdict = stock.get('vol_verdict', '')
                    fake_badge = ""
                    if vol_verdict == "量化对倒":
                        fake_badge = " <span style='color:#ef4444;'>⚠️假信号</span>"
                    elif vol_verdict == "真金白银":
                        fake_badge = " <span style='color:#22c55e;'>✅真金</span>"
                    extra_html += f'<span style="display:inline-block; background:{badge_color}20; color:{badge_color}; padding:4px 8px; border-radius:4px; font-size:11px; margin:2px; border:1px solid {badge_color};">{sig_name} {badge_text}{fake_badge}<br><span style="font-size:10px;">胜率{winrate:.1f}% · {stars_text}</span></span>'
                else:
                    extra_html += f'<span style="display:inline-block; background:#fbbf24; color:#000; padding:2px 8px; border-radius:4px; font-size:11px; margin:2px;">{sig_name}</span>'
        else:
            extra_html = '<span style="color:#94a3b8; font-size:12px;">无</span>'
        
        interp_html = ""
        for section in stock['interpretations']:
            interp_html += f"""
            <div style="margin-bottom: 12px; padding: 10px; background: #0f172a; border-radius: 8px; border-left: 3px solid #fbbf24;">
                <div style="font-weight: bold; color: #fbbf24; margin-bottom: 6px; font-size: 13px;">{section['title']}</div>
            """
            for line in section['content']:
                interp_html += f'                <p style="margin: 4px 0; font-size: 12px; color: #cbd5e1; line-height: 1.7;">{line}</p>\n'
            interp_html += """            </div>"""
        
        atr_text = f"{stock['atr_pct']:.2f}%" if stock['atr_pct'] else "未知"
        yin_thresh_text = f"{stock['yin_body_threshold']:.2f}%" if stock.get('yin_body_threshold') else "未知"
        
        if stock.get('stock_trend') == "上升趋势" and stock.get('position') in ["中位", "低位"]:
            pos_trend_color = "#22c55e"
            pos_trend_text = "✅ 黄金组合！信号胜率高"
        elif stock.get('stock_trend') == "下降趋势":
            pos_trend_color = "#ef4444"
            pos_trend_text = "❌ 下降趋势，谨慎操作"
        elif stock.get('position') == "高位":
            pos_trend_color = "#f97316"
            pos_trend_text = "⚠️ 高位，注意风险"
        else:
            pos_trend_color = "#eab308"
            pos_trend_text = "⚠️ 一般，轻仓试错"

        # ========== 新增：提取当前股票的 AI 研判 ==========
        ai_comment_text = ai_comments.get(stock['code'], {}).get('ai_comment', '')
        ai_html = ""
        if ai_comment_text and "未配置" not in ai_comment_text and "失败" not in ai_comment_text:
            ai_html = f'''
            <div style="background:#8b5cf620; border-radius:8px; padding:12px; margin-bottom:15px; border-left:4px solid #8b5cf6;">
                <div style="font-size:14px; font-weight:bold; color:#8b5cf6;">
                    🤖 AI 研判（Agnes AI）
                </div>
                <div style="font-size:12px; color:#cbd5e1; margin-top:4px; line-height: 1.6;">
                    {ai_comment_text}
                </div>
            </div>
            '''
        # ====================================================
        
        item_html = f"""
        <div class="stock-card">
            <div class="stock-header">
                <div>
                    <div class="stock-name">{stock['name']}</div>
                    <div class="stock-code">{stock['code']}</div>
                </div>
                <div class="stock-price {price_class}">{stock['close']:.2f}元 ({stock['pct_chg']:+.2f}%)</div>
            </div>
            
            <!-- 新增：主力意图识别（最重要！放最前面！） -->
            {''.join([f'''
            <div style="background:{color}20; border-radius:8px; padding:12px; margin-bottom:10px; border-left:4px solid {color};">
                <div style="font-size:16px; font-weight:bold; color:{color};">
                    🎯 主力意图：{intent}
                </div>
                <div style="font-size:12px; color:{color}; margin-top:2px;">
                    {desc}
                </div>
            </div>
            ''' for intent, color, desc in stock.get('main_intent', [])])}

            {ai_html}
            
            <!-- 新增：大盘环境 -->
            {f'''
            <div style="background:{'#10b981' if stock['market_regime'] == '多头市场' else '#ef4444'}20; border-radius:8px; padding:10px; margin-bottom:10px; border-left:4px solid {'#10b981' if stock['market_regime'] == '多头市场' else '#ef4444'};">
                <div style="font-size:14px; font-weight:bold; color:{'#10b981' if stock['market_regime'] == '多头市场' else '#ef4444'};">
                    🏛️ 大盘环境：{stock['market_regime']}
                </div>
                <div style="font-size:12px; color:{'#10b981' if stock['market_regime'] == '多头市场' else '#ef4444'}; margin-top:2px;">
                    上证指数{stock['vs_ma20_pct']:+.1f}%（vs 20日线）
                </div>
            </div>
            ''' if stock.get('market_regime') and stock['market_regime'] != '未知' else ''}
            
            <!-- 新增：位置+趋势总览 -->
            <div style="background:{pos_trend_color}20; border-radius:8px; padding:12px; margin-bottom:15px; border-left:4px solid {pos_trend_color};">
                <div style="font-size:16px; font-weight:bold; color:{pos_trend_color};">
                    📊 {stock['position']}（{stock['position_pct']:.0f}%分位）· {stock['stock_trend']}
                </div>
                <div style="font-size:13px; color:{pos_trend_color}; margin-top:4px;">
                    {pos_trend_text}
                </div>
            </div>
            
            <!-- 新增：三维共振提示 -->
            {f'''
            <div style="background:{'#22c55e' if '最佳买点' in stock.get('resonance', '') or '较好买点' in stock.get('resonance', '') else '#ef4444' if '最佳卖点' in stock.get('resonance', '') or '较好卖点' in stock.get('resonance', '') else '#60a5fa'}20; border-radius:8px; padding:10px; margin-bottom:10px; border-left:4px solid {'#22c55e' if '最佳买点' in stock.get('resonance', '') or '较好买点' in stock.get('resonance', '') else '#ef4444' if '最佳卖点' in stock.get('resonance', '') or '较好卖点' in stock.get('resonance', '') else '#60a5fa'};">
                <div style="font-size:14px; font-weight:bold; color:{'#22c55e' if '最佳买点' in stock.get('resonance', '') or '较好买点' in stock.get('resonance', '') else '#ef4444' if '最佳卖点' in stock.get('resonance', '') or '较好卖点' in stock.get('resonance', '') else '#60a5fa'};">
                    {stock['resonance']}
                </div>
            </div>
            ''' if stock.get('resonance') else ''}
            
            <!-- 新增：量化对倒判断 -->
            {f'''
            <div style="background:#ef444420; border-radius:8px; padding:10px; margin-bottom:10px; border-left:4px solid #ef4444;">
                <div style="font-size:14px; font-weight:bold; color:#ef4444;">
                    ⚠️ 今日量能：{stock['vol_verdict']}（估算占比{stock['quant_pct']:.0f}%）
                </div>
                <div style="font-size:12px; color:#ef4444; margin-top:2px;">
                    CV={stock['vol_cv']:.2f} · 量价相关={stock['vol_corr']:.2f} · 尾盘占比={stock['vol_tail']*100:.0f}%
                </div>
            </div>
            ''' if stock.get('vol_verdict') else ''}
            
            <!-- 新增：筹码集中/分散 -->
            {f'''
            <div style="background:#60a5fa20; border-radius:8px; padding:10px; margin-bottom:10px; border-left:4px solid #60a5fa;">
                <div style="font-size:14px; font-weight:bold; color:#60a5fa;">
                    👥 筹码：{stock['chips_verdict']}
                </div>
                <div style="font-size:12px; color:#60a5fa; margin-top:2px;">
                    股东户数{stock['holders_change']:+.1f}%
                </div>
            </div>
            ''' if stock.get('chips_verdict') else ''}
            
            <!-- 新增：主力成本区 -->
            {f'''
            <div style="background:#a78bfa20; border-radius:8px; padding:10px; margin-bottom:15px; border-left:4px solid #a78bfa;">
                <div style="font-size:14px; font-weight:bold; color:#a78bfa;">
                    💰 主力成本区：{stock['main_cost']:.2f}元
                </div>
                <div style="font-size:12px; color:#a78bfa; margin-top:2px;">
                    当前价格{stock['vs_cost_pct']:+.1f}%（60日VWAP）
                </div>
            </div>
            ''' if stock.get('main_cost') else ''}
            
            <!-- 新增：龙虎榜 -->
            {f'''
            <div style="background:#f59e0b20; border-radius:8px; padding:10px; margin-bottom:10px; border-left:4px solid #f59e0b;">
                <div style="font-size:14px; font-weight:bold; color:#f59e0b;">
                    🐉 龙虎榜：{stock['lhb_reason']}
                </div>
            </div>
            ''' if stock.get('lhb_reason') else ''}
            
            <!-- 新增：融资融券 -->
            {f'''
            <div style="background:#06b6d420; border-radius:8px; padding:10px; margin-bottom:10px; border-left:4px solid #06b6d4;">
                <div style="font-size:14px; font-weight:bold; color:#06b6d4;">
                    💰 {stock['margin_label']}：{stock['margin_balance']/1e8:.1f}亿
                </div>
            </div>
            ''' if stock.get('margin_balance') else ''}
            
            <!-- 新增：北向资金 -->
            {f'''
            <div style="background:#10b98120; border-radius:8px; padding:10px; margin-bottom:10px; border-left:4px solid #10b981;">
                <div style="font-size:14px; font-weight:bold; color:#10b981;">
                    🌏 北向持仓：{stock['north_hold']/1e4:.0f}万股
                </div>
            </div>
            ''' if stock.get('north_hold') else ''}
            
            <!-- 新增：限售解禁 -->
            {f'''
            <div style="background:#dc262620; border-radius:8px; padding:10px; margin-bottom:10px; border-left:4px solid #dc262626;">
                <div style="font-size:14px; font-weight:bold; color:#dc262626;">
                    ⚠️ 解禁：{stock['restricted_date']}
                </div>
                <div style="font-size:12px; color:#dc262626; margin-top:2px;">
                    解禁{stock['restricted_amount']/1e8:.2f}亿股
                </div>
            </div>
            ''' if stock.get('restricted_date') else ''}
            
            <!-- 新增：周线共振 -->
            {f'''
            <div style="background:{'#10b981' if stock['weekly_signal'] in ['金叉','多头'] else '#ef4444'}20; border-radius:8px; padding:10px; margin-bottom:15px; border-left:4px solid {'#10b981' if stock['weekly_signal'] in ['金叉','多头'] else '#ef4444'};">
                <div style="font-size:14px; font-weight:bold; color:{'#10b981' if stock['weekly_signal'] in ['金叉','多头'] else '#ef4444'};">
                    📅 {stock['weekly_desc']}
                </div>
            </div>
            ''' if stock.get('weekly_desc') else ''}
            
            <!-- 新增：王牌线 -->
            {f'''
            <div style="background:#f59e0b20; border-radius:8px; padding:10px; margin-bottom:10px; border-left:4px solid #f59e0b;">
                <div style="font-size:14px; font-weight:bold; color:#f59e0b;">
                    🛡️ {stock['ace_type']}线：{stock['ace_line']:.2f}元
                </div>
                <div style="font-size:12px; color:#f59e0b; margin-top:2px;">
                    当前价格{stock['vs_ace_pct']:+.1f}%
                </div>
            </div>
            ''' if stock.get('ace_line') else ''}
            
            <!-- 新增：价柱形态 -->
            {f'''
            <div style="background:#8b5cf620; border-radius:8px; padding:10px; margin-bottom:10px; border-left:4px solid #8b5cf6;">
                <div style="font-size:14px; font-weight:bold; color:#8b5cf6;">
                    📈 今日价柱：{stock['price_pattern']}
                </div>
            </div>
            ''' if stock.get('price_pattern') and stock['price_pattern'] != '普通' else ''}
            
            <!-- 新增：量价背离 -->
            {f'''
            <div style="background:#dc262620; border-radius:8px; padding:10px; margin-bottom:10px; border-left:4px solid #dc262626;">
                <div style="font-size:14px; font-weight:bold; color:#dc262626;">
                    ⚠️ {stock['divergence']}
                </div>
            </div>
            ''' if stock.get('divergence') else ''}
            
            <!-- 新增：风险信号 -->
            {''.join([f'''
            <div style="background:#dc262620; border-radius:8px; padding:8px; margin-bottom:8px; border-left:4px solid #dc262626;">
                <div style="font-size:13px; font-weight:bold; color:#dc262626;">
                    {risk}
                </div>
            </div>
            ''' for risk in stock.get('risks', [])])}
            
            <div class="step-section">
                <div class="step-title">📐 本股ATR参数（自动计算）</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">ATR(14)</div>
                            <div class="value">{atr_text}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">中大阴线阈值</div>
                            <div class="value">{yin_thresh_text}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">起点：大阴实顶</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">大阴实顶（近60日）</div>
                            <div class="value">{yintop_text}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">当前位置</div>
                            <div class="value" style="color:{yintop_color}">{yintop_status}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">① 从右向左看：比较价柱的高低阴阳</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">价格vs大阴实顶</div>
                            <div class="value">{stock['price_vs_yintop_pct']:+.2f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">阳线/阴线数量</div>
                            <div class="value">{stock['yang_count']}阳 / {stock['yin_count']}阴</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">阴阳比</div>
                            <div class="value">{stock['yang_yin_ratio']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日高点</div>
                            <div class="value">{stock['recent_high']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日低点</div>
                            <div class="value">{stock['recent_low']:.2f}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">② 从上往下看：比较量价的真假大小</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">大阴实顶的量</div>
                            <div class="value">{stock['yin_vol_size']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">今日量柱形态</div>
                            <div class="value">{stock['vol_pattern']}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">③ 从左往右看：比较量柱的远近多少</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">时间距离</div>
                            <div class="value">{stock['days_since_yin']}天前</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">时间影响力</div>
                            <div class="value">{stock['time_impact']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">今天量vs大阴实顶量</div>
                            <div class="value">{stock['today_vs_yin_vol']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">关键位量影响力</div>
                            <div class="value" style="color:{'#ef4444' if stock['impact_20'] == '强' else '#fbbf24' if stock['impact_20'] == '中' else '#94a3b8'}">{stock['impact_20']}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">④ 从下往上看：比较量价的长短伸缩</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">量柱长短</div>
                            <div class="value">{stock['vol_length']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量能位置(20日)</div>
                            <div class="value">{stock['vol_pos_20']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">价柱伸缩</div>
                            <div class="value">{stock['price_length']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">实体占比</div>
                            <div class="value">{stock['body_ratio']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">📊 今日信号（25种涨停基因全）</div>
                <div class="step-content">
                    {extra_html}
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">王牌柱体系（官方版·优先级搜索·基柱自适应）</div>
                <div class="step-content">
                    <div class="grid-2">
                        {pillar_html}
                        <div class="grid-item">
                            <div class="label">黄金线（基柱最低价）</div>
                            <div class="value">{f"{stock['golden_line']:.2f}" if stock['golden_line'] else "无"}</div>
                        </div>
                        {aokou_html}
                        <div class="grid-item">
                            <div class="label">20日量柱位置</div>
                            <div class="value">{stock['vol_pos_20']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">⑤ 左侧关键位</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">平衡线</div>
                            <div class="value">{f"{stock['balance_price']:.2f}（{stock['balance_date']}）" if stock['balance_price'] else '-'}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">精准线</div>
                            <div class="value">{f"{stock['precise_lines'][0]['price']:.2f}（{stock['precise_lines'][0]['points']}点）" if stock['precise_lines'] else '-'}</div>
                        </div>
                        {peak_html('20日峰顶线', stock['peak_20'], stock['peak_date_20'])}
                        {valley_html('20日谷底线', stock['valley_20'], stock['valley_date_20'])}
                        <div class="grid-item">
                            <div class="label">20日安全线</div>
                            <div class="value">{f"{stock['safe_20']:.2f}（{stock['date_20']}）" if stock['safe_20'] else '-'}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日风险线</div>
                            <div class="value">{f"{stock['risk_20']:.2f}（{stock['date_20']}）" if stock['risk_20'] else '-'}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">📖 综合解读（量学理论推导）</div>
                <div class="step-content" style="background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);">
                    {interp_html}
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
        
        .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
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
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>四维循环看盘报告</h1>
            <div class="date">{today_str}</div>
            <div class="note" style="margin-top:10px;font-size:13px;opacity:0.7">量能自适应版 · 核心定义保留官方 · 辅助判断用分位数</div>
        </div>
        
        <div class="signal-guide">
            <h2>参数说明（全部参数化，方便调整）</h2>
            
            <div class="signal-item">
                <h3>【核心定义·保留官方】</h3>
                <p>倍量柱：今天量/昨天量 ≥ 1.8（官方最低90%）</p>
                <p>高量柱：前20天最高</p>
                <p>低量柱：前20天最低</p>
                <p>梯量柱：连续3天递增</p>
                <p>缩量柱：连续3天递减</p>
                <p>平量柱：和前5天平均差不超过15%</p>
                <p class="source">来源：股海明灯官网</p>
            </div>
            
            <div class="signal-item">
                <h3>【辅助判断·分位数自适应】</h3>
                <p>大量/放量：过去20日量的80%分位以上</p>
                <p>小量/缩量：过去20日量的20%分位以下</p>
                <p>王牌柱基柱：基柱量在过去20日的60%分位以上</p>
                <p>倍量伸缩：放量到80%分位 + 缩量到20%分位</p>
                <p class="source">来源：量化行业通用做法</p>
            </div>
            
            <div class="signal-item">
                <h3>【王牌柱官方定义】</h3>
                <p>三原则：①三日收盘不破底 ②量柱三日不过头 ③基柱是相对高量</p>
                <p>搜索优先级：元帅柱 > 黄金柱 > 将军柱</p>
                <p class="source">来源：股海明灯官网《王子老师语录十》</p>
            </div>
            
            <div class="signal-item">
                <h3>【最高原则】</h3>
                <p><strong>所有参数、阈值都要适配当前最新市场环境</strong></p>
                <p><strong>代码不要写死，能用参数阈值的就用参数阈值</strong></p>
                <p><strong>不构成任何交易建议，只做客观描述</strong></p>
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
    print("四维循环看盘报告 - HTML版（量能自适应版）")
    print("=" * 60)
    
    stocks_data = []
    today_str = ""
    
    for market, code in HOLDINGS:
        try:
            data = get_stock_data(market, code)
            if data:
                stocks_data.append(data)
                today_str = data['date']
                if data['atr_pct']:
                    print(f"  已生成：{data['name']}（ATR={data['atr_pct']:.2f}%，王牌柱={data['pillar_type']}）")
                else:
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
