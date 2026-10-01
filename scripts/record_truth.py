#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
真假量柱账本记录器 (record_truth.py) v3.0
=================================================
版本历史:
  v1.0 (仓库版)     绝对阈值（CV<0.5/尾盘>0.3），实测严重脱靶：
                    ~90%误判"疑似量化"，且记账失败仍删原始数据
  v2.0 (2026-09-30) 双轨判定 + 校准阈值 + ver版本号 + 失败保命 + 指数剔除
  v2.1             新增量波特征（早盘量/尾盘量/脉冲数）入账本
  v2.2 (补丁C/B/D) 大盘量比market_vol_ratio + 残缺日保留策略 + 指数文件清理
  v3.0 (本版)      【1分钟数据深挖 Phase 0+1】新增7个行为指纹字段+3个审计字段：
                    vwap_hold_ratio / open_30min_pct / close_auction_pct /
                    pullup_slope / weave_score / pm_reversal / open_premium_pct
                    + bars / t_first / t_last（审计竞价段覆盖情况）
                    判定逻辑（verdict/is_real/quant_pct）与v2.2完全一致，零改动。

判定逻辑 v2（未变）:
  - 该股有 ≥5 天账本历史 → 指标和自己过去20天比（分位）
  - 历史不足 → 用校准后的绝对阈值兜底
  - |量价相关| 无量纲，保留绝对阈值
  每条记录含 ver 字段，回测可按口径版本过滤（ver>=2 才可信）。

★ 核心资产写入协议（不可违背）★
1. 本脚本是 truth_ledger/ 目录的【唯一写入者】。
2. 写入策略严格遵守【只追加，不覆盖】原则。
3. 账本代表【历史真相】，严禁修改/删除/回滚/清洗。
4. 如发现账本异常，唯一正确做法是【git revert 回滚提交】。
5. 1分钟数据"用一天少一天"：错过记账窗口，历史真相永久丢失。

核心流程:
  按日期分组1分钟K线 → 只记账"完整"交易日（≥230根）
  → 计算真假特征+量波特征+行为指纹 → 按月分片写入账本 → 删除原始数据
  → 记账失败的文件保留不删，次日重试
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

# 账本口径版本号（回测/报告按此过滤，v1为失真旧口径）
LEDGER_VERSION = 3

# ============================================================
# 指数不入账本：指数无"主力对倒"概念，入账只会稀释统计
# ============================================================
INDEX_CODES = {"sh000001", "sz399001", "sz399006"}

# ============================================================
# 校准后的绝对阈值（基于2026-09账本实测分布）
# ============================================================
CV_ABS_QUANT = 0.95
TAIL_ABS_QUANT = 0.22
CORR_ABS_QUANT = 0.30

# ============================================================
# 相对分位判定参数
# ============================================================
HISTORY_LOOKBACK = 20
MIN_HISTORY_FOR_RELATIVE = 5
CV_RANK_LOW = 0.20
TAIL_RANK_HIGH = 0.80

# ============================================================
# 连续打分的线性映射区间（用于 quant_pct）
# ============================================================
CV_MAP = (0.80, 1.40)
TAIL_MAP = (0.12, 0.25)
CORR_MAP = (0.20, 0.40)

# ============================================================
# 量波特征参数（与报告T3口径一致）
# ============================================================
WAVE_OPEN_BARS = 30
WAVE_CLOSE_BARS = 30
WAVE_SURGE_RATIO = 2.0

# ============================================================
# v3.0 行为指纹参数
# ============================================================
WEAVE_BAND = 0.015        # 织布机判定带宽：|close/vwap-1| < 1.5%
PM_MIN_MOVE = 0.001       # 午后反转判定的最小波动（0.1%）


# ============================================================
# 看门狗：在账本目录写入只读声明文件
# ============================================================
def write_watchdog():
    """在账本目录写入 DO_NOT_MODIFY.md，作为对外部读写者的警告。"""
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    watchdog_path = LEDGER_DIR / "DO_NOT_MODIFY.md"
    content = """# ⚠️ 请勿手动修改此目录 ⚠️

本目录为量化系统的【历史账本】。账本由 `scripts/record_truth.py` 以
【只追加，不覆盖】的方式写入，代表历史真相。

## 严禁操作
- ❌ 手动修改任意 .json 文件
- ❌ 删除任意 .json 文件
- ❌ 重命名或移动文件
- ❌ 通过 AI Agent（如 OpenMinis/MonkeyCode）直接写入或 git push

## 如发现异常
- ✅ 唯一正确的做法：回滚 Git 提交 (git revert)
- ✅ 联系脚本维护者，检查 record_truth.py 的写入逻辑

## 口径版本说明
- ver=1：旧口径（绝对阈值与1分钟数据真实分布脱靶，~90%误判"疑似量化"，
  判定结果不可信，但其 cv/corr/tail_ratio 原始指标仍有参考价值）
- ver=2：校准后口径（相对分位+校准绝对阈值双轨判定，可信）
- ver=3：v2口径 + 行为指纹字段（vwap_hold_ratio等7个）+ 审计字段（bars/t_first/t_last），
  判定逻辑与v2完全一致
- 回测统计时建议只取 ver>=2 的记录。
"""
    if not watchdog_path.exists():
        with open(watchdog_path, 'w', encoding='utf-8') as f:
            f.write(content)


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


def parse_hhmm(ts):
    """v3.0: 从时间戳提取当日分钟数（09:31 → 571）。
    兼容 '2026-10-09 09:31:00' 和 '20261009093100' 两种格式。"""
    digits = ''.join(ch for ch in str(ts) if ch.isdigit())
    if len(digits) >= 12:
        try:
            return int(digits[8:10]) * 60 + int(digits[10:12])
        except ValueError:
            return None
    return None


# ============================================================
# 工具函数
# ============================================================
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


def get_day_last_close(day_klines):
    """v3.0: 取某日最后一根有效K线的收盘价（用于次日open_premium_pct）"""
    last = None
    for k in day_klines:
        try:
            if len(k) > 5:
                last = float(k[2])
        except Exception:
            continue
    return last


# ============================================================
# 历史索引：启动时把全部分片账本载入内存，供相对分位判定查询
# ============================================================
class HistoryIndex:
    """把所有账本分片载入 {code: {date: entry}} 结构"""

    def __init__(self):
        self.data = {}
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


# ============================================================
# 核心分析：单日1分钟K线 → 真假特征 + 量波特征 + 行为指纹
# ============================================================
def analyze_1min_volatility(day_klines, hist_index, code, date_str, prev_close=None):
    """输入单日完整的1分钟K线 + 该股历史索引 + 前一交易日收盘价，
    返回账本条目 dict（失败返回 None）。
    v3.0: 判定逻辑（verdict/is_real/quant_pct）与v2.2逐字节一致；
          仅新增行为指纹字段与审计字段。"""

    if not day_klines or len(day_klines) < MIN_FULL_DAY_BARS:
        return None

    volumes, closes, hhmm = [], [], []
    for k in day_klines:
        try:
            if len(k) > 5:
                volumes.append(float(k[5]))
                closes.append(float(k[2]))
                hhmm.append(parse_hhmm(k[0]))
        except Exception:
            continue
    if len(volumes) < 30:
        return None

    vol_mean = np.mean(volumes)
    vol_std = np.std(volumes)
    cv = vol_std / vol_mean if vol_mean > 0 else 999

    corr = 0.0
    if len(closes) == len(volumes) and len(closes) > 10:
        price_changes = np.diff(closes)
        vol_changes = np.diff(volumes)
        if np.std(price_changes) > 0 and np.std(vol_changes) > 0:
            corr = float(np.corrcoef(price_changes, vol_changes)[0, 1])
            if np.isnan(corr):
                corr = 0.0
    abs_corr = abs(corr)

    total_vol = sum(volumes)
    tail_ratio = sum(volumes[-30:]) / total_vol if total_vol > 0 else 0

    # ---- 量波特征（v2.1，供报告T3"量波选时"使用）----
    vols_arr = np.array(volumes)
    total_v = vols_arr.sum()
    wave_morning = float(vols_arr[:30].sum() / total_v) if total_v > 0 else 0
    wave_close = float(vols_arr[-30:].sum() / total_v) if total_v > 0 else 0
    wave_pulses = int((vols_arr >= vols_arr.mean() * WAVE_SURGE_RATIO).sum())

    # ===== 双轨判定：相对分位优先，绝对阈值兜底（与v2.2一致）=====
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
    if abs_corr < CORR_ABS_QUANT:
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

    # ===== 连续 quant_pct（三指标线性打分取均值）=====
    cv_score = _linear_score(cv, CV_MAP[0], CV_MAP[1])
    tail_score = _linear_score(tail_ratio, TAIL_MAP[0], TAIL_MAP[1], invert=True)
    corr_score = _linear_score(abs_corr, CORR_MAP[0], CORR_MAP[1])
    quant_pct = round((cv_score + tail_score + corr_score) / 3, 1)

    # ===== v3.0 行为指纹（沙盘验证：5/7字段强分离）=====
    c = np.array(closes)
    v = np.array(volumes)
    entry = {
        "is_real": is_real,
        "verdict": verdict,
        "quant_pct": quant_pct,
        "cv": round(cv, 2),
        "corr": round(corr, 2),
        "tail_ratio": round(tail_ratio, 3),
        "wave_morning": wave_morning,
        "wave_close": wave_close,
        "wave_pulses": wave_pulses,
    }

    # 审计字段（Phase 0）：竞价段覆盖情况由 t_first/t_last 直接暴露
    entry["bars"] = len(c)
    if hhmm and hhmm[0] is not None:
        entry["t_first"] = f"{hhmm[0]//60:02d}:{hhmm[0]%60:02d}"
        entry["t_last"] = f"{hhmm[-1]//60:02d}:{hhmm[-1]%60:02d}"

    if total_v > 0:
        vwap = np.cumsum(c * v) / np.cumsum(v)
        entry["vwap_hold_ratio"] = round(float((c >= vwap).mean()), 3)
        entry["weave_score"] = round(float((np.abs(c / vwap - 1) < WEAVE_BAND).mean()), 3)
    if len(c) >= 30:
        entry["open_30min_pct"] = round(float((c[29] / c[0] - 1) * 100), 3)
    if len(c) >= 31:
        entry["pullup_slope"] = round(float((c[-1] / c[-31] - 1) * 100 / 30), 4)
        entry["close_auction_pct"] = round(float((c[-1] / c[-4] - 1) * 100), 3)
    # 午后反转：按时间切分上午/下午（无时间戳则用第120根兜底）
    if hhmm and hhmm[0] is not None:
        m = sum(1 for t in hhmm if t <= 11 * 60 + 30)
    else:
        m = min(120, len(c) - 1)
    if 1 < m < len(c) - 1:
        mr = c[m - 1] / c[0] - 1
        pr = c[-1] / c[m] - 1
        if abs(mr) > PM_MIN_MOVE and abs(pr) > PM_MIN_MOVE:
            entry["pm_reversal"] = 1 if np.sign(mr) != np.sign(pr) else 0
        else:
            entry["pm_reversal"] = None
    # 跨日溢价（前一交易日收盘价，来自同一文件的更早日期）
    if prev_close and prev_close > 0:
        entry["open_premium_pct"] = round(float((c[0] / prev_close - 1) * 100), 3)

    entry["_basis"] = basis  # 内部调试用，写入前剔除
    entry.pop("_basis", None)

    return entry


# ============================================================
# 账本读写（按月分片）
# ============================================================
def get_ledger_path(date_str):
    month = date_str[:7]
    return LEDGER_DIR / f"{month}.json"


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
    """安全保存账本（原子操作，防止中途崩溃损坏文件）"""
    path = get_ledger_path(date_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix('.tmp')
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)
    tmp_path.replace(path)


# ============================================================
# 【v2.2 补丁C】大盘背景量：上证当日量能 / 自身5日均量
# ============================================================
def load_market_volume():
    path = DATA_DIR / "kline" / "sh" / "sh000001.json"
    if not path.exists():
        print("[大盘量比] 指数日线数据缺失，market_vol_ratio 将为空")
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            klines = json.load(f).get('klines', [])
        dates, vols = [], []
        for k in klines:
            try:
                dates.append(str(k[0])[:10])
                vols.append(float(k[5]))
            except Exception:
                continue
        out = {}
        for i in range(len(dates)):
            prev = vols[max(0, i - 5):i]
            if prev and sum(prev) > 0:
                out[dates[i]] = round(vols[i] / (sum(prev) / len(prev)), 2)
        print(f"[大盘量比] 指数量比就绪: {len(out)} 天")
        return out
    except Exception as e:
        print(f"[大盘量比] 加载失败: {e}")
        return {}


# ============================================================
# 主函数
# ============================================================
def main():
    write_watchdog()

    bj_now = datetime.now(timezone.utc) + timedelta(hours=8)
    print(f"[账本] 北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')}")
    today_str = bj_now.strftime('%Y-%m-%d')
    print(f"[账本] 完整交易日标准: ≥{MIN_FULL_DAY_BARS}根1分钟K线")
    print(f"[账本] 判定口径: v{LEDGER_VERSION}（v2双轨判定 + 行为指纹字段）")
    print(f"[账本] 写入协议: 只追加，不覆盖")

    if not KLINE_1MIN_DIR.exists():
        print(f"[账本] 1分钟数据目录不存在，跳过")
        return

    files = list(KLINE_1MIN_DIR.glob("*.json"))
    if not files:
        print("[账本] 无1分钟数据文件，跳过")
        return

    hist_index = HistoryIndex()
    mkt_vol = load_market_volume()

    print(f"[账本] 待处理 {len(files)} 个文件\n")

    monthly_ledgers = {}
    failed_files = {}
    verdict_stats = {"量化对倒": 0, "疑似量化": 0, "真金白银": 0}
    updated = 0
    skipped_incomplete = 0
    skipped_exists = 0
    skipped_index = 0
    fingerprint_days = 0  # v3.0: 含行为指纹的记录数

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

            last_close_map = {}  # v3.0: {日期: 当日收盘}，供次日算溢价

            for d, day_klines in sorted(by_date.items()):
                # v3.0: 先取昨日收盘（无论今天是否已记账，昨日收盘都有效）
                prev_dates = [pd_ for pd_ in last_close_map if pd_ < d]
                prev_close = last_close_map[sorted(prev_dates)[-1]] if prev_dates else None

                # 更新收盘价缓存（即使今天残缺/已记账，明日仍可引用）
                day_last = get_day_last_close(day_klines)
                if day_last:
                    last_close_map[d] = day_last

                if len(day_klines) < MIN_FULL_DAY_BARS:
                    skipped_incomplete += 1
                    print(f"  [残缺] {code} {d} 仅{len(day_klines)}根(<{MIN_FULL_DAY_BARS})")
                    # 补丁B：只有"今天"的残缺日明天能补全→保留文件；
                    # 历史残缺日已超出640根滚动窗口，永远补不全，保留无意义
                    if d >= today_str:
                        failed_files.setdefault(f, []).append(f"残缺:{d}:{len(day_klines)}根")
                    continue

                month = d[:7]
                if month not in monthly_ledgers:
                    monthly_ledgers[month] = load_ledger(d)
                ledger = monthly_ledgers[month]

                # ★★★ 只追加，不覆盖：已存在的日期直接跳过 ★★★
                if code in ledger and d in ledger[code]:
                    skipped_exists += 1
                    continue

                entry = analyze_1min_volatility(day_klines, hist_index, code, d, prev_close)

                if entry is None:
                    failed_files.setdefault(f, []).append(d)
                    continue

                entry["market_vol_ratio"] = mkt_vol.get(d)
                entry["ver"] = LEDGER_VERSION

                ledger.setdefault(code, {})[d] = entry
                updated += 1
                verdict_stats[entry["verdict"]] += 1
                if "vwap_hold_ratio" in entry:
                    fingerprint_days += 1

                if updated <= 20 or updated % 500 == 0:
                    fp = f", vwap_hold={entry.get('vwap_hold_ratio')}" if "vwap_hold_ratio" in entry else ""
                    print(f"  {code} {d} ✅ {entry['verdict']} (量化{entry['quant_pct']}%{fp})")

        except Exception as e:
            print(f"  {code} 处理失败: {e}")
            failed_files.setdefault(f, []).append(f"异常:{type(e).__name__}")

    for month, ledger in monthly_ledgers.items():
        save_ledger(f"{month}-01", ledger)
        total = sum(len(v) for v in ledger.values())
        print(f"[账本] {month}.json: {len(ledger)} 只股票, {total} 条记录")

    print(f"\n[统计] 更新: {updated} 条（含行为指纹 {fingerprint_days} 条），跳过不完整: {skipped_incomplete} 条，"
          f"已存在: {skipped_exists} 条，指数跳过: {skipped_index} 条")
    print(f"[分布] 真金白银: {verdict_stats['真金白银']} | "
          f"疑似量化: {verdict_stats['疑似量化']} | 量化对倒: {verdict_stats['量化对倒']}")
    if updated > 0 and verdict_stats["量化对倒"] == 0 and verdict_stats["真金白银"] == 0:
        print("[告警] ⚠️ 全部落在'疑似'一档——阈值可能再次脱靶，请检查实测分布！")

    # ============ 清理原始1分钟数据 ============
    deleted = 0
    kept = 0
    for f in files:
        if f.stem in INDEX_CODES:
            try:
                f.unlink()
                deleted += 1
            except Exception:
                pass
            continue
        if failed_files.get(f):
            kept += 1
            print(f"[清理] ⚠️ 保留 {f.name}，完整交易日记账失败、需人工排查: {failed_files[f]}")
            continue
        try:
            f.unlink()
            deleted += 1
        except Exception as e:
            print(f"[清理] 删除失败 {f.name}: {e}")

    print(f"[清理] 已删除 {deleted} 个1分钟原始数据文件，保留 {kept} 个待排查文件")


if __name__ == "__main__":
    main()
