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
HS300_PATH = Path(__file__).parent.parent / "data" / "hushen300.json"

# 最大回测股票数：沪深300 + 持仓股，约308只
MAX_STOCKS = 308

# 回测起始日（缩短历史跨度，加速回测）
START_IDX = 500

# 持仓股（必跑，用户实际操作的）
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
    cache_key = f"{market}{code}_{trade_date}"
    if cache_key in _real_money_cache:
        return _real_money_cache[cache_key]

    # 优先级1：查账本
    ledger = _load_ledger()
    key = f"{market}{code}"
    if key in ledger and trade_date in ledger[key]:
        entry = ledger[key][trade_date]
        result = (entry.get("is_real"), entry.get("quant_pct", 0))
        _real_money_cache[cache_key] = result
        return result

    # 优先级2：退回1分钟数据
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

        day_klines = []
        for k in klines:
            if k[0].startswith(trade_date):
                day_klines.append(k)

        if len(day_klines) < 200:
            result = (True, 0)
            _real_money_cache[cache_key] = result
            return result

        volumes = [float(k[5]) for k in day_klines]
        closes = [float(k[2]) for k in day_klines]

        vol_mean = np.mean(volumes)
        vol_std = np.std(volumes)
        cv = vol_std / vol_mean if vol_mean > 0 else 1

        price_changes = np.diff(closes)
        vol_changes = np.diff(volumes)
        if len(price_changes) > 10:
            corr = np.corrcoef(price_changes, vol_changes)[0, 1]
            if np.isnan(corr):
                corr = 0.5
        else:
            corr = 0.5

        tail_vol = sum(volumes[-30:])
        total_vol = sum(volumes)
        tail_ratio = tail_vol / total_vol if total_vol > 0 else 0

        quant_count = 0
        if cv < 0.5: quant_count += 1
        if abs(corr) < 0.3: quant_count += 1
        if tail_ratio > 0.3: quant_count += 1

        if cv < 0.5: cv_score = 0.7
        elif cv < 1.0: cv_score = 0.4
        else: cv_score = 0.1

        if abs(corr) < 0.3: corr_score = 0.6
        elif abs(corr) < 0.5: corr_score = 0.3
        else: corr_score = 0.1

        if tail_ratio > 0.3: tail_score = 0.7
        elif tail_ratio > 0.2: tail_score = 0.4
        else: tail_score = 0.1

        quant_ratio = (cv_score + corr_score + tail_score) / 3 * 100
        is_quant = quant_count >= 2
        result = (not is_quant, round(quant_ratio, 1))
        _real_money_cache[cache_key] = result
        return result

    except Exception:
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
# 【自动扫描所有股票】（优先纳入沪深300和持仓股）
# ============================================================
def scan_all_stocks():
    stocks = []
    
    # 1. 优先：持仓股
    for market, code in HOLDINGS:
        stocks.append((market, code))
        
    # 2. 其次：沪深300成分股（从本地读取）
    hs300_codes = []
    if HS300_PATH.exists():
        try:
            with open(HS300_PATH, 'r', encoding='utf-8') as f:
                data = json.load(f)
            hs300_codes = data.get('codes', [])
        except Exception:
            pass
            
    for code in hs300_codes:
        market = code[:2]
        pure_code = code[2:]
        if not any(c == pure_code for _, c in stocks):
            stocks.append((market, pure_code))

    # 3. 最后：本地目录补充（防止不足308只）
    sh_dir = DATA_DIR / "sh"
    if sh_dir.exists():
        for f in sh_dir.glob("*.json"):
            code = f.stem
            if code == "sh000001":
                continue
            pure_code = code[2:] if code.startswith('sh') else code
            if not any(c == pure_code for _, c in stocks):
                stocks.append(("sh", pure_code))
                
    sz_dir = DATA_DIR / "sz"
    if sz_dir.exists():
        for f in sz_dir.glob("*.json"):
            code = f.stem
            if code.startswith("sz399"):
                continue
            pure_code = code[2:] if code.startswith('sz') else code
            if not any(c == pure_code for _, c in stocks):
                stocks.append(("sz", pure_code))

    # 限制最大数量
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
    if i < 2: return False, None
    today_vol = df.iloc[i]['volume']
    yesterday_vol = df.iloc[i-1]['volume']
    if yesterday_vol > 0 and today_vol / yesterday_vol >= BEISHU_RATIO:
        return True, df.iloc[i]['open']
    return False, None

def check_gao_liang(df, i):
    if i < GAOLIANG_LOOKBACK: return False, None
    recent = df.iloc[i-GAOLIANG_LOOKBACK:i+1]
    if df.iloc[i]['volume'] == recent['volume'].max():
        return True, df.iloc[i]['low']
    return False, None

def check_di_liang(df, i):
    if i < GAOLIANG_LOOKBACK: return False, None
    recent = df.iloc[i-GAOLIANG_LOOKBACK:i+1]
    if df.iloc[i]['volume'] == recent['volume'].min():
        return True, df.iloc[i]['low']
    return False, None

def check_ti_liang(df, i):
    if i < 3: return False, None
    v1, v2, v3 = df.iloc[i-2]['volume'], df.iloc[i-1]['volume'], df.iloc[i]['volume']
    if v1 < v2 < v3:
        return True, df.iloc[i-2]['open']
    return False, None

def check_suo_liang(df, i):
    if i < 3: return False, None
    v1, v2, v3 = df.iloc[i-2]['volume'], df.iloc[i-1]['volume'], df.iloc[i]['volume']
    if v1 > v2 > v3:
        return True, df.iloc[i-2]['open']
    return False, None

def check_ping_liang(df, i):
    if i < 6: return False, None
    recent_5_avg = df.iloc[i-5:i]['volume'].mean()
    if recent_5_avg > 0 and abs(df.iloc[i]['volume'] - recent_5_avg) / recent_5_avg <= PINGLIANG_TOLERANCE:
        return True, df.iloc[i]['close']
    return False, None

def check_xiao_bei_yang(df, i):
    if i < 2: return False, None
    today, yesterday = df.iloc[i], df.iloc[i-1]
    body_pct = (today['close'] - today['open']) / today['open'] * 100
    vol_ratio = today['volume'] / yesterday['volume'] if yesterday['volume'] > 0 else 0
    if 0 < body_pct < 3 and SMALL_BEISHU_MIN <= vol_ratio < SMALL_BEISHU_MAX:
        return True, today['open']
    return False, None

def check_yang_sheng_jin(df, i):
    if i < 2: return False, None
    today, yesterday = df.iloc[i], df.iloc[i-1]
    if today['close'] > today['open'] and today['volume'] > yesterday['volume'] and today['close'] > yesterday['close']:
        return True, today['open']
    return False, None

def check_yin_sheng_chu(df, i):
    if i < 2: return False, None
    today, yesterday = df.iloc[i], df.iloc[i-1]
    if today['close'] < today['open'] and today['volume'] > yesterday['volume'] and today['close'] < yesterday['close']:
        return True, today['close']
    return False, None

def check_chang_duan_yin(df, i, atr_pct):
    if i < 6: return False, None
    today = df.iloc[i]
    body_pct_down = (today['open'] - today['close']) / today['close'] * 100
    vol_pctl = get_vol_percentile(df.iloc[:i+1], VOL_LOOKBACK)
    if body_pct_down > get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK) and vol_pctl < LONG_YIN_SHORT_VOL_PCTL:
        return True, today['low']
    return False, None

def check_yang_bao_yin(df, i):
    if i < 2: return False, None
    today, yesterday = df.iloc[i], df.iloc[i-1]
    if today['close'] > yesterday['open'] and today['open'] < yesterday['close'] and today['close'] > today['open']:
        return True, today['open']
    return False, None

def check_ban_zhang(df, i, code):
    if i < 2: return False, None
    today, yesterday = df.iloc[i], df.iloc[i-1]
    pct = (today['close'] - yesterday['close']) / yesterday['close'] * 100
    limit_up = LIMIT_UP_GEM if is_gem_star(code) else LIMIT_UP_MAIN
    if pct >= limit_up:
        return True, today['open']
    return False, None

def check_guo_zuofeng(df, i, peak_20):
    if peak_20 is None: return False, None
    if df.iloc[i]['close'] > peak_20:
        return True, peak_20
    return False, None

def check_jiayin_ciyang(df, i, atr_pct):
    if i < 6: return False, None
    today = df.iloc[i]
    recent_5 = df.iloc[i-5:i]
    changyang_thresh = get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK)
    for j in range(len(recent_5)-2, 0, -1):
        row = recent_5.iloc[j]
        if (row['close'] - row['open']) / row['open'] * 100 < -changyang_thresh:
            if today['close'] > today['open'] and (row['open'] - row['close']) > 0 and (today['close'] - row['close']) / (row['open'] - row['close']) > 0.5:
                return True, row['close']
            break
    return False, None

def check_changyang_aizhu(df, i, atr_pct):
    if i < 2: return False, None
    today, yesterday = df.iloc[i], df.iloc[i-1]
    if (today['close'] - yesterday['close']) / yesterday['close'] * 100 > get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK) and get_vol_percentile(df.iloc[:i+1], VOL_LOOKBACK) < 0.5:
        return True, today['open']
    return False, None

def check_beiliang_buchuan(df, i, code):
    if i < 60: return False, None
    recent_60 = df.iloc[i-59:i+1]
    for j in range(len(recent_60)-1, 5, -1):
        row, prev_row = recent_60.iloc[j], recent_60.iloc[j-1]
        if prev_row['volume'] > 0 and row['volume'] / prev_row['volume'] >= BEISHU_RATIO and row['close'] > row['open']:
            beiliang_bottom = row['open']
            future = recent_60.iloc[j+1:]
            if len(future) > 0 and all(future['low'] >= beiliang_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
                return True, beiliang_bottom
            break
    return False, None

def check_gaoliang_bupo(df, i):
    if i < 60: return False, None
    recent_60 = df.iloc[i-59:i+1]
    max_vol_idx = recent_60['volume'].idxmax()
    max_vol_row = recent_60.loc[max_vol_idx]
    gaoliang_bottom = max_vol_row['low']
    future = recent_60.iloc[max_vol_idx + 1:]
    if len(future) > 0 and all(future['low'] >= gaoliang_bottom * (1 - NIUGU_TOUCH_TOLERANCE)):
        return True, gaoliang_bottom
    return False, None

def check_diliang_qun(df, i):
    if i < 100: return False, None
    recent_100 = df.iloc[i-99:i+1]
    vol_low_pctl = recent_100['volume'].quantile(VOL_PCTL_LOW)
    low_vol_count = sum(recent_100['volume'] <= vol_low_pctl)
    if low_vol_count >= 5:
        return True, recent_100[recent_100['volume'] <= vol_low_pctl].iloc[-1]['low']
    return False, None

def check_jiasheng_liangsou(df, i):
    if i < 3: return False, None
    recent_3 = df.iloc[i-2:i+1]
    prices_up = all(recent_3.iloc[j]['close'] > recent_3.iloc[j-1]['close'] for j in range(1, len(recent_3)))
    vols_down = all(recent_3.iloc[j]['volume'] < recent_3.iloc[j-1]['volume'] for j in range(1, len(recent_3)))
    if prices_up and vols_down:
        return True, recent_3.iloc[0]['open']
    return False, None

def check_beishuo_shensuo(df, i):
    if i < 5: return False, None
    recent_5 = df.iloc[i-4:i+1]
    vols_pctl = (recent_5['volume'].rank(pct=True)).values
    for j in range(1, len(vols_pctl)):
        if vols_pctl[j] >= BEISHUO_EXTEND_PCTL and vols_pctl[j-1] <= BEISHUO_SHRINK_PCTL:
            return True, recent_5.iloc[j]['open']
    return False, None

def check_huicai_jingzhun(df, i, precise_price):
    if precise_price is None or i < 10: return False, None
    recent_10 = df.iloc[i-9:i+1]
    if any(abs(row['low'] - precise_price) / precise_price < TOUCH_TOLERANCE for _, row in recent_10.iterrows()):
        return True, precise_price
    return False, None


# ============================================================
# 【新增：价柱形态识别】
# ============================================================
def identify_price_pattern(df, i, atr_pct):
    if i < 1: return "普通"
    today = df.iloc[i]
    body = abs(today['close'] - today['open'])
    total_range = today['high'] - today['low']
    if total_range == 0: return "十字星"
    body_ratio = body / total_range
    changyang_thresh = get_atr_threshold(atr_pct, CHANGYANG_ATR_MULT, CHANGYANG_FALLBACK)
    if body_ratio > 0.7:
        if (today['close'] - today['open']) / today['open'] * 100 > changyang_thresh: return "长阳"
        if (today['open'] - today['close']) / today['open'] * 100 > changyang_thresh: return "长阴"
    if body_ratio < 0.1: return "十字星"
    return "普通"


# ============================================================
# 【新增：量价背离】（修复除零问题）
# ============================================================
def check_divergence(df, i):
    if i < 10: return None, None
    recent_10 = df.iloc[i-10:i+1]
    price_change = (recent_10.iloc[-1]['close'] - recent_10.iloc[0]['close']) / recent_10.iloc[0]['close'] * 100
    
    # 修复：防止除零
    first_vol = recent_10.iloc[0]['volume']
    if first_vol > 0:
        vol_change = (recent_10.iloc[-1]['volume'] - first_vol) / first_vol * 100
    else:
        vol_change = 0
    
    if price_change > 5 and vol_change < -20:
        return "顶背离", recent_10.iloc[-1]['close']
    if price_change < -5 and vol_change > 20:
        return "底背离", recent_10.iloc[-1]['close']
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
    if end_idx < min_required: return None, None
    recent_df = df.iloc[end_idx-lookback_days+1:end_idx+1]
    vol_threshold = recent_df['volume'].quantile(vol_percentile)
    peaks, valleys = [], []
    for i in range(peak_side, len(recent_df) - max(peak_side, confirm_days)):
        row = recent_df.iloc[i]
        window = recent_df.iloc[i-peak_side:i+peak_side+1]
        if row['high'] == window['high'].max() and row['volume'] >= vol_threshold:
            if all(recent_df.iloc[i+1:i+1+confirm_days]['close'] < row['high']): peaks.append({'price': row['high'], 'date': row['date']})
        if row['low'] == window['low'].min() and row['volume'] >= vol_threshold:
            if all(recent_df.iloc[i+1:i+1+confirm_days]['close'] > row['low']): valleys.append({'price': row['low'], 'date': row['date']})
    return (peaks[-1]['price'] if peaks else None, valleys[-1]['price'] if valleys else None)


# ============================================================
# 【找精准线】
# ============================================================
def find_precise_at(df, end_idx, lookback_days=120, min_points=3, price_tolerance=1.0):
    if end_idx < lookback_days: return None
    recent_df = df.iloc[end_idx-lookback_days+1:end_idx+1]
    prices = recent_df['close'].values
    if len(prices) < min_points: return None
    clusters, used = {}, set()
    for i in range(len(prices)):
        if i in used: continue
        cluster = [i]
        for j in range(len(prices)):
            if i == j or j in used: continue
            if abs(prices[i] - prices[j]) / prices[i] * 100 <= price_tolerance: cluster.append(j)
        if len(cluster) >= min_points:
            avg_price = np.mean([prices[idx] for idx in cluster])
            clusters[len(cluster)] = avg_price
            for idx in cluster: used.add(idx)
    return clusters[max(clusters.keys())] if clusters else None


# ============================================================
# 【找大阴实顶】
# ============================================================
def find_big_yin_top_at(df, end_idx, lookback_days, yin_body_pct):
    if end_idx < lookback_days: return None, None
    recent_df = df.iloc[end_idx-lookback_days+1:end_idx+1]
    for i in range(len(recent_df)-1, -1, -1):
        row = recent_df.iloc[i]
        if row['close'] < row['open'] and (row['open'] - row['close']) / row['close'] * 100 >= yin_body_pct:
            return row['open'], row['date']
    return None, None


# ============================================================
# 【找王牌柱】
# ============================================================
def find_pillars_at(df, end_idx, lookback_days=60):
    if end_idx < lookback_days + GENERAL_CONFIRM_DAYS + 20: return "无", None
    recent_df = df.iloc[end_idx-lookback_days+1:end_idx+1]
    marshals, goldens, generals = [], [], []
    for i in range(len(recent_df) - GENERAL_CONFIRM_DAYS - 1, 5, -1):
        row = recent_df.iloc[i]
        if row['close'] <= row['open'] or i < 20: continue
        start_idx = max(0, i - 20)
        vol_window = recent_df.iloc[start_idx:i]['volume']
        if (vol_window < row['volume']).sum() / len(vol_window) < BASE_VOL_PCTL: continue
        future = recent_df.iloc[i+1:i+1+GENERAL_CONFIRM_DAYS]
        if len(future) < GENERAL_CONFIRM_DAYS: continue
        if future['close'].mean() < row['open'] or future.iloc[-1]['volume'] >= row['volume']: continue
        is_golden = future['close'].mean() >= row['close']
        is_gap_up = row['open'] > recent_df.iloc[i-1]['high'] if i > 0 else False
        if is_golden and is_gap_up: marshals.append(row['low'])
        elif is_golden: goldens.append(row['low'])
        else: generals.append(row['low'])
    if marshals: return "元帅柱", marshals[0]
    if goldens: return "黄金柱", goldens[0]
    if generals: return "将军柱", generals[0]
    return "无", None


# ============================================================
# 【主函数】
# ============================================================
def main():
    print("=" * 70)
    print("四维循环看盘法 - 历史回测验证（终极完整版 + 真假账本优先）")
    print("=" * 70)
    print(f"\n样本：沪深300 + 持仓股，共 {MAX_STOCKS} 只")
    print(f"回测起始日：第 {START_IDX} 天（只跑近2年）")
    print(f"位置分档：低位<30% / 中位30%-70% / 高位>70%")
    print(f"交易成本：{TOTAL_COST*100:.2f}%")
    print(f"真假量柱：优先查账本 truth_ledger.json")

    _load_ledger()
    index_df = load_index_data()
    all_stocks = scan_all_stocks()

    print(f"\n自动扫描到股票数：{len(all_stocks)}只")
    print(f"持有周期：{HOLD_PERIODS}个交易日\n")

    all_trades = defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: defaultdict(lambda: {h: [] for h in HOLD_PERIODS}))))

    for idx, (market, code) in enumerate(all_stocks):
        print(f"  回测中 {idx+1}/{len(all_stocks)}: {market}{code} ...")
        df = load_klines(market, code)
        if df is None: continue
        full_code = f"{market}{code}"
        n = len(df)
        
        for i in range(START_IDX, n - 60 - MAX_WAIT_DAYS - 2):
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

            # 1. 量柱
            for name, func in [("倍量柱", check_bei_liang), ("高量柱", check_gao_liang), ("低量柱（地量）", check_di_liang), 
                               ("梯量柱", check_ti_liang), ("缩量柱", check_suo_liang), ("平量柱", check_ping_liang)]:
                ok, support = func(df, i)
                if ok:
                    signals_today.append((name, support))
                    if vol_pattern == "无": vol_pattern = name

            # 2. 形态信号
            for name, func, arg in [("小倍阳（矮将军）", check_xiao_bei_yang, None), ("阳胜进", check_yang_sheng_jin, None),
                                   ("阴胜出", check_yin_sheng_chu, None), ("长阴短柱", check_chang_duan_yin, atr_pct),
                                   ("阳包阴", check_yang_bao_yin, None), ("涨停板", check_ban_zhang, full_code),
                                   ("过左峰", check_guo_zuofeng, peak_20), ("极阴次阳", check_jiayin_ciyang, atr_pct),
                                   ("长阳矮柱", check_changyang_aizhu, atr_pct), ("倍量不穿", check_beiliang_buchuan, full_code),
                                   ("高量不破", check_gaoliang_bupo, None), ("地量群", check_diliang_qun, None),
                                   ("价升量缩", check_jiasheng_liangsou, None), ("倍量伸缩", check_beishuo_shensuo, None),
                                   ("回踩精准线", check_huicai_jingzhun, precise_price)]:
                ok, support = func(df, i, arg) if arg is not None else func(df, i)
                if ok: signals_today.append((name, support))

            # 3. 王牌柱
            if pillar_type != "无": signals_today.append((pillar_type, golden_line))

            # 4. 量线
            if valley_20 and abs(df.iloc[i]['low'] - valley_20) / valley_20 < TOUCH_TOLERANCE and df.iloc[i]['close'] > valley_20:
                signals_today.append(("回踩谷底线不破", valley_20))
            if big_yin_top and df.iloc[i]['close'] > big_yin_top:
                signals_today.append(("突破大阴实顶", big_yin_top))

            # 5. 价柱形态 & 背离
            price_pattern = identify_price_pattern(df, i, atr_pct)
            if price_pattern != "普通": signals_today.append((price_pattern, df.iloc[i]['close']))
            divergence_name, divergence_support = check_divergence(df, i)
            if divergence_name: signals_today.append((divergence_name, divergence_support))

            # 6. 主力意图
            for intent_name, intent_support in check_main_intent(position, stock_trend, vol_pattern, pillar_type, price_pattern):
                signals_today.append((intent_name, intent_support if intent_support else df.iloc[i]['close']))

            # 对每个信号，找回踩买入点
            for signal_name, support_price in signals_today:
                if signal_name == "阴胜出": continue
                buy_idx = check_pullback_buy(df, i, support_price)
                if buy_idx is None: continue
                buy_today, buy_yesterday = df.iloc[buy_idx], df.iloc[buy_idx - 1]
                if buy_today['open'] == buy_today['close'] and (buy_today['close'] - buy_yesterday['close']) / buy_yesterday['close'] * 100 > 9.5: continue
                bp = df.iloc[buy_idx]['open']
                is_real, quant_ratio = is_real_money(market, code, df.iloc[i]['date'])
                for hold_days in HOLD_PERIODS:
                    sell_idx = buy_idx + hold_days
                    if sell_idx >= n: continue
                    sp = df.iloc[sell_idx]['close']
                    if bp <= 0: continue
                    ret = (sp - bp) / bp * 100 - TOTAL_COST * 100
                    all_trades[signal_name][position][stock_trend][market_regime][hold_days].append((ret, is_real))

    # 输出结果（省略详细打印，保留核心JSON生成）
    print("\n" + "=" * 70)
    print("回测完成，正在生成 winrate.json ...")
    print("=" * 70)

    WINRATE_HOLD_DAYS = 20
    winrate_data = {}
    positions = ["低位", "中位", "高位"]
    stock_trends = ["上升趋势", "下降趋势"]
    market_regimes = ["牛市", "熊市", "未知"]

    for signal_name in all_trades:
        for pos in positions:
            if pos not in winrate_data: winrate_data[pos] = {}
            for trend in stock_trends:
                if trend not in winrate_data[pos]: winrate_data[pos][trend] = {}
                all_trades_list = []
                for regime in market_regimes: all_trades_list.extend(all_trades[signal_name][pos][trend][regime][WINRATE_HOLD_DAYS])

                all_returns = [t[0] for t in all_trades_list]
                count = len(all_returns)
                if count >= 5:
                    winrate_data[pos][trend][signal_name] = {
                        "win_rate": round(sum(1 for r in all_returns if r > 0) / count * 100, 1),
                        "avg_ret": round(float(np.mean(all_returns)), 2)
                    }

                real_returns = [t[0] for t in all_trades_list if t[1] is True]
                if len(real_returns) >= 5:
                    winrate_data[pos][trend][f"{signal_name}_真金"] = {
                        "win_rate": round(sum(1 for r in real_returns if r > 0) / len(real_returns) * 100, 1),
                        "avg_ret": round(float(np.mean(real_returns)), 2)
                    }

                quant_returns = [t[0] for t in all_trades_list if t[1] is False]
                if len(quant_returns) >= 5:
                    winrate_data[pos][trend][f"{signal_name}_量化"] = {
                        "win_rate": round(sum(1 for r in quant_returns if r > 0) / len(quant_returns) * 100, 1),
                        "avg_ret": round(float(np.mean(quant_returns)), 2)
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
