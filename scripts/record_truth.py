#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真假量柱账本记录器 (record_truth.py) v2.0
=================================================
判定逻辑 v2（2026-09-30 校准）:
  v1.0 绝对阈值（CV<0.5 / 尾盘>0.3）与1分钟数据真实分布严重脱靶，
  实测（2026-09账本）: CV 0.78~1.70、尾盘占比 0.083~0.183，
  导致 ~90% 判为"疑似量化"，真金/量化两档几乎为空。
  v2 改为【历史相对分位】为主、【校准绝对阈值】为辅的双轨判定:
  - 该股有 ≥5 天账本历史 → 指标和自己过去20天比（分位）
  - 历史不足 → 用校准后的绝对阈值兜底
  - |量价相关| 无量纲，保留绝对阈值
  每条记录含 ver 字段，回测可按口径版本过滤。
"""

import json
import numpy as np
from datetime import datetime, timezone, timedelta
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
KLINE_1MIN_DIR = DATA_DIR / "kline_1min"
LEDGER_DIR = DATA_DIR / "analysis" / "truth_ledger"

MIN_FULL_DAY_BARS = 230
LEDGER_VERSION = 2

# ---- 指数不入账本：指数无"主力对倒"概念，入账只会稀释统计 ----
INDEX_CODES = {"sh000001", "sz399001", "sz399006"}

# ---- 校准后的绝对阈值（基于2026-09账本实测分布）----
CV_ABS_QUANT = 0.95      # 实测区间 0.78~1.70，下沿附近算"异常均匀"
TAIL_ABS_QUANT = 0.22    # 实测区间 0.083~0.183，明显高于常态算"尾盘做量"
CORR_ABS_QUANT = 0.30    # 相关系数无量纲，保留原值

# ---- 相对分位判定参数 ----
HISTORY_LOOKBACK = 20        # 用该股过去20天账本记录做基准
MIN_HISTORY_FOR_RELATIVE = 5 # 历史不足此数时退回绝对阈值
CV_RANK_LOW = 0.20           # CV处于自身历史最低20% → 量化特征
TAIL_RANK_HIGH = 0.80        # 尾盘占比处于自身历史最高20% → 量化特征

# ---- 连续打分的线性映射区间（用于 quant_pct）----
CV_MAP = (0.80, 1.40)        # cv<=0.80 → 100分(量化), >=1.40 → 0分
TAIL_MAP = (0.12, 0.25)      # tail>=0.25 → 100分, <=0.12 → 0分
CORR_MAP = (0.20, 0.40)      # |corr|<=0.20 → 100分, >=0.40 → 0分


def write_watchdog():
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    watchdog_path = LEDGER_DIR / "DO_NOT_MODIFY.md"
    content = """# ⚠️ 请勿手动修改此目录 ⚠️
本目录为量化系统的【历史账本】。账本由 `scripts/record_truth.py` 以
【只追加，不覆盖】的方式写入，代表历史真相。

## 严禁操作
- ❌ 手动修改 / 删除 / 重命名任意 .json 文件
- ❌ 通过 AI Agent 直接写入或 git push 本目录

## 如发现异常
- ✅ 唯一正确做法：git revert 回滚提交
- ✅ 记录含 ver 字段：ver=1 为旧口径（阈值脱靶，判定失真），ver=2 为校准后口径。
  回测统计时建议只取 ver>=2 的记录。
"""
    if not watchdog_path.exists():
        with open(watchdog_path, 'w', encoding='utf-8') as f:
            f.write(content)


def extract_date_from_timestamp(ts):
    s = str(ts).strip()
    if not s:
        return None
    if '-' in s:
        return s[:10]
    if len(s) >= 8 and s[:8].isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return None


def _pct_rank(value, arr):
    """value 在 arr 中的分位（0~1），arr为空返回None"""
    if not arr:
        return None
    return sum(1 for x in arr if x < value) / len(arr)


def _linear_score(value, lo, hi, invert=False):
    """线性映射到0~100。invert=True表示值越大越量化（尾盘占比用）"""
    if hi <= lo:
        return 0.0
    t = (value - lo) / (hi - lo)
    t = min(max(t, 0.0), 1.0)
    return round((1 - t if not invert else t) * 100, 1)


class HistoryIndex:
    """启动时把全部分片账本载入内存，供相对分位判定查询该股历史特征"""

    def __init__(self):
        self.data = {}  # {code: {date: entry}}
        if LEDGER_DIR.exists():
            for f in sorted(LEDGER_DIR.glob("*.json")):
                try:
                    with open(f, 'r', encoding='utf-8') as fp:
                        monthly = json.load(fp)
                    for code, dates in monthly.items():
                        self.data.setdefault(code, {}).update(dates)
                except Exception as e:
                    print(f"  [历史索引] 读取 {f.name} 失败: {e}")
        total = sum(len(v) for v in self.data.values())
        print(f"[账本] 历史索引: {len(self.data)} 只股票, {total} 条记录")

    def history(self, code, before_date):
        """返回该股 before_date 之前的 (cvs, |corrs|, tails) 列表"""
        entries = self.data.get(code, {})
        days = sorted(d for d in entries if d < before_date)[-HISTORY_LOOKBACK:]
        cvs = [entries[d]["cv"] for d in days if "cv" in entries[d]]
        corrs = [abs(entries[d]["corr"]) for d in days if "corr" in entries[d]]
        tails = [entries[d]["tail_ratio"] for d in days if "tail_ratio" in entries[d]]
        return cvs, corrs, tails


def analyze_1min_volatility(day_klines, hist_index, code, date_str):
    """输入单日完整1分钟K线 + 该股历史，返回 (verdict, is_real, quant_pct, cv, corr, tail)"""
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

    vol_mean, vol_std = np.mean(volumes), np.std(volumes)
    cv = vol_std / vol_mean if vol_mean > 0 else 999

    corr = 0.0
    if len(closes) == len(volumes) and len(closes) > 10:
        pc, vc = np.diff(closes), np.diff(volumes)
        if np.std(pc) > 0 and np.std(vc) > 0:
            corr = float(np.corrcoef(pc, vc)[0, 1])
            if np.isnan(corr):
                corr = 0.0
    abs_corr = abs(corr)

    total_vol = sum(volumes)
    tail_ratio = sum(volumes[-30:]) / total_vol if total_vol > 0 else 0

    # ===== 双轨判定：相对分位优先，绝对阈值兜底 =====
    cvs_h, corrs_h, tails_h = hist_index.history(code, date_str)
    use_relative = len(cvs_h) >= MIN_HISTORY_FOR_RELATIVE

    quant_score = 0
    if use_relative:
        cv_rank = _pct_rank(cv, cvs_h)
        tail_rank = _pct_rank(tail_ratio, tails_h)
        if cv_rank is not None and cv_rank <= CV_RANK_LOW:
            quant_score += 1
        if tail_rank is not None and tail_rank >= TAIL_RANK_HIGH:
            quant_score += 1
        basis = "相对分位"
    else:
        if cv <= CV_ABS_QUANT:
            quant_score += 1
        if tail_ratio >= TAIL_ABS_QUANT:
            quant_score += 1
        basis = "绝对阈值"
    if abs_corr < CORR_ABS_QUANT:   # 相关系数无量纲，始终用绝对阈值
        quant_score += 1

    if quant_score >= 2:
        verdict, is_real = "量化对倒", False
    elif quant_score == 1:
        verdict, is_real = "疑似量化", None
    else:
        verdict, is_real = "真金白银", True

    # ===== 连续 quant_pct（三指标线性打分取均值，替代阶跃贡献度）=====
    cv_score = _linear_score(cv, CV_MAP[0], CV_MAP[1])
    tail_score = _linear_score(tail_ratio, TAIL_MAP[0], TAIL_MAP[1], invert=True)
    corr_score = _linear_score(abs_corr, CORR_MAP[0], CORR_MAP[1])
    quant_pct = round((cv_score + tail_score + corr_score) / 3, 1)

    return (verdict, is_real, quant_pct,
            round(cv, 2), round(corr, 2), round(tail_ratio, 3))


def get_ledger_path(date_str):
    return LEDGER_DIR / f"{date_str[:7]}.json"


def load_ledger(date_str):
    path = get_ledger_path(date_str)
    if not path.exists():
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_ledger(date_str, ledger):
    path = get_ledger_path(date_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def main():
    write_watchdog()
    bj_now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[账本] 北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[账本] 判定口径: v{LEDGER_VERSION}（相对分位+校准绝对阈值双轨）")

    if not KLINE_1MIN_DIR.exists():
        print("[账本] 1分钟数据目录不存在，跳过")
        return
    files = list(KLINE_1MIN_DIR.glob("*.json"))
    if not files:
        print("[账本] 无1分钟数据文件，跳过")
        return

    hist_index = HistoryIndex()
    print(f"[账本] 待处理 {len(files)} 个文件\n")

    monthly_ledgers = {}
    failed_files = {}
    verdict_stats = {"量化对倒": 0, "疑似量化": 0, "真金白银": 0}
    updated = skipped_incomplete = skipped_exists = skipped_index = 0

    for f in files:
        code = f.stem
        if code in INDEX_CODES:
            skipped_index += 1
            continue
        try:
            with open(f, 'r', encoding='utf-8') as fp:
                data = json.load(fp)
            klines = data.get('klines', [])
            if not klines:
                continue

            by_date = {}
            for k in klines:
                d = extract_date_from_timestamp(k[0])
                if d:
                    by_date.setdefault(d, []).append(k)

            for d, day_klines in sorted(by_date.items()):
                if len(day_klines) < MIN_FULL_DAY_BARS:
                    skipped_incomplete += 1
                    continue
                month = d[:7]
                if month not in monthly_ledgers:
                    monthly_ledgers[month] = load_ledger(d)
                ledger = monthly_ledgers[month]

                # 只追加，不覆盖
                if code in ledger and d in ledger[code]:
                    skipped_exists += 1
                    continue

                res = analyze_1min_volatility(day_klines, hist_index, code, d)
                if res[0] is None:
                    failed_files.setdefault(f, []).append(d)
                    continue

                verdict, is_real, quant_pct, cv, corr, tail = res
                ledger.setdefault(code, {})[d] = {
                    "is_real": is_real,
                    "verdict": verdict,
                    "quant_pct": quant_pct,
                    "cv": cv,
                    "corr": corr,
                    "tail_ratio": tail,
                    "ver": LEDGER_VERSION,   # 口径版本，回测可过滤
                }
                updated += 1
                verdict_stats[verdict] += 1
                if updated <= 20 or updated % 500 == 0:
                    print(f"  {code} {d} ✅ {verdict} (量化{quant_pct}%)")

        except Exception as e:
            print(f"  {code} 处理失败: {e}")
            failed_files.setdefault(f, []).append(f"异常:{type(e).__name__}")

    for month, ledger in monthly_ledgers.items():
        save_ledger(f"{month}-01", ledger)
        print(f"[账本] {month}.json: {len(ledger)} 只股票, "
              f"{sum(len(v) for v in ledger.values())} 条记录")

    print(f"\n[统计] 更新: {updated} | 不完整跳过: {skipped_incomplete} | "
          f"已存在跳过: {skipped_exists} | 指数跳过: {skipped_index}")
    print(f"[分布] 真金白银: {verdict_stats['真金白银']} | "
          f"疑似: {verdict_stats['疑似量化']} | "
          f"量化对倒: {verdict_stats['量化对倒']}")
    if updated > 0 and verdict_stats["量化对倒"] == 0 and verdict_stats["真金白银"] == 0:
        print("[告警] ⚠️ 全部落在'疑似'一档——阈值可能再次脱靶，请检查实测分布！")

    deleted = kept = 0
    for f in files:
        if f.stem in INDEX_CODES:
            continue
        if failed_files.get(f):
            kept += 1
            print(f"[清理] ⚠️ 保留 {f.name}，记账失败需人工排查: {failed_files[f]}")
            continue
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            print(f"[清理] 删除失败 {f.name}: {e}")
    print(f"[清理] 删除 {deleted} 个，保留 {kept} 个待排查")


if __name__ == "__main__":
    main()
