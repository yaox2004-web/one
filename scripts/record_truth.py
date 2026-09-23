#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真假量柱账本记录器 (record_truth.py) — 全市场按月分片版
=================================================
核心逻辑：
  1. 按"日期"分组1分钟K线
  2. 只记账"完整"的交易日（≥230根1分钟K线）
  3. 跳过"不完整"的当天（说明还在盘中）
  4. 按月份分片存储，防止单个文件过大
  5. 清理原始1分钟数据，节省仓库体积

账本存储结构：
  data/analysis/truth_ledger/2026-09.json
  data/analysis/truth_ledger/2026-10.json
  ...

时间规则（北京时间）：
  - 盘中：数据不完整 → 自动跳过
  - 盘后：数据完整 → 正常记账
  - 周末/节假日：接口返回最后交易日数据 → 自动识别
"""
import json
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ============================================================
# 路径配置
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data"
KLINE_1MIN_DIR = DATA_DIR / "kline_1min"
LEDGER_DIR = DATA_DIR / "analysis" / "truth_ledger"

# 完整交易日所需的1分钟K线数量
MIN_FULL_DAY_BARS = 230


def extract_date_from_timestamp(ts):
    """从时间戳提取日期（YYYY-MM-DD）"""
    s = str(ts).strip()
    if not s:
        return None
    if '-' in s:
        return s[:10]
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def analyze_1min_volatility(day_klines):
    """输入单日完整的1分钟K线，返回真假特征"""
    if not day_klines or len(day_klines) < MIN_FULL_DAY_BARS:
        return None, None, None, None, None, None

    volumes, closes = [], []
    for k in day_klines:
        try:
            if len(k) > 5:
                volumes.append(float(k[5]))
                closes.append(float(k[2]))
        except Exception:
            continue

    if len(volumes) < 30:
        return None, None, None, None, None, None

    vol_mean = np.mean(volumes)
    vol_std = np.std(volumes)
    cv = vol_std / vol_mean if vol_mean > 0 else 999

    if len(closes) == len(volumes) and len(closes) > 10:
        price_changes = np.diff(closes)
        vol_changes = np.diff(volumes)
        if np.std(price_changes) > 0 and np.std(vol_changes) > 0:
            corr = float(np.corrcoef(price_changes, vol_changes)[0, 1])
            if np.isnan(corr):
                corr = 0.0
        else:
            corr = 0.0
    else:
        corr = 0.0

    tail_vol = sum(volumes[-30:])
    total_vol = sum(volumes)
    tail_ratio = tail_vol / total_vol if total_vol > 0 else 0

    quant_score = 0
    if cv < 0.5: quant_score += 1
    if abs(corr) < 0.3: quant_score += 1
    if tail_ratio > 0.3: quant_score += 1

    if quant_score >= 2:
        verdict = "量化对倒"
        is_real = False
    elif quant_score == 1:
        verdict = "疑似量化"
        is_real = None
    else:
        verdict = "真金白银"
        is_real = True

    cv_contrib = 70 if cv < 0.5 else (40 if cv < 1.0 else 10)
    corr_contrib = 60 if abs(corr) < 0.2 else (30 if abs(corr) < 0.5 else 10)
    tail_contrib = 70 if tail_ratio > 0.4 else (40 if tail_ratio > 0.2 else 10)
    quant_pct = (cv_contrib + corr_contrib + tail_contrib) / 3

    return (verdict, is_real, round(quant_pct, 1),
            round(cv, 2), round(corr, 2), round(tail_ratio, 3))


def get_ledger_path(date_str):
    """根据日期返回账本文件路径（按月分片）"""
    month = date_str[:7]  # 例如 "2026-09"
    return LEDGER_DIR / f"{month}.json"


def load_ledger(date_str):
    """加载指定月份的账本"""
    path = get_ledger_path(date_str)
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_ledger(date_str, ledger):
    """安全保存账本"""
    path = get_ledger_path(date_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix('.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


def main():
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)

    bj_now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[账本] 北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[账本] 完整交易日标准: ≥{MIN_FULL_DAY_BARS}根1分钟K线")

    if not KLINE_1MIN_DIR.exists():
        print(f"[账本] 1分钟数据目录不存在，跳过")
        return

    files = list(KLINE_1MIN_DIR.glob("*.json"))
    if not files:
        print("[账本] 无1分钟数据文件，跳过")
        return

    print(f"[账本] 待处理 {len(files)} 个文件\n")

    # 按月份分组处理
    monthly_ledgers = {}  # {月份: {代码: {日期: {...}}}}
    updated = 0
    skipped_incomplete = 0
    skipped_exists = 0

    for f in files:
        code = f.stem
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            klines = data.get('klines', [])
            if not klines:
                continue

            # 按日期分组
            by_date = {}
            for k in klines:
                d = extract_date_from_timestamp(k[0])
                if d:
                    by_date.setdefault(d, []).append(k)

            for d, day_klines in sorted(by_date.items()):
                # 检查完整度
                if len(day_klines) < MIN_FULL_DAY_BARS:
                    skipped_incomplete += 1
                    continue

                # 加载对应月份的账本
                month = d[:7]
                if month not in monthly_ledgers:
                    monthly_ledgers[month] = load_ledger(d)

                ledger = monthly_ledgers[month]

                # 检查是否已记账
                if code in ledger and d in ledger[code]:
                    skipped_exists += 1
                    continue

                # 记账
                res = analyze_1min_volatility(day_klines)
                if res[0] is None:
                    continue

                verdict, is_real, quant_pct, cv, corr, tail = res

                if code not in ledger:
                    ledger[code] = {}
                ledger[code][d] = {
                    "is_real": is_real,
                    "verdict": verdict,
                    "quant_pct": quant_pct,
                    "cv": cv,
                    "corr": corr,
                    "tail_ratio": tail,
                }
                updated += 1
                if updated <= 20 or updated % 500 == 0:
                    print(f"  {code} {d} ✅ {verdict} (量化{quant_pct}%)")

        except Exception as e:
            print(f"  {code} 处理失败: {e}")

    # 保存所有月份账本
    for month, ledger in monthly_ledgers.items():
        save_ledger(f"{month}-01", ledger)
        total = sum(len(v) for v in ledger.values())
        print(f"[账本] {month}.json: {len(ledger)} 只股票, {total} 条记录")

    print(f"\n[统计] 更新: {updated} 条，跳过不完整: {skipped_incomplete} 条，已存在: {skipped_exists} 条")

    # 清理1分钟原始数据
    deleted = 0
    for f in files:
        try:
            f.unlink()
            deleted += 1
        except Exception:
            pass
    print(f"[清理] 已删除 {deleted} 个1分钟原始数据文件")


if __name__ == "__main__":
    main()
