#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真假量柱账本记录器 (record_truth.py) — 数据完整度自适应版
=================================================
核心逻辑：
  1. 按"日期"分组1分钟K线
  2. 只记账"完整"的交易日（≥230根1分钟K线）
  3. 跳过"不完整"的当天（说明还在盘中）
  4. 已记账的日期不重复记账（避免覆盖）
  5. 清理原始1分钟数据，节省仓库体积

时间规则（北京时间）：
  - 上午9:30-15:00 盘中：数据不完整 → 自动跳过
  - 下午15:00后：数据完整 → 正常记账
  - 周末/节假日：接口返回最后交易日数据 → 自动识别日期
  - 凌晨/任何时刻：用数据自身的时间戳判断归属日期
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

# 完整交易日所需的1分钟K线数量（A股每天240根，留10根容错）
MIN_FULL_DAY_BARS = 230


# ============================================================
# 从时间戳提取日期（兼容多种格式）
# ============================================================
def extract_date_from_timestamp(ts):
    """
    从时间戳字符串里提取日期（YYYY-MM-DD）。
    兼容：
      "202609221459"        -> "2026-09-22"
      "2026-09-22 14:59:00" -> "2026-09-22"
    """
    s = str(ts).strip()
    if not s:
        return None
    if '-' in s:
        return s[:10]
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


# ============================================================
# 真假量柱识别（输入是单日完整的1分钟K线）
# ============================================================
def analyze_1min_volatility(day_klines):
    """
    输入：某个交易日完整的1分钟K线（约240根）
    输出：(verdict, is_real, quant_pct, cv, corr, tail_ratio)
    """
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

    # 3. 尾盘占比（最后30根）
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

    # 北京时间（仅用于日志显示）
    bj_now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[账本] 当前北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[账本] 完整交易日标准: 至少 {MIN_FULL_DAY_BARS} 根1分钟K线")

    # 1. 加载已有账本
    ledger = {}
    if LEDGER_PATH.exists():
        try:
            with open(LEDGER_PATH, 'r', encoding='utf-8') as f:
                ledger = json.load(f)
            total = sum(len(v) for v in ledger.values())
            print(f"[账本] 已加载 {len(ledger)} 只股票，共 {total} 条历史记录")
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

    print(f"[账本] 待处理 {len(files)} 个文件\n")

    updated = 0
    skipped_incomplete = 0
    skipped_exists = 0

    for f in files:
        code = f.stem  # 例如 sh600584
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            klines = data.get('klines', [])
            if not klines:
                print(f"  {code} 无K线数据，跳过")
                continue

            # ========== 按日期分组 ==========
            by_date = {}
            for k in klines:
                d = extract_date_from_timestamp(k[0])
                if d:
                    by_date.setdefault(d, []).append(k)

            if not by_date:
                print(f"  {code} 无法解析时间戳，跳过")
                continue

            # ========== 遍历每个日期 ==========
            for d, day_klines in sorted(by_date.items()):
                # 检查1：数据完整度
                if len(day_klines) < MIN_FULL_DAY_BARS:
                    print(f"  {code} {d} 只有{len(day_klines)}根，盘中不完整，跳过")
                    skipped_incomplete += 1
                    continue

                # 检查2：是否已记账
                if code in ledger and d in ledger[code]:
                    print(f"  {code} {d} 已记账，跳过")
                    skipped_exists += 1
                    continue

                # ========== 记账 ==========
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
                print(f"  {code} {d} ✅ 记账: {verdict} (is_real={is_real}, 量化{quant_pct}%)")

        except Exception as e:
            print(f"  {code} 处理失败: {e}")

    # 3. 安全写入（原子操作）
    if updated > 0:
        tmp_path = LEDGER_PATH.with_suffix('.tmp')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(ledger, f, ensure_ascii=False, indent=2)
        tmp_path.replace(LEDGER_PATH)
        print(f"\n[账本] 已更新 {updated} 条记录 → {LEDGER_PATH}")
    else:
        print(f"\n[账本] 无新增记录")

    print(f"[统计] 跳过不完整: {skipped_incomplete} 条，已存在: {skipped_exists} 条")

    # 4. 清理1分钟原始数据（账本已留档）
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
