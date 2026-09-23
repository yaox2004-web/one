#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法 - 历史回测验证（终极完整版 + 真假账本优先）
=================================================
【无未来函数】
【买入标准】信号确认后 → 等回踩关键位 → 缩量企稳 → T+1开盘买入
【交易成本】0.35%
【位置分档】低位<30% / 中位30%-70% / 高位>70%
【趋势判断】上升趋势/下降趋势（个股20日均线）
【大盘环境】牛市/熊市（上证指数200日均线）
【真假量柱】优先查 truth_ledger.json 账本，查不到再退回1分钟数据
【资料来源】股海明灯《量柱擒涨停》《量线捉涨停》黑马王子著
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from collections import defaultdict

# ============================================================
# 【配置区】所有参数
# ============================================================

DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
INDEX_PATH = DATA_DIR / "sh" / "sh000001.json"
MIN1_DIR = Path(__file__).parent.parent / "data" / "kline_1min"
LEDGER_PATH = Path(__file__).parent.parent / "data" / "analysis" / "truth_ledger.json"

# 最大回测股票数：持仓8只 + 沪深300全部，共约308只
MAX_STOCKS = 8

# 持仓股（必跑，用户实际操作的）
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

# 持有周期：5天/10天/20天
HOLD_PERIODS = [5, 10, 20]

# ============================================================
# 【回踩买入核心参数】
# ============================================================
MAX_WAIT_DAYS = 10
TOUCH_TOLERANCE = 0.02
SHRINK_VOL_RATIO = 0.8
STAY_ABOVE = True

# ============================================================
# 【交易成本】
# ============================================================
COMMISSION_RATE = 0.00125
STAMP_TAX = 0.001
TOTAL_COST = COMMISSION_RATE * 2 + STAMP_TAX

# ============================================================
# 【位置分档参数】
# ============================================================
POSITION_LOOKBACK = 120
LOW_PCTL = 0.30
HIGH_PCTL = 0.70

# ============================================================
# 【三低筛选参数】
# ============================================================
LOW_VOL_PCTL = 0.30
LOW_PRICE_THRESHOLD = 20.0

# ============================================================
# 【趋势判断参数】
# ============================================================
TREND_MA_PERIOD = 20
INDEX_TREND_MA = 200

# ============================================================
# 【整体结构参数】
# ============================================================
STEP_LOOKBACK = 20

# ============================================================
# 【ATR自适应】
# ============================================================
ATR_ADAPTIVE = True
ATR_PERIOD = 14
YIN_BODY_ATR_MULT = 1.5
YIN_BODY_FALLBACK = 5.0
YIN_LOOKBACK = 60
CHANGYANG_ATR_MULT = 1.5
CHANGYANG_FALLBACK = 5.0

# ============================================================
# 【量柱核心定义】
# ============================================================
BEISHU_RATIO = 1.8
GAOLIANG_LOOKBACK = 20
PINGLIANG_TOLERANCE = 0.15
SMALL_BEISHU_MIN = 1.5
SMALL_BEISHU_MAX = 2.0

# ============================================================
# 【量能分位数】
# ============================================================
VOL_LOOKBACK = 20
VOL_PCTL_HIGH = 0.80
VOL_PCTL_LOW = 0.20
BASE_VOL_PCTL = 0.60
BEISHUO_EXTEND_PCTL = 0.80
BEISHUO_SHRINK_PCTL = 0.20
LONG_YIN_SHORT_VOL_PCTL = 0.30

# ============================================================
# 【涨停板】
# ============================================================
LIMIT_UP_MAIN = 9.8
LIMIT_UP_GEM = 19.8

# ============================================================
# 【王牌柱】
# ============================================================
GENERAL_CONFIRM_DAYS = 3

# ============================================================
# 【峰顶线/谷底线】
# ============================================================
SHORT_WINDOW = 20
CONFIRM_DAYS_SHORT = 2
PEAK_SIDE_SHORT = 2
VOL_PERCENTILE = 0.7

# ============================================================
# 【其他参数】
# ============================================================
BODY_RATIO_THRESHOLD = 0.6
NIUGU_TOUCH_TOLERANCE = 0.01


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


# ============================================================
# 【真假量柱判断】—— 账本优先，1分钟数据兜底
# ============================================================
_real_money_cache = {}
_ledger_cache = None


def _load_ledger():
    """加载真假账本（带缓存，只读一次）"""
    global _ledger_cache
    if _ledger_cache is not None:
        return _ledger_cache
    if not LEDGER_PATH.exists():
        print(f"  [账本] 未找到 {LEDGER_PATH}，将退回1分钟数据")
        _ledger_cache = {}
        return _ledger_cache
    try:
        with open(LEDGER_PATH, 'r', encoding='utf-8') as f:
            _ledger_cache = json.load(f)
        total_records = sum(len(v) for v in _ledger_cache.values())
        print(f"  [账本] 已加载 {len(_ledger_cache)} 只股票，共 {total_records} 条历史记录")
        return _ledger_cache
    except Exception as e:
        print(f"  [账本] 读取失败: {e}，将退回1分钟数据")
        _ledger_cache = {}
        return _ledger_cache


def is_real_money(market, code, trade_date):
    """
    判断当天是真金白银还是量化对倒。
    【优先级1】查账本 truth_ledger.json（几KB，秒查）
    【优先级2】退回1分钟原始数据（兼容老数据）
    返回：(是否真金, 量化占比)
    """
    cache_key = f"{market}{code}_{trade_date}"
    if cache_key in _real_money_cache:
        return _real_money_cache[cache_key]

    # ========== 优先级1：查账本 ==========
    ledger = _load_ledger()
    key = f"{market}{code}"
    if key in ledger and trade_date in ledger[key]:
        entry = ledger[key][trade_date]
        result = (entry.get("is_real"), entry.get("quant_pct", 0))
        _real_money_cache[cache_key] = result
        return result

    # ========== 优先级2：退回1分钟数据 ==========
    filepath = MIN1_DIR / f"{market}{code}.json"
    if not filepath.exists():
        result = (True, 0)
        _real_money_cache[cache_key] = result
        return result

    try:
        with open(filepath, 'r') as f:
            data = json.load(f)
        klines = data.get('klines', [])
        if len(klines) < 100:
            result = (True, 0)
            _real_money_cache[cache_key] = result
            return result

        # 找到当天的1分钟数据
        day_klines = []
        for k in klines:
            if k[0].startswith(trade_date):
                day_klines.append(k)

        if len(day_klines) < 200:
            result = (True, 0)
            _real_money_cache[cache_key] = result
            return result

        # 计算三个指标
        volumes = [float(k[5]) for k in day_klines]
        closes = [float(k[2]) for k in day_klines]

        # 1. CV值
        vol_mean = np.mean(volumes)
        vol_std = np.std(volumes)
        cv = vol_std / vol_mean if vol_mean > 0 else 1

        # 2. 量价相关
        price_changes = np.diff(closes)
        vol_changes = np.diff(volumes)
        if len(price_changes) > 10:
            corr = np.corrcoef(price_changes, vol_changes)[0, 1]
            if np.isnan(corr):
                corr = 0.5
        else:
            corr = 0.5

        # 3. 尾盘占比
        tail_vol = sum(volumes[-30:])
        total_vol = sum(volumes)
        tail_ratio = tail_vol / total_vol if total_vol > 0 else 0

        # 判断
        quant_count = 0
        if cv < 0.5:
            quant_count += 1
        if abs(corr) < 0.3:
            quant_count += 1
        if tail_ratio > 0.3:
            quant_count += 1

        # 量化占比估算
        if cv < 0.5:
            cv_score = 0.7
        elif cv < 1.0:
            cv_score = 0.4
        else:
            cv_score = 0.1

        if abs(corr) < 0.3:
            corr_score = 0.6
        elif abs(corr) < 0.5:
            corr_score = 0.3
        else:
            corr_score = 0.1

        if tail_ratio > 0.3:
            tail_score = 0.7
        elif tail_ratio > 0.2:
            tail_score = 0.4
        else:
            tail_score = 0.1

        quant_ratio = (cv_score + corr_score + tail_score) / 3 * 100

        is_quant = quant_count >= 2
        result = (not is_quant, round(quant_ratio, 1))
        _real_money_cache[cache_key] = result
        return result

    except Exception as e:
        result = (True, 0)
        _real_money_cache[cache_key] = result
        return result


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
# 【量能分位数】
# ============================================================
def get_vol_percentile(df, lookback=20):
    if len(df) < lookback:
        lookback = len(df)
    recent_vols = df.iloc[-lookback:]['volume']
    today_vol = df.iloc[-1]['volume']
    pct = (recent_vols < today_vol).sum() / len(recent_vols)
    return pct


# ============================================================
# 【位置计算】
# ============================================================
def get_position_level(df, end_idx, lookback=POSITION_LOOKBACK):
    if end_idx < lookback:
        lookback = end_idx
    recent_df = df.iloc[end_idx-lookback+1:end_idx+1]
    today_price = df.iloc[end_idx]['close']
    pct = (recent_df['close'] < today_price).sum() / len(recent_df)
    if pct < LOW_PCTL:
        return "低位"
    elif pct > HIGH_PCTL:
        return "高位"
    else:
        return "中位"


# ============================================================
# 【个股趋势判断】
# ============================================================
def get_stock_trend(df, end_idx, ma_period=TREND_MA_PERIOD):
    if end_idx < ma_period:
        return "未知"
    ma = df.iloc[end_idx-ma_period+1:end_idx+1]['close'].mean()
    today_close = df.iloc[end_idx]['close']
    if today_close > ma:
        return "上升趋势"
    else:
        return "下降趋势"


# ============================================================
# 【大盘环境判断】
# ============================================================
def load_index_data():
    if not INDEX_PATH.exists():
        return None
    with open(INDEX_PATH, 'r') as f:
        data = json.load(f)
    klines = data.get('klines', [])
    if not klines:
        return None
    ncols = len(klines[0])
    cols = ['date', 'open', 'close', 'high', 'low', 'volume'] if ncols == 6 else ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
    df = pd.DataFrame(klines)
    df = df.iloc[:, :ncols]
    df.columns = cols[:ncols]
    for col in ['open', 'close', 'high', 'low', 'volume']:
        df[col] = pd.to_numeric(df[col], errors='coerce')
    df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
    return df


def get_market_regime(index_df, target_date):
    if index_df is None:
        return "未知"
    date_mask = index_df['date'] <= target_date
    if date_mask.sum() < INDEX_TREND_MA:
        return "未知"
    end_idx = date_mask.sum() - 1
    ma = index_df.iloc[end_idx-INDEX_TREND_MA+1:end_idx+1]['close'].mean()
    today_close = index_df.iloc[end_idx]['close']
    if today_close > ma:
        return "牛市"
    else:
        return "熊市"


# ============================================================
# 【三低判断】
# ============================================================
def is_san_di(df, end_idx, position):
    if position != "低位":
        return False
    lookback = min(120, end_idx)
    recent_vols = df.iloc[end_idx-lookback+1:end_idx+1]['volume']
    today_vol = df.iloc[end_idx]['volume']
    vol_pctl = (recent_vols < today_vol).sum() / len(recent_vols)
    if vol_pctl > LOW_VOL_PCTL:
        return False
    today_price = df.iloc[end_idx]['close']
    if today_price > LOW_PRICE_THRESHOLD:
        return False
    return True


# ============================================================
# 【整体结构判断】
# ============================================================
def check_healthy_structure(df, end_idx, lookback=STEP_LOOKBACK):
    if end_idx < lookback:
        return False
    recent_df = df.iloc[end_idx-lookback+1:end_idx+1]
    lows = recent_df['low'].values
    first_low = lows[:5].mean()
    last_low = lows[-5:].mean()
    step_up = last_low > first_low
    if len(recent_df) > 10:
        corr = recent_df['close'].pct_change().corr(recent_df['volume'].pct_change())
        healthy_vol_price = corr > 0
    else:
        healthy_vol_price = True
    return step_up and healthy_vol_price


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
            if not klines:
                return None
            ncols = len(klines[0])
            cols = ['date', 'open', 'close', 'high', 'low', 'volume'] if ncols == 6 else ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
            df = pd.DataFrame(klines)
            df = df.iloc[:, :ncols]
            df.columns = cols[:ncols]
            for col in ['open', 'close', 'high', 'low', 'volume']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
            return df
    return None


# ============================================================
# 【自动扫描所有股票】
# ============================================================
def scan_all_stocks():
    stocks = []
    for market, code in HOLDINGS:
        stocks.append((market, code))
    sh_dir = DATA_DIR / "sh"
    if sh_dir.exists():
        for f in sh_dir.glob("*.json"):
            code = f.stem
            if code == "sh000001":
                continue
            if not any(c == code for _, c in stocks):
                stocks.append(("sh", code))
    sz_dir = DATA_DIR / "sz"
    if sz_dir.exists():
        for f in sz_dir.glob("*.json"):
            code = f.stem
            if code.startswith("sz399"):
                continue
            if not any(c == code for _, c in stocks):
                stocks.append(("sz", code))
    if len(stocks) > MAX_STOCKS:
        stocks = stocks[:MAX_STOCKS]
    return stocks


# ============================================================
# 【核心：回踩买入判断】
# ============================================================
def check_pullback_buy(df, confirm_idx, support_price, max_wait_days=MAX_WAIT_DAYS):
    if support_price is None or support_price <= 0:
        return None
    n = len(df)
    for i in range(confirm_idx + 1, min(confirm_idx + 1 + max_wait_days, n - 2)):
        today = df.iloc[i]
        yesterday = df.iloc[i - 1]
        touch_low = today['low'] <= support_price * (1 + TOUCH_TOLERANCE)
        if STAY_ABOVE:
            stay_above = today['close'] >= support_price * (1 - TOUCH_TOLERANCE)
        else:
            stay_above = True
        shrink_vol = today['volume'] < yesterday['volume'] * SHRINK_VOL_RATIO
        if touch_low and stay_above and shrink_vol:
            buy_idx = i + 1
            if buy_idx < n:
                return buy_idx
    return None


# ============================================================
# 【信号判断函数】
# ============================================================
def check_bei_liang(df, i):
    if i < 2:
        return False, None
    today_vol = df.iloc[i]['volume']
    yesterday_vol = df.iloc[i-1]['volume']
    if yesterday_vol > 0 and today_vol / yesterday_vol >= BEISHU_RATIO:
        support = df.iloc[i]['open']
        return True, support
    return False, None


def check_gao_liang(df, i):
    if i < GAOLIANG_LOOKBACK:
        return False, None
    recent = df.iloc[i-GAOLIANG_LOOKBACK:i+1]
    today_vol = df.iloc[i]['volume']
    if today_vol == recent['volume'].max():
        support = df.iloc[i]['low']
        return True, support
    return False, None


def check_di_liang(df, i):
    if i < GAOLIANG_LOOKBACK:
        return False, None
    recent = df.iloc[i-GAOLIANG_LOOKBACK:i+1]
    today_vol = df.iloc[i]['volume']
    if today_vol == recent['volume'].min():
        support = df.iloc[i]['low']
        return True, support
    return False, None


def check_ti_liang(df, i):
    if i < 3:
        return False, None
    v1 = df.iloc[i-2]['volume']
    v2 = df.iloc[i-1]['volume']
    v3 = df.iloc[i]['volume']
    if v1 < v2 < v3:
        support = df.iloc[i-2]['open']
        return True, support
    return False, None


def check_suo_liang(df, i):
    if i < 3:
        return False, None
    v1 = df.iloc[i-2]['volume']
    v2 = df.iloc[i-1]['volume']
    v3 = df.iloc[i]['volume']
    if v1 > v2 > v3:
        support = df.iloc[i-2]['open']
        return True, support
    return False, None


def check_ping_liang(df, i):
    if i < 6:
        return False, None
    today_vol = df.iloc[i]['volume']
    recent_5_avg = df.iloc[i-5:i]['volume'].mean()
    if recent_5_avg > 0:
        diff_pct = abs(today_vol - recent_5_avg) / recent_5_avg
        if diff_pct <= PINGLIANG_TOLERANCE:
            support = df.iloc[i]['close']
            return True, support
    return False, None


def check_xiao_bei_yang(df, i):
    if i < 2:
        return False, None
    today = df.iloc[i]
    yesterday = df.iloc[i-1]
    body_pct = (today['close'] - today['open']) / today['open'] * 100
    vol_ratio = today['volume'] / yesterday['volume'] if yesterday['volume'] > 0 else 0
    if 0 < body_pct < 3 and SMALL_BEISHU_MIN <= vol_ratio < SMALL_BEISHU_MAX:
        support = today['open']
        return True, support
    return False, None


def check_yang_sheng_jin(df, i):
    if i < 2:
        return False, None
    today = df.iloc[i]
    yesterday = df.iloc[i-1]
    if today['close'] > today['open'] and today['volume'] > yesterday['volume'] and today['close'] > yesterday['close']:
        support = today['open']
        return True, support
    return False, None


def check_yin_sheng_chu(df, i):
    if i < 2:
        return False, None
    today = df.iloc[i]
    yesterday = df.iloc[i-1]
    if today['close'] < today['open'] and today['volume'] > yesterday['volume'] and today['close'] < yesterday['close']:
        support = today['close']
        return True, support
    return False, None


def check_chang_duan_yin(df, i, atr_pct):
    if i < 6:
        return False, None
    today = df.iloc[i]
    body_pct_down = (today['open'] - today['close']) / today['close'] * 100
    changyang_thresh = get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK)
    vol_pctl = get_vol_percentile(df.iloc[:i+1], VOL_LOOKBACK)
    if body_pct_down > changyang_thresh and vol_pctl < LONG_YIN_SHORT_VOL_PCTL:
        support = today['low']
        return True, support
    return False, None


def check_yang_bao_yin(df, i):
    if i < 2:
        return False, None
    today = df.iloc[i]
    yesterday = df.iloc[i-1]
    if today['close'] > yesterday['open'] and today['open'] < yesterday['close'] and today['close'] > today['open']:
        support = today['open']
        return True, support
    return False, None


def check_ban_zhang(df, i, code):
    if i < 2:
        return False, None
    today = df.iloc[i]
    yesterday = df.iloc[i-1]
    pct = (today['close'] - yesterday['close']) / yesterday['close'] * 100
    limit_up = LIMIT_UP_GEM if is_gem_star(code) else LIMIT_UP_MAIN
    if pct >= limit_up:
        support = today['open']
        return True, support
    return False, None


def check_guo_zuofeng(df, i, peak_20):
    if peak_20 is None:
        return False, None
    today = df.iloc[i]
    if today['close'] > peak_20:
        support = peak_20
        return True, support
    return False, None


def check_jiayin_ciyang(df, i, atr_pct):
    if i < 6:
        return False, None
    today = df.iloc[i]
    recent_5 = df.iloc[i-5:i]
    changyang_thresh = get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK)
    for j in range(len(recent_5)-2, 0, -1):
        row = recent_5.iloc[j]
        drop_pct = (row['close'] - row['open']) / row['open'] * 100
        if drop_pct < -changyang_thresh:
            if today['close'] > today['open']:
                yin_body_size = row['open'] - row['close']
                rebound_size = today['close'] - row['close']
                if yin_body_size > 0 and rebound_size / yin_body_size > 0.5:
                    support = row['close']
                    return True, support
            break
    return False, None


def check_changyang_aizhu(df, i, atr_pct):
    if i < 2:
        return False, None
    today = df.iloc[i]
    yesterday = df.iloc[i-1]
    changyang_thresh = get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK)
    chongyang_up_pct = (today['close'] - yesterday['close']) / yesterday['close'] * 100
    vol_pctl = get_vol_percentile(df.iloc[:i+1], VOL_LOOKBACK)
    if chongyang_up_pct > changyang_thresh and vol_pctl < 0.5:
        support = today['open']
        return True, support
    return False, None


def check_beiliang_buchuan(df, i, code):
    if i < 60:
        return False, None
    recent_60 = df.iloc[i-59:i+1]
    for j in range(len(recent_60)-1, 5, -1):
        row = recent_60.iloc[j]
        prev_row = recent_60.iloc[j-1]
        if prev_row['volume'] > 0 and row['volume'] / prev_row['volume'] >= BEISHU_RATIO and row['close'] > row['open']:
            beiliang_bottom = row['open']
            future = recent_60.iloc[j+1:]
            if len(future) > 0 and all(future['low'] >= beiliang_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
                support = beiliang_bottom
                return True, support
            break
    return False, None


def check_gaoliang_bupo(df, i):
    if i < 60:
        return False, None
    recent_60 = df.iloc[i-59:i+1]
    max_vol_idx = recent_60['volume'].idxmax()
    max_vol_row = recent_60.loc[max_vol_idx]
    gaoliang_bottom = max_vol_row['low']
    future = recent_60.iloc[max_vol_idx + 1:]
    if len(future) > 0 and all(future['low'] >= gaoliang_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
        support = gaoliang_bottom
        return True, support
    return False, None


def check_diliang_qun(df, i):
    if i < 100:
        return False, None
    recent_100 = df.iloc[i-99:i+1]
    vol_low_pctl = recent_100['volume'].quantile(VOL_PCTL_LOW)
    low_vol_count = sum(recent_100['volume'] <= vol_low_pctl)
    if low_vol_count >= 5:
        last_diliang = recent_100[recent_100['volume'] <= vol_low_pctl].iloc[-1]
        support = last_diliang['low']
        return True, support
    return False, None


def check_jiasheng_liangsou(df, i):
    if i < 3:
        return False, None
    recent_3 = df.iloc[i-2:i+1]
    prices_up = all(recent_3.iloc[j]['close'] > recent_3.iloc[j-1]['close'] for j in range(1, len(recent_3)))
    vols_down = all(recent_3.iloc[j]['volume'] < recent_3.iloc[j-1]['volume'] for j in range(1, len(recent_3)))
    if prices_up and vols_down:
        support = recent_3.iloc[0]['open']
        return True, support
    return False, None


def check_beishuo_shensuo(df, i):
    if i < 5:
        return False, None
    recent_5 = df.iloc[i-4:i+1]
    vols_pctl = (recent_5['volume'].rank(pct=True)).values
    for j in range(1, len(vols_pctl)):
        if vols_pctl[j] >= BEISHUO_EXTEND_PCTL and vols_pctl[j-1] <= BEISHUO_SHRINK_PCTL:
            support = recent_5.iloc[j]['open']
            return True, support
    return False, None


def check_huicai_jingzhun(df, i, precise_price):
    if precise_price is None:
        return False, None
    if i < 10:
        return False, None
    recent_10 = df.iloc[i-9:i+1]
    touched = any(abs(row['low'] - precise_price) / precise_price < TOUCH_TOLERANCE for _, row in recent_10.iterrows())
    if touched:
        support = precise_price
        return True, support
    return False, None


# ============================================================
# 【新增：价柱形态识别】
# ============================================================
def identify_price_pattern(df, i, atr_pct):
    if i < 1:
        return "普通"
    today = df.iloc[i]
    open_price = today['open']
    close_price = today['close']
    high_price = today['high']
    low_price = today['low']
    body = abs(close_price - open_price)
    total_range = high_price - low_price
    if total_range == 0:
        return "十字星"
    body_ratio = body / total_range
    changyang_thresh = get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK)
    if body_ratio > 0.7 and (close_price - open_price) / open_price * 100 > changyang_thresh:
        return "长阳"
    if body_ratio > 0.7 and (open_price - close_price) / open_price * 100 > changyang_thresh:
        return "长阴"
    if body_ratio < 0.1:
        return "十字星"
    return "普通"


# ============================================================
# 【新增：量价背离】
# ============================================================
def check_divergence(df, i):
    if i < 10:
        return None, None
    recent_10 = df.iloc[i-10:i+1]
    price_change = (recent_10.iloc[-1]['close'] - recent_10.iloc[0]['close']) / recent_10.iloc[0]['close'] * 100
    vol_change = (recent_10.iloc[-1]['volume'] - recent_10.iloc[0]['volume']) / recent_10.iloc[0]['volume'] * 100
    if price_change > 5 and vol_change < -20:
        support = recent_10.iloc[-1]['close']
        return "顶背离", support
    if price_change < -5 and vol_change > 20:
        support = recent_10.iloc[-1]['close']
        return "底背离", support
    return None, None


# ============================================================
# 【新增：主力意图识别】
# ============================================================
def check_main_intent(position, stock_trend, vol_pattern, pillar_type, price_pattern):
    intents = []
    if position == "低位" and vol_pattern == "倍量柱" and stock_trend == "上升趋势":
        intents.append(("建仓中", None))
    if position == "中位" and pillar_type == "黄金柱" and stock_trend == "上升趋势":
        intents.append(("洗盘", None))
    if position == "中位" and pillar_type == "元帅柱" and vol_pattern == "倍量柱":
        intents.append(("拉升", None))
    if position == "高位" and vol_pattern == "倍量柱":
        intents.append(("出货", None))
    if position == "高位" and price_pattern == "长阴" and vol_pattern in ["倍量柱", "高量柱"]:
        intents.append(("出逃", None))
    return intents


# ============================================================
# 【找峰顶线/谷底线】
# ============================================================
def find_fenggu_at(df, end_idx, lookback_days, peak_side, confirm_days, vol_percentile):
    min_required = lookback_days + confirm_days + peak_side
    if end_idx < min_required:
        return None, None
    recent_df = df.iloc[end_idx-lookback_days+1:end_idx+1]
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
                peaks.append({'price': row['high'], 'date': row['date']})
        if is_local_low and has_vol:
            future = recent_df.iloc[i+1:i+1+confirm_days]
            if all(future['close'] > row['low']):
                valleys.append({'price': row['low'], 'date': row['date']})
    recent_peak = peaks[-1] if peaks else None
    recent_valley = valleys[-1] if valleys else None
    return (recent_peak['price'] if recent_peak else None,
            recent_valley['price'] if recent_valley else None)


# ============================================================
# 【找精准线】
# ============================================================
def find_precise_at(df, end_idx, lookback_days=120, min_points=3, price_tolerance=1.0):
    if end_idx < lookback_days:
        return None
    recent_df = df.iloc[end_idx-lookback_days+1:end_idx+1]
    prices = recent_df['close'].values
    if len(prices) < min_points:
        return None
    clusters = {}
    used = set()
    for i in range(len(prices)):
        if i in used:
            continue
        cluster = [i]
        for j in range(len(prices)):
            if i == j or j in used:
                continue
            diff_pct = abs(prices[i] - prices[j]) / prices[i] * 100
            if diff_pct <= price_tolerance:
                cluster.append(j)
        if len(cluster) >= min_points:
            avg_price = np.mean([prices[idx] for idx in cluster])
            clusters[len(cluster)] = avg_price
            for idx in cluster:
                used.add(idx)
    if clusters:
        return clusters[max(clusters.keys())]
    return None


# ============================================================
# 【找大阴实顶】
# ============================================================
def find_big_yin_top_at(df, end_idx, lookback_days, yin_body_pct):
    if end_idx < lookback_days:
        return None, None
    recent_df = df.iloc[end_idx-lookback_days+1:end_idx+1]
    for i in range(len(recent_df)-1, -1, -1):
        row = recent_df.iloc[i]
        if row['close'] >= row['open']:
            continue
        body_pct = (row['open'] - row['close']) / row['close'] * 100
        if body_pct >= yin_body_pct:
            return row['open'], row['date']
    return None, None


# ============================================================
# 【找王牌柱】
# ============================================================
def find_pillars_at(df, end_idx, lookback_days=60):
    if end_idx < lookback_days + GENERAL_CONFIRM_DAYS + 20:
        return "无", None
    recent_df = df.iloc[end_idx-lookback_days+1:end_idx+1]
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
        future_avg_close = future['close'].mean()
        if future_avg_close < base_open:
            continue
        future_last_vol = future.iloc[-1]['volume']
        base_vol = row['volume']
        if future_last_vol >= base_vol:
            continue
        is_golden = future_avg_close >= base_close
        if i > 0:
            prev_row = recent_df.iloc[i-1]
            is_gap_up = row['open'] > prev_row['high']
        else:
            is_gap_up = False
        if is_golden and is_gap_up:
            marshals.append(row['low'])
        elif is_golden:
            goldens.append(row['low'])
        else:
            generals.append(row['low'])
    if marshals:
        return "元帅柱", marshals[0]
    elif goldens:
        return "黄金柱", goldens[0]
    elif generals:
        return "将军柱", generals[0]
    else:
        return "无", None


# ============================================================
# 【主函数】
# ============================================================
def main():
    print("=" * 70)
    print("四维循环看盘法 - 历史回测验证（终极完整版 + 真假账本优先）")
    print("=" * 70)
    print(f"\n样本：持仓8只 + 沪深300全部，约{MAX_STOCKS}只")
    print(f"位置分档：低位<30% / 中位30%-70% / 高位>70%")
    print(f"个股趋势：上升/下降（20日均线）")
    print(f"大盘环境：牛市/熊市（200年线）")
    print(f"交易成本：{TOTAL_COST*100:.2f}%")
    print(f"买入规则：信号→回踩支撑→缩量企稳→T+1开盘买")
    print(f"真假量柱：优先查账本 truth_ledger.json")

    # 预加载账本
    _load_ledger()

    index_df = load_index_data()
    if index_df is not None:
        print(f"\n已加载上证指数数据：{len(index_df)}条")
    else:
        print("\n警告：未找到上证指数数据，大盘环境判断将显示'未知'")

    all_stocks = scan_all_stocks()

    print(f"\n自动扫描到股票数：{len(all_stocks)}只")
    print(f"持有周期：{HOLD_PERIODS}个交易日\n")

    all_trades = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {h: [] for h in HOLD_PERIODS}))))

    for idx, (market, code) in enumerate(all_stocks):
        print(f"  回测中 {idx+1}/{len(all_stocks)}: {market}{code} ...")
        df = load_klines(market, code)
        if df is None:
            continue
        full_code = f"{market}{code}"
        n = len(df)
        start_idx = 120

        for i in range(start_idx, n - 60 - MAX_WAIT_DAYS - 2):
            atr_value, atr_pct = calculate_atr(df.iloc[:i+1], ATR_PERIOD)
            yin_body_thresh = get_atr_threshold(atr_pct, YIN_BODY_ATR_MULT, YIN_BODY_FALLBACK)

            peak_20, valley_20 = find_fenggu_at(df, i, SHORT_WINDOW, PEAK_SIDE_SHORT, CONFIRM_DAYS_SHORT, VOL_PERCENTILE)
            precise_price = find_precise_at(df, i)
            big_yin_top, big_yin_date = find_big_yin_top_at(df, i, YIN_LOOKBACK, yin_body_thresh)
            pillar_type, golden_line = find_pillars_at(df, i)

            position = get_position_level(df, i)
            stock_trend = get_stock_trend(df, i)

            today_date = df.iloc[i]['date']
            market_regime = get_market_regime(index_df, today_date)

            signals_today = []
            vol_pattern = "无"

            ok, support = check_bei_liang(df, i)
            if ok:
                signals_today.append(("倍量柱", support))
                vol_pattern = "倍量柱"
            ok, support = check_gao_liang(df, i)
            if ok:
                signals_today.append(("高量柱", support))
                if vol_pattern == "无":
                    vol_pattern = "高量柱"
            ok, support = check_di_liang(df, i)
            if ok:
                signals_today.append(("低量柱（地量）", support))
                if vol_pattern == "无":
                    vol_pattern = "低量柱"
            ok, support = check_ti_liang(df, i)
            if ok:
                signals_today.append(("梯量柱", support))
                if vol_pattern == "无":
                    vol_pattern = "梯量柱"
            ok, support = check_suo_liang(df, i)
            if ok:
                signals_today.append(("缩量柱", support))
                if vol_pattern == "无":
                    vol_pattern = "缩量柱"
            ok, support = check_ping_liang(df, i)
            if ok:
                signals_today.append(("平量柱", support))
                if vol_pattern == "无":
                    vol_pattern = "平量柱"

            ok, support = check_xiao_bei_yang(df, i)
            if ok:
                signals_today.append(("小倍阳（矮将军）", support))
            ok, support = check_yang_sheng_jin(df, i)
            if ok:
                signals_today.append(("阳胜进", support))
            ok, support = check_yin_sheng_chu(df, i)
            if ok:
                signals_today.append(("阴胜出", support))
            ok, support = check_chang_duan_yin(df, i, atr_pct)
            if ok:
                signals_today.append(("长阴短柱", support))
            ok, support = check_yang_bao_yin(df, i)
            if ok:
                signals_today.append(("阳包阴", support))
            ok, support = check_ban_zhang(df, i, full_code)
            if ok:
                signals_today.append(("涨停板", support))
            ok, support = check_guo_zuofeng(df, i, peak_20)
            if ok:
                signals_today.append(("过左峰", support))
            ok, support = check_jiayin_ciyang(df, i, atr_pct)
            if ok:
                signals_today.append(("极阴次阳", support))
            ok, support = check_changyang_aizhu(df, i, atr_pct)
            if ok:
                signals_today.append(("长阳矮柱", support))
            ok, support = check_beiliang_buchuan(df, i, full_code)
            if ok:
                signals_today.append(("倍量不穿", support))
            ok, support = check_gaoliang_bupo(df, i)
            if ok:
                signals_today.append(("高量不破", support))
            ok, support = check_diliang_qun(df, i)
            if ok:
                signals_today.append(("地量群", support))
            ok, support = check_jiasheng_liangsou(df, i)
            if ok:
                signals_today.append(("价升量缩", support))
            ok, support = check_beishuo_shensuo(df, i)
            if ok:
                signals_today.append(("倍量伸缩", support))
            ok, support = check_huicai_jingzhun(df, i, precise_price)
            if ok:
                signals_today.append(("回踩精准线", support))

            if pillar_type == "元帅柱":
                signals_today.append(("元帅柱", golden_line))
            elif pillar_type == "黄金柱":
                signals_today.append(("黄金柱", golden_line))
            elif pillar_type == "将军柱":
                signals_today.append(("将军柱", golden_line))

            if valley_20:
                today = df.iloc[i]
                touched = abs(today['low'] - valley_20) / valley_20 < TOUCH_TOLERANCE
                if touched and today['close'] > valley_20:
                    signals_today.append(("回踩谷底线不破", valley_20))

            if big_yin_top:
                today = df.iloc[i]
                if today['close'] > big_yin_top:
                    signals_today.append(("突破大阴实顶", big_yin_top))

            price_pattern = identify_price_pattern(df, i, atr_pct)
            if price_pattern != "普通":
                signals_today.append((price_pattern, df.iloc[i]['close']))

            divergence_name, divergence_support = check_divergence(df, i)
            if divergence_name:
                signals_today.append((divergence_name, divergence_support))

            main_intents = check_main_intent(position, stock_trend, vol_pattern, pillar_type, price_pattern)
            for intent_name, intent_support in main_intents:
                if intent_support is None:
                    intent_support = df.iloc[i]['close']
                signals_today.append((intent_name, intent_support))

            for signal_name, support_price in signals_today:
                if signal_name == "阴胜出":
                    continue
                buy_idx = check_pullback_buy(df, i, support_price)
                if buy_idx is None:
                    continue

                buy_today = df.iloc[buy_idx]
                buy_yesterday = df.iloc[buy_idx - 1]
                if buy_today['open'] == buy_today['close'] and (buy_today['close'] - buy_yesterday['close']) / buy_yesterday['close'] * 100 > 9.5:
                    continue

                bp = df.iloc[buy_idx]['open']

                today_date = df.iloc[i]['date']
                is_real, quant_ratio = is_real_money(market, code, today_date)

                for hold_days in HOLD_PERIODS:
                    sell_idx = buy_idx + hold_days
                    if sell_idx >= n:
                        continue
                    sp = df.iloc[sell_idx]['close']
                    if bp <= 0:
                        continue
                    ret = (sp - bp) / bp * 100 - TOTAL_COST * 100
                    all_trades[signal_name][position][stock_trend][market_regime][hold_days].append((ret, is_real))

    print("\n" + "=" * 70)
    print("四维循环看盘法 - 历史回测结果（终极完整版）")
    print("=" * 70)
    print(f"\n总股票数：{len(all_stocks)}只")
    print(f"交易成本：已扣除{TOTAL_COST*100:.2f}%\n")

    positions = ["低位", "中位", "高位"]
    stock_trends = ["上升趋势", "下降趋势"]
    market_regimes = ["牛市", "熊市", "未知"]

    for hold_days in HOLD_PERIODS:
        print(f"\n=== 持有{hold_days}天 ===")

        for market_regime in market_regimes:
            has_data = False
            for pos in positions:
                for trend in stock_trends:
                    for sig in all_trades:
                        if len(all_trades[sig][pos][trend][market_regime][hold_days]) > 0:
                            has_data = True
                            break
                    if has_data:
                        break
                if has_data:
                    break
            if not has_data:
                continue

            print(f"\n大盘环境：{market_regime}")

            for pos in positions:
                print(f"\n  --- {pos} ---")

                for trend in stock_trends:
                    print(f"\n    [{trend}]")
                    print(f"    {'信号':<20} {'样本数':>8} {'平均收益%':>10} {'胜率%':>8} {'结论':>10}")
                    print("    " + "-" * 65)

                    sorted_signals = sorted(all_trades.keys(), key=lambda x: len(all_trades[x][pos][trend][market_regime][hold_days]), reverse=True)

                    for signal_name in sorted_signals:
                        returns = all_trades[signal_name][pos][trend][market_regime][hold_days]
                        count = len(returns)
                        if count < 5:
                            continue
                        avg_ret = np.mean([r[0] for r in returns])
                        win_rate = sum(1 for r in returns if r[0] > 0) / count * 100

                        if win_rate > 55 and avg_ret > 0:
                            conclusion = "有效"
                        elif win_rate > 50:
                            conclusion = "一般"
                        else:
                            conclusion = "无效"

                        print(f"    {signal_name:<20} {count:>8} {avg_ret:>10.2f} {win_rate:>8.1f} {conclusion:>10}")

    print("\n" + "=" * 70)
    print("结论说明：")
    print("- 胜率>55% 且 平均收益>0：信号有效")
    print("- 胜率50%-55%：信号一般")
    print("- 胜率<50%：信号无效")
    print("=" * 70)

    WINRATE_HOLD_DAYS = 20

    winrate_data = {}
    for signal_name in all_trades:
        for pos in positions:
            if pos not in winrate_data:
                winrate_data[pos] = {}
            for trend in stock_trends:
                if trend not in winrate_data[pos]:
                    winrate_data[pos][trend] = {}
                all_trades_list = []
                for regime in market_regimes:
                    all_trades_list.extend(all_trades[signal_name][pos][trend][regime][WINRATE_HOLD_DAYS])

                all_returns = [t[0] for t in all_trades_list]
                count = len(all_returns)
                if count >= 5:
                    win_rate = sum(1 for r in all_returns if r > 0) / count * 100
                    avg_ret = float(np.mean(all_returns))
                    winrate_data[pos][trend][signal_name] = {
                        "win_rate": round(win_rate, 1),
                        "avg_ret": round(avg_ret, 2)
                    }

                real_returns = [t[0] for t in all_trades_list if t[1] is True]
                real_count = len(real_returns)
                if real_count >= 5:
                    real_win_rate = sum(1 for r in real_returns if r > 0) / real_count * 100
                    real_avg_ret = float(np.mean(real_returns))
                    winrate_data[pos][trend][f"{signal_name}_真金"] = {
                        "win_rate": round(real_win_rate, 1),
                        "avg_ret": round(real_avg_ret, 2)
                    }

                quant_returns = [t[0] for t in all_trades_list if t[1] is False]
                quant_count = len(quant_returns)
                if quant_count >= 5:
                    quant_win_rate = sum(1 for r in quant_returns if r > 0) / quant_count * 100
                    quant_avg_ret = float(np.mean(quant_returns))
                    winrate_data[pos][trend][f"{signal_name}_量化"] = {
                        "win_rate": round(quant_win_rate, 1),
                        "avg_ret": round(quant_avg_ret, 2)
                    }

    output_dir = Path(__file__).parent.parent / "data" / "analysis"
    output_dir.mkdir(parents=True, exist_ok=True)
    winrate_path = output_dir / "winrate.json"
    with open(winrate_path, 'w', encoding='utf-8') as f:
        json.dump(winrate_data, f, ensure_ascii=False, indent=2)
    print(f"\n✅ 已生成胜率文件：{winrate_path}")
    print(f"   报告脚本下次运行时会自动读取这个文件！")


if __name__ == "__main__":
    main()
