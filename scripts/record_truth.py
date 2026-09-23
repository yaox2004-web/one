#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真假量柱账本记录器 (record_truth.py)
=================================================
功能：
  1. 读取当天1分钟数据，计算真假量柱特征
  2. 写入 data/analysis/truth_ledger.json（永久留档）
  3. 删除原始1分钟数据，节省仓库体积
核心修复：
  从1分钟数据里读取"实际日期"作为记账日期，而非用当前系统日期。
  避免凌晨跑的时候，把昨天数据记成今天。
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
ANALYSIS_DIR = DATA_DIR / "analysis"
LEDGER_PATH = ANALYSIS_DIR / "truth_ledger.json"


# ============================================================
# 从时间戳提取日期（兼容多种格式）
# ============================================================
def extract_date_from_timestamp(ts):
    """
    从时间戳字符串里提取日期（YYYY-MM-DD）。
    兼容两种格式：
      "202609221459"  -> "2026-09-22"
      "2026-09-22 14:59:00" -> "2026-09-22"
    """
    s = str(ts).strip()
    if not s:
        return None
    # 带横杠格式
    if '-' in s:
        return s[:10]
    # 纯数字格式（YYYYMMDDHHMM）
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


# ============================================================
# 真假量柱识别（与 level4d_report_html.py 逻辑一致）
# ============================================================
def analyze_1min_volatility(klines):
    """返回 (verdict, is_real, quant_pct, cv, corr, tail_ratio)"""
    if not klines or len(klines) < 60:
        return None, None, None, None, None, None

    day_klines = klines[-240:] if len(klines) >= 240 else klines
    if len(day_klines) < 30:
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

    # 1. 成交量CV
    vol_mean = np.mean(volumes)
    vol_std = np.std(volumes)
    cv = vol_std / vol_mean if vol_mean > 0 else 999

    # 2. 量价相关系数
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

    # 3. 尾盘占比
    tail_vol = sum(volumes[-30:])
    total_vol = sum(volumes)
    tail_ratio = tail_vol / total_vol if total_vol > 0 else 0

    # 综合判断
    quant_score = 0
    if cv < 0.5:
        quant_score += 1
    if abs(corr) < 0.3:
        quant_score += 1
    if tail_ratio > 0.3:
        quant_score += 1

    if quant_score >= 2:
        verdict = "量化对倒"
        is_real = False
    elif quant_score == 1:
        verdict = "疑似量化"
        is_real = None
    else:
        verdict = "真金白银"
        is_real = True

    # 量化占比估算
    cv_contrib = 70 if cv < 0.5 else (40 if cv < 1.0 else 10)
    corr_contrib = 60 if abs(corr) < 0.2 else (30 if abs(corr) < 0.5 else 10)
    tail_contrib = 70 if tail_ratio > 0.4 else (40 if tail_ratio > 0.2 else 10)
    quant_pct = (cv_contrib + corr_contrib + tail_contrib) / 3

    return (
        verdict,
        is_real,
        round(quant_pct, 1),
        round(cv, 2),
        round(corr, 2),
        round(tail_ratio, 3),
    )


# ============================================================
# 主流程
# ============================================================
def main():
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. 加载已有账本
    ledger = {}
    if LEDGER_PATH.exists():
        try:
            with open(LEDGER_PATH, 'r', encoding='utf-8') as f:
                ledger = json.load(f)
            total = sum(len(v) for v in ledger.values())
            print(f"[账本] 已加载 {len(ledger)} 只股票，共 {total} 条记录")
        except Exception as e:
            print(f"[账本] 读取失败，重新开始: {e}")
            ledger = {}

    # 2. 遍历1分钟数据文件
    if not KLINE_1MIN_DIR.exists():
        print(f"[账本] 1分钟数据目录不存在: {KLINE_1MIN_DIR}")
        return

    files = list(KLINE_1MIN_DIR.glob("*.json"))
    if not files:
        print("[账本] 无1分钟数据文件，跳过")
        return

    print(f"[账本] 待处理 {len(files)} 个文件")

    updated = 0
    for f in files:
        code = f.stem  # 例如 sh600584
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            klines = data.get('klines', [])
            if not klines:
                print(f"  {code} 无K线数据，跳过")
                continue

            # ==========================================
            # 关键修复：从最后一条K线数据里提取实际日期
            # ==========================================
            data_date = extract_date_from_timestamp(klines[-1][0])
            if not data_date:
                print(f"  {code} 无法解析时间戳: {klines[-1][0]}，跳过")
                continue

            res = analyze_1min_volatility(klines)
            if res[0] is None:
                print(f"  {code} 数据不足，跳过")
                continue

            verdict, is_real, quant_pct, cv, corr, tail = res

            if code not in ledger:
                ledger[code] = {}
            ledger[code][data_date] = {
                "is_real": is_real,
                "verdict": verdict,
                "quant_pct": quant_pct,
                "cv": cv,
                "corr": corr,
                "tail_ratio": tail,
            }
            updated += 1
            print(f"  {code} 记账到 {data_date}: {verdict} (is_real={is_real})")
        except Exception as e:
            print(f"  {code} 处理失败: {e}")

    # 3. 安全写入
    if updated > 0:
        tmp_path = LEDGER_PATH.with_suffix('.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, ensure_ascii=False, indent=2)
        tmp_path.replace(LEDGER_PATH)
        print(f"[账本] 已更新 {updated} 条记录 → {LEDGER_PATH}")
    else:
        print("[账本] 无新增记录")

    # 4. 清理1分钟原始数据
    deleted = 0
    for f in files:
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            print(f"  删除失败 {f.name}: {e}")
    print(f"[清理] 已删除 {deleted} 个1分钟原始数据文件")


if __name__ == "__main__":
    main()
