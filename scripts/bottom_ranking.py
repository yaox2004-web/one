#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json, os, sys
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data_fetcher import ANALYSIS_DIR, KLINE_DIR, load_kline_json

OUT_DIR = ANALYSIS_DIR
RAW_PATH = os.path.join(OUT_DIR, "bottom_ranking_raw.jsonl")
ALL_RAW = os.path.join(OUT_DIR, "signal_ranking_all_raw.jsonl")
COST = 1.1
HOLD = 5
FLUSH_EVERY = 200
LOG_EVERY = 50

def load_all_codes():
    codes = set()
    if not os.path.exists(ALL_RAW):
        return []
    with open(ALL_RAW, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                obj = json.loads(line)
                if obj.get("code"): codes.add(obj["code"])
            except: continue
    return sorted(codes)

def calc_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.rolling(period, min_periods=period).mean()
    avg_loss = loss.rolling(period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)

def calc_boll(close, period=20, num_std=2):
    ma = close.rolling(period, min_periods=period).mean()
    std = close.rolling(period, min_periods=period).std()
    return ma + num_std * std, ma, ma - num_std * std

def calc_obv(close, vol):
    direction = np.sign(close.diff().fillna(0))
    return (direction * vol).cumsum()

def detect_divergence(price, ind, lookback=60, bars_back=30):
    n = len(price)
    result = np.zeros(n, dtype=bool)
    p = price.values
    v = ind.values
    for i in range(lookback + bars_back, n):
        rp = p[i-bars_back:i+1]
        pp = p[i-bars_back-lookback:i-bars_back+1]
        if len(pp) < 10: continue
        if np.nanmin(rp) >= np.nanmin(pp) * 0.995: continue
        ri = np.argmin(rp)
        pi = np.argmin(pp)
        rv = v[i-bars_back+ri]
        pv = v[i-bars_back-lookback+pi]
        if np.isnan(rv) or np.isnan(pv): continue
        if rv > pv: result[i] = True
    return pd.Series(result, index=price.index)
def analyze_one(code, idx_above_map):
    df = load_kline_json(code)
    if df.empty or len(df) < 100: return {}
    df = df.copy()
    df["日期"] = pd.to_datetime(df["日期"])
    for c in ["开盘","收盘","最高","最低","成交量"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    close = df["收盘"]
    vol = df["成交量"]
    open_ = df["开盘"]
    rsi = calc_rsi(close, 14)
    bu, bm, bl = calc_boll(close, 20, 2)
    obv = calc_obv(close, vol)
    vol5 = vol.rolling(5, min_periods=1).mean()
    vol20 = vol.rolling(20, min_periods=1).mean()
    ma20 = close.rolling(20, min_periods=1).mean()
    # 1 RSI底背离
    rsi_div = detect_divergence(close, rsi, 60, 30)
    s1 = rsi_div & (vol.shift(-1) > vol5.shift(-1)*1.5) & (close.shift(-1) > open_.shift(-1))
    # 2 缩量极致阳盖
    ve = vol < vol20 * 0.5
    near = (close >= ma20*0.97) & (close <= ma20*1.03)
    yg = (close.shift(-1) > open_.shift(-1)) & (close.shift(-1) > close.shift(-2)) & (close.shift(-1) > open_.shift(-2))
    s2 = ve & near & yg
    # 3 布林下轨反弹
    tl = close <= bl * 1.005
    ro = rsi < 30
    s3 = tl & ro & (vol.shift(-1) > vol5.shift(-1)*1.3) & (close.shift(-1) > open_.shift(-1))
    # 4 OBV底背离
    od = detect_divergence(close, obv, 60, 30)
    s4 = od & (vol.shift(-1) > vol5.shift(-1)*1.3) & (close.shift(-1) > open_.shift(-1))
    results = {}
    for name, sig in [("RSI底背离",s1),("缩量极致阳盖",s2),("布林下轨反弹",s3),("OBV底背离",s4)]:
        sig = sig.fillna(False).to_numpy()
        rets = []
        for i in range(20, len(df)-HOLD-1):
            if not sig[i]: continue
            ds = df["日期"].iloc[i].strftime("%Y-%m-%d")
            if not idx_above_map.get(ds, True): continue
            bi, si = i+1, i+HOLD
            if si >= len(close): continue
            bp, sp = close.iloc[bi], close.iloc[si]
            if bp <= 0: continue
            rets.append((sp/bp - 1.0)*100 - COST)
        results[name] = rets
    return results

def load_raw():
    ar, done = {}, set()
    if not os.path.exists(RAW_PATH): return ar, done
    with open(RAW_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: obj = json.loads(line)
            except: continue
            if not obj.get("code"): continue
            done.add(obj["code"])
            for k,v in obj.get("results",{}).items():
                ar.setdefault(k,[]).extend(v)
    return ar, done

def main():
    codes = load_all_codes()
    if not codes: print("无全市场列表"); return
    idx_df = load_kline_json("sh000001")
    idx_df["日期"] = pd.to_datetime(idx_df["日期"])
    ic = idx_df.set_index("日期")["收盘"].sort_index()
    im = ic.rolling(20, min_periods=1).mean()
    iam = {d.strftime("%Y-%m-%d"): bool(v) for d,v in (ic >= im).items()}
    print(f"全市场 {len(codes)} 只")
    ar, done = load_raw()
    todo = [c for c in codes if c not in done]
    print(f"已完成 {len(done)} | 待跑 {len(todo)}")
    os.makedirs(OUT_DIR, exist_ok=True)
    fh = open(RAW_PATH, "a", encoding="utf-8")
    try:
        for pi, code in enumerate(todo):
            try: res = analyze_one(code, iam)
            except Exception as e:
                print(f"  跳过 {code}: {e}"); res = {}
            for k,v in res.items(): ar.setdefault(k,[]).extend(v)
            fh.write(json.dumps({"code":code,"results":res},ensure_ascii=False)+"\n")
            if (pi+1) % LOG_EVERY == 0: print(f"  进度 {pi+1}/{len(todo)}")
            if (pi+1) % FLUSH_EVERY == 0: fh.flush()
        fh.flush()
    finally:
        fh.close()
    rows = []
    for name in sorted(ar):
        arr = np.array(ar[name]) if ar[name] else np.array([0])
        rows.append({"信号名":name,"次数":len(ar[name]),"中位%":round(float(np.median(arr)),2),"均值%":round(float(np.mean(arr)),2),"胜率%":round(float((arr>0).mean()*100),1)})
    df = pd.DataFrame(rows).sort_values("中位%", ascending=False)
    df.to_csv(os.path.join(OUT_DIR,"bottom_ranking.csv"), index=False, encoding="utf-8-sig")
    print("\n=== 结果（T+1+成本1.1%+MA20上+持有5日）===")
    print(df.to_string(index=False))

if __name__ == "__main__":
    main()

