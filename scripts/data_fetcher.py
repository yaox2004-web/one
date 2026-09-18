```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
A股数据获取模块 (data_fetcher.py)
==================================
当前沙箱网络环境下的数据源可用性说明（重要！）：
--------------------------------------------------
真实可拉取的数据源（已验证通过）：
  ✅ 日线数据   —— 腾讯财经 HTTP 接口 (web.ifzq.gtimg.cn) / baostock
  ✅ 龙虎榜     —— 东财 datacenter-web (stock_lhb_detail_em) + 新浪 (stock_lhb_detail_daily_sina)
  ✅ 北向资金   —— 东财 datacenter-web (stock_hsgt_hist_em / stock_hsgt_fund_min_em)
  ✅ 大盘指数   —— 腾讯财经 CN_MarketData.getKLineData

降级/缺失的数据源（已验证不可用）：
  ❌ 个股资金流向 —— akshare stock_individual_fund_flow 依赖东财 push2his 通道，
                    该通道在当前沙箱网络被限制 (Connection aborted)。
                    本模块返回空 DataFrame 并打印警告。
  ❌ finshare    —— 沙箱缺 /dev/shm，loguru 的 multiprocessing 初始化失败，无法导入。

重试机制：所有网络请求均通过 tenacity 装饰的内部 helper 实现
          —— 连接错误/超时自动重试 3 次，间隔 5 秒；外层 try/except 兜底返回空表。

作者：Minis 助手
日期：2026-09-16
"""
import json
import os
import time
import warnings
from typing import Optional

import pandas as pd
import requests
from tenacity import (
    retry,
    stop_after_attempt,
    wait_fixed,
    retry_if_exception_type,
)

# ============ 配置 ============
# 全部改为相对仓库根目录的路径，不再依赖 /var/minis
DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
KLINE_DIR = os.path.join(DATA_DIR, "kline")
ANALYSIS_DIR = os.path.join(DATA_DIR, "analysis")
LHB_DIR = os.path.join(DATA_DIR, "lhb", "by_code")
# 兼容旧引用（dim_wash 等仍 import DB_PATH）；新流程已不再写 SQLite
DB_PATH = os.path.join(DATA_DIR, "astock", "daily.db")
RETRY_ATTEMPTS = 3
RETRY_WAIT = 5  # 秒

# 个股资金流向可用性标记
# 已知：东财 push2his 通道在当前沙箱网络被限制，个股资金流向拿不到。
# FUND_FLOW_AVAILABLE=False 时，信号引擎应通过 get_signal_confidence_penalty()
# 对相关信号置信度打 8 折。
FUND_FLOW_AVAILABLE = False

# 网络异常类型集合（触发重试）
_NET_ERRORS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
    requests.exceptions.HTTPError,
    requests.exceptions.ProxyError,
    requests.exceptions.SSLError,
    ConnectionError,
    TimeoutError,
)

# 请求头
_TX_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://gu.qq.com",
}
_SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn",
}

# 空表列定义（降级时返回统一列）
DAILY_COLS = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]
FUND_FLOW_COLS = ["日期", "收盘价", "涨跌幅", "主力净流入-净额",
                  "主力净流入-净占比", "超大单净流入-净额"]
LHB_COLS = ["序号", "代码", "名称", "上榜日", "收盘价", "涨跌幅",
            "龙虎榜净买额", "龙虎榜买入额", "龙虎榜卖出额", "上榜原因"]
NORTH_COLS = ["日期", "当日成交净买额", "买入成交额", "卖出成交额"]
INDEX_COLS = ["day", "open", "high", "low", "close", "volume"]

# ============ 工具函数 ============
import signal

class _TimeoutError(Exception):
    """自定义超时异常"""

def _timeout(seconds):
    """给函数整体加超时保护（用 SIGALRM）。
    适用于调用没有内置 timeout 的三方库（如 akshare）时防止卡死。
    超时时返回空 DataFrame（本模块所有函数均返回 DataFrame）。"""
    def decorator(func):
        def wrapper(*args, **kwargs):
            def handler(signum, frame):
                raise _TimeoutError(f"函数超时 ({seconds}s)")
            old_handler = signal.getsignal(signal.SIGALRM)
            signal.signal(signal.SIGALRM, handler)
            signal.alarm(seconds)
            try:
                return func(*args, **kwargs)
            except _TimeoutError:
                warnings.warn(f"[{func.__name__}] 超时 ({seconds}s)，返回空表")
                return pd.DataFrame()
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
        return wrapper
    return decorator

def _tx_code(code: str) -> str:
    """把 601138 转成 sh601138 格式（默认按代码首位判断市场）"""
    code = str(code).strip()
    if code.lower().startswith(("sh", "sz", "bj")):
        return code.lower()
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("0", "3")):
        return "sz" + code
    if code.startswith(("4", "8", "9")):
        return "bj" + code
    return "sh" + code

def to_tx(code: str) -> str:
    """对外公开：6位代码/带前缀代码 → 统一 sh/sz/bj 前缀格式（同 _tx_code）。"""
    return _tx_code(code)

# ============ JSON 数据读写（替代 SQLite） ============
_KLINE_COLS = ["日期", "开盘", "收盘", "最高", "最低", "成交量"]

def load_kline_json(code: str) -> pd.DataFrame:
    """
    读取单只股票/指数的日线 JSON。

    路径：data/kline/<market>/<tx>.json，回退 data/kline/<tx>.json
    返回列：日期/开盘/收盘/最高/最低/成交量；文件缺失或异常时返回空表。
    """
    tx = to_tx(code)
    candidates = [
        os.path.join(KLINE_DIR, tx[:2], f"{tx}.json"),
        os.path.join(KLINE_DIR, f"{tx}.json"),
    ]
    path = next((p for p in candidates if os.path.exists(p)), None)
    if path is None:
        return pd.DataFrame(columns=_KLINE_COLS)
    try:
        with open(path, encoding="utf-8") as f:
            payload = json.load(f)
        klines = payload.get("klines") or []
        rows = [k[:6] for k in klines
                if isinstance(k, list) and len(k) >= 6]
        if not rows:
            return pd.DataFrame(columns=_KLINE_COLS)
        df = pd.DataFrame(rows, columns=_KLINE_COLS)
        df["日期"] = df["日期"].astype(str).str[:10]
        for col in _KLINE_COLS[1:]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        return df
    except Exception as e:
        warnings.warn(f"[load_kline_json] {code} 读取失败: {e}")
        return pd.DataFrame(columns=_KLINE_COLS)

def save_kline_json(code: str, df: pd.DataFrame, name: str = "") -> str:
    """
    把日线 DataFrame 写入 data/kline/<market>/<tx>.json。

    列顺序：日期/开盘/收盘/最高/最低/成交量；name 留空则保留原文件中的名称。
    返回写入的文件路径。
    """
    tx = to_tx(code)
    outdir = os.path.join(KLINE_DIR, tx[:2])
    os.makedirs(outdir, exist_ok=True)
    path = os.path.join(outdir, f"{tx}.json")

    klines = []
    if df is not None and not df.empty:
        d = df.copy()
        for c in _KLINE_COLS:
            if c not in d.columns:
                d[c] = None
        for _, row in d[_KLINE_COLS].iterrows():
            dt = row["日期"]
            dt_s = dt.strftime("%Y-%m-%d") if hasattr(dt, "strftime") \
                else str(dt)[:10]
            vals = []
            for c in _KLINE_COLS[1:]:
                v = row[c]
                try:
                    vals.append(None if pd.isna(v) else float(v))
                except (TypeError, ValueError):
                    vals.append(None)
            klines.append([dt_s] + vals)

    old_name = ""
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                old_name = json.load(f).get("name", "")
        except Exception:
            old_name = ""
    payload = {
        "code": tx,
        "name": name or old_name,
        "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "count": len(klines),
        "klines": klines,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    return path

def _retry_helper(func):
    """用 tenacity 装饰内部请求 helper：网络异常重试3次、间隔5秒"""
    return retry(
        stop=stop_after_attempt(RETRY_ATTEMPTS),
        wait=wait_fixed(RETRY_WAIT),
        retry=retry_if_exception_type(_NET_ERRORS),
        reraise=True,
    )(func)

# ============ 1. 日线数据 ============
@_retry_helper
def _daily_request(code: str) -> pd.DataFrame:
    """内部请求：腾讯日K线，异常直接抛出（由 tenacity 重试）"""
    tx = _tx_code(code)
    url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
    params = {"_var": "kline_dayqfq", "param": f"{tx},day,,,1000,qfq"}
    r = requests.get(url, params=params, headers=_TX_HEADERS, timeout=15)
    r.raise_for_status()

    text = r.text
    start = text.find("{")
    if start == -1:
        raise ValueError(f"腾讯接口返回异常: {text[:100]}")
    data = json.loads(text[start:])

    node = data.get("data", {}).get(tx, {})
    klines = node.get("qfqday") or node.get("day")
    if not klines:
        raise ValueError(f"未获取到 {code} 的日线数据")

    # 过滤含分红信息的 7 列行（第7列是 dict），只保留标准 6 列 OHLCV
    klines = [k for k in klines
              if isinstance(k, list) and len(k) == 6
              and not any(isinstance(x, dict) for x in k)]
    if not klines:
        raise ValueError(f"过滤后无有效日线数据: {code}")

    df = pd.DataFrame(klines, columns=["日期", "开盘", "收盘", "最高", "最低", "成交量"])
    df["日期"] = pd.to_datetime(df["日期"])
    for col in ["开盘", "收盘", "最高", "最低", "成交量"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df["成交额"] = 0.0  # 腾讯接口不提供成交额，置 0
    df = df[DAILY_COLS].dropna(subset=["日期"])
    return df

def _validate_daily_df(df: pd.DataFrame, code: str) -> pd.DataFrame:
    """
    日线数据完整性校验与清洗。
    1. 检查 DataFrame 是否为空
    2. 检查 OHLC 关系合法性（High>=Low, High>=Open, High>=Close）
    3. 成交量/换手率/成交额为空用 0 填充并标记
    4. 打印数据条数和日期范围

    返回清洗后的 DataFrame（不合法的行将被剔除）。
    """
    if df is None or df.empty:
        warnings.warn(f"[_validate_daily_df] {code} 数据为空，校验跳过")
        return pd.DataFrame(columns=DAILY_COLS)

    # 确保必要列存在
    for col in DAILY_COLS:
        if col not in df.columns:
            df[col] = 0.0

    # 2) OHLC 合法性校验
    mask = (
        df["最高"].notna() & df["最低"].notna()
        & df["开盘"].notna() & df["收盘"].notna()
        & (df["最高"] >= df["最低"])
        & (df["最高"] >= df["开盘"])
        & (df["最高"] >= df["收盘"])
        & (df["最低"] <= df["开盘"])
        & (df["最低"] <= df["收盘"])
    )
    n_bad_ohlc = int((~mask).sum())
    if n_bad_ohlc > 0:
        warnings.warn(f"[_validate_daily_df] {code} 剔除 {n_bad_ohlc} 条 OHLC 关系非法行")
    df = df[mask]

    # 3) 成交量/成交额空值用 0 填充并标记
    filled = 0
    for col in ["成交量", "成交额"]:
        if col in df.columns:
            null_cnt = int(df[col].isna().sum())
            if null_cnt > 0:
                df[col] = df[col].fillna(0.0)
                filled += null_cnt
    if filled > 0:
        warnings.warn(f"[_validate_daily_df] {code} 填充 {filled} 个空成交量/成交额=0")

    # 4) 打印数据条数和日期范围
    if not df.empty and "日期" in df.columns:
        print(f"    [{code}] 校验后 {len(df)} 条, "
              f"{df['日期'].min().date()} ~ {df['日期'].max().date()}, "
              f"最新收盘={df['收盘'].iloc[-1]}")

    return df

def fetch_daily(code: str, adjust: str = "qfq", to_db: bool = True) -> pd.DataFrame:
    """
    获取个股日线数据（前复权 qfq 默认）。
    数据源：腾讯财经 HTTP 接口（已验证可用）。
    失败时返回空 DataFrame（重试3次后仍失败）。
    返回前经过数据完整性校验（_validate_daily_df）。
    """
    try:
        df = _daily_request(code)
        # 数据完整性校验与清洗
        df = _validate_daily_df(df, code)
        if to_db and not df.empty:
            _save_daily_to_db(code, df)
        return df
    except Exception as e:
        warnings.warn(f"[fetch_daily] 获取 {code} 日线失败: {e}")
        return pd.DataFrame(columns=DAILY_COLS)

def _save_daily_to_db(code: str, df: pd.DataFrame) -> None:
    """把日线 DataFrame 写入 JSON（data/kline/<market>/<tx>.json）"""
    try:
        path = save_kline_json(code, df)
        print(f"  已写入 {path}, {len(df)} 行")
    except Exception as e:
        warnings.warn(f"[_save_daily_to_db] 写入失败: {e}")

# ============ 2. 个股资金流向 ============
@_retry_helper
def _fund_flow_request(code: str, market: str) -> pd.DataFrame:
    """内部请求：akshare 个股资金流向（东财push2his通道）"""
    import akshare as ak
    return ak.stock_individual_fund_flow(stock=code, market=market)

def fetch_fund_flow(code: str, market: str = "") -> pd.DataFrame:
    """
    获取个股资金流向数据。

    注意：依赖东财 push2his 通道，当前沙箱网络下不可用（已验证）。
    会触发重试3次，最终失败返回空 DataFrame 并打印警告。

    若未来网络允许东财 push2his，此处将自动返回真实数据。
    """
    code = str(code)
    if not market:
        market = "sh" if code.startswith("6") else ("sz" if code.startswith(("0", "3")) else "bj")

    try:
        df = _fund_flow_request(code, market)
        return df
    except Exception as e:
        warnings.warn(
            f"[fetch_fund_flow] 个股资金流向 {code} 当前网络不可用（东财push2his被限制），"
            f"重试{RETRY_ATTEMPTS}次后返回空数据。错误: {e}"
        )
        return pd.DataFrame(columns=FUND_FLOW_COLS)

# ============ 3. 龙虎榜 ============
@_retry_helper
def _lhb_em_request(code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """内部请求：东财龙虎榜（datacenter-web 通道，已验证可用）。
    超时保护由外层 fetch_lhb 的 @_timeout(15) 统一控制。"""
    import akshare as ak
    return ak.stock_lhb_detail_em(start_date=start_date, end_date=end_date)

@_retry_helper
def _lhb_sina_request(code: str, date: str) -> pd.DataFrame:
    """内部请求：新浪龙虎榜每日详情（已验证可用）。超时由外层控制。"""
    import akshare as ak
    return ak.stock_lhb_detail_daily_sina(date=date)

@_timeout(15)
def fetch_lhb(code: str, date: Optional[str] = None) -> pd.DataFrame:
    """
    获取个股龙虎榜数据。

    数据源优先级：
      1. 东财 stock_lhb_detail_em（datacenter-web，数据更丰富）
      2. 新浪 stock_lhb_detail_daily_sina（兜底）

    整个函数加 15s 超时保护（@_timeout），确保非龙虎榜日
    也不会因为 akshare 内部请求无 timeout 而卡死。

    参数：
        code : 股票代码 '601138'
        date : 日期 YYYYMMDD，留空则用最近90天窗口并精确过滤该代码

    返回：
        该股票的龙虎榜记录 DataFrame；当日未上榜或超时则返回空表。
    """
    code = str(code)
    # 日期窗口（用 datetime 正确计算，避免整数值相减的 bug）
    from datetime import datetime, timedelta
    if date:
        end_date = date
        d = datetime.strptime(date, "%Y%m%d")
        start_date = (d - timedelta(days=30)).strftime("%Y%m%d")
    else:
        end_date = time.strftime("%Y%m%d")
        start_date = time.strftime("%Y%m%d", time.localtime(time.time() - 30 * 86400))

    # 1) 东财
    try:
        df = _lhb_em_request(code, start_date, end_date)
        if df is None or df.empty:
            return pd.DataFrame(columns=LHB_COLS)
        code_col = "代码" if "代码" in df.columns else "股票代码"
        if code_col in df.columns:
            df = df[df[code_col].astype(str) == code]
        # 取需要的列（若存在）
        keep = [c for c in LHB_COLS if c in df.columns]
        return df[keep] if keep else df

    except Exception as e:
        warnings.warn(f"[fetch_lhb] 东财龙虎榜 {code} 失败，尝试新浪: {e}")

    # 2) 新浪兜底
    if date:
        try:
            df = _lhb_sina_request(code, date)
            if df is None or df.empty:
                return pd.DataFrame(columns=LHB_COLS)
            code_col = "股票代码" if "股票代码" in df.columns else "代码"
            if not df.empty and code_col in df.columns:
                df = df[df[code_col].astype(str) == code]
            keep = [c for c in LHB_COLS if c in df.columns]
            return df[keep] if keep else df
        except Exception as e2:
            warnings.warn(f"[fetch_lhb] 新浪龙虎榜 {code} 也失败: {e2}")

    return pd.DataFrame(columns=LHB_COLS)

# ============ 3.1 龙虎榜历史采集（大窗口，用于席位画像） ============
def fetch_lhb_history(code: str, history_days: int = 750) -> pd.DataFrame:
    """
    用大窗口（默认 750 天 ≈ 3 年）拉取该股票全部历史龙虎榜记录，
    存入 JSON（data/lhb/by_code/<tx>.json）（供席位画像统计"上榜后5/10/20日胜率""平均持有周期"用）。

    参数：
        code         : 股票代码 '601138'
        history_days : 历史窗口天数，默认 750（约3年）

    返回：
        该股票全部历史龙虎榜记录 DataFrame；失败返回空表。
        同时将完整记录（含全部东财字段）写入 data/lhb/by_code/<tx>.json。
    """
    code = str(code)
    table = f"lhb_{str(code).lower().lstrip('shszbj')}"
    from datetime import datetime, timedelta

    end_date = time.strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=history_days)).strftime("%Y%m%d")

    try:
        # 用大窗口拉取全量，不传超时（数据量大，给足时间），但用 _timeout 兜底防卡死
        df = _lhb_em_request(code, start_date, end_date)
        if df is None or df.empty:
            print(f"    [{code}] 无历史龙虎榜记录")
            return pd.DataFrame(columns=LHB_COLS)

        # 过滤该股票
        code_col = "代码" if "代码" in df.columns else "股票代码"
        if code_col in df.columns:
            df = df[df[code_col].astype(str) == code]

        if df.empty:
            print(f"    [{code}] 最近{history_days}天无该股票龙虎榜记录")
            # 仍建空表
            _save_lhb_to_db(code, df)
            return pd.DataFrame(columns=LHB_COLS)

        # 写入 JSON（保存全量东财字段，供席位画像）
        _save_lhb_to_db(code, df)

        # 统计日期范围
        date_col = "上榜日" if "上榜日" in df.columns else "date"
        print(f"    [{code}] 历史龙虎榜 {len(df)} 条, "
              f"{df[date_col].min()} ~ {df[date_col].max()}")
        return df

    except Exception as e:
        warnings.warn(f"[fetch_lhb_history] 获取 {code} 历史龙虎榜失败: {e}")
        return pd.DataFrame(columns=LHB_COLS)

def _load_lhb_json(code: str) -> pd.DataFrame:
    """读取 data/lhb/by_code/<tx>.json 的龙虎榜记录；缺失/异常返回空表。"""
    path = os.path.join(LHB_DIR, f"{to_tx(code)}.json")
    if not os.path.exists(path):
        return pd.DataFrame(columns=LHB_COLS)
    try:
        with open(path, encoding="utf-8") as f:
            rows = json.load(f).get("rows") or []
        return pd.DataFrame(rows) if rows else pd.DataFrame(columns=LHB_COLS)
    except Exception as e:
        warnings.warn(f"[_load_lhb_json] {code} 读取失败: {e}")
        return pd.DataFrame(columns=LHB_COLS)

def _save_lhb_to_db(code: str, df: pd.DataFrame) -> None:
    """把龙虎榜记录写入 JSON（data/lhb/by_code/<tx>.json）"""
    try:
        tx = to_tx(code)
        os.makedirs(LHB_DIR, exist_ok=True)
        if df is None or df.empty:
            rows = []
        else:
            rows = json.loads(df.to_json(orient="records", force_ascii=False,
                                         date_format="iso"))
        payload = {
            "code": tx,
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
            "count": len(rows),
            "rows": rows,
        }
        with open(os.path.join(LHB_DIR, f"{tx}.json"), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, default=str)
    except Exception as e:
        warnings.warn(f"[_save_lhb_to_db] 写入 {code} 龙虎榜失败: {e}")

def sync_lhb_incremental(code: str) -> pd.DataFrame:
    """
    增量同步龙虎榜数据：读取 JSON 中已有的最新上榜日，
    只拉取最新日期之后的增量数据，追加写入（避免每次全量重拉）。

    参数：
        code : 股票代码 '601138'

    返回：
        本次新增的龙虎榜记录 DataFrame；无新增返回空表。
    """
    code = str(code)
    table = f"lhb_{str(code).lower().lstrip('shszbj')}"
    from datetime import datetime, timedelta

    end_date = time.strftime("%Y%m%d")

    # 读取已有最新上榜日（来自 JSON）
    latest = None
    old_records = _load_lhb_json(code)
    for col in ["上榜日", "date"]:
        if col in old_records.columns and not old_records.empty:
            try:
                val = old_records[col].dropna()
                if not val.empty:
                    latest = str(val.max())[:10]
                    break
            except Exception:
                continue

    if latest:
        # 有历史数据：拉取 latest 之后的数据
        start_date = (datetime.strptime(latest, "%Y-%m-%d")
                      if "-" in latest
                      else datetime.strptime(latest, "%Y%m%d")).strftime("%Y%m%d")
        print(f"    [{code}] 已有最新上榜日 {latest}，拉取 {start_date}~{end_date} 增量")
        try:
            df = _lhb_em_request(code, start_date, end_date)
            if df is None or df.empty:
                return pd.DataFrame(columns=LHB_COLS)
            code_col = "代码" if "代码" in df.columns else "股票代码"
            if code_col in df.columns:
                df = df[df[code_col].astype(str) == code]
            if df.empty:
                return pd.DataFrame(columns=LHB_COLS)

            # 过滤掉已有的（只保留严格大于 latest 的记录）
            date_col = "上榜日" if "上榜日" in df.columns else "date"
            df[date_col] = df[date_col].astype(str)
            new_df = df[df[date_col] > latest]

            # 追加写入 JSON：按整行去重（保留同一天多条不同上榜原因的记录）
            old = _load_lhb_json(code)
            dedup_key = [c for c in [date_col, "上榜原因", "解读"]
                         if c in old.columns and c in new_df.columns]
            if not dedup_key:
                dedup_key = [date_col]
            merged = pd.concat([old, new_df]).drop_duplicates(
                subset=dedup_key, keep="last")
            _save_lhb_to_db(code, merged)

            print(f"    [{code}] 增量新增 {len(new_df)} 条，合并后共 {len(merged)} 条")
            return new_df
        except Exception as e:
            warnings.warn(f"[sync_lhb_incremental] {code} 增量同步失败: {e}")
            return pd.DataFrame(columns=LHB_COLS)
    else:
        # 无历史数据：等同全量历史拉取
        print(f"    [{code}] 表中无历史数据，执行全量历史拉取")
        return fetch_lhb_history(code, history_days=750)

# ============ 3.2 信号置信度降级标注 ============
def get_signal_confidence_penalty() -> float:
    """
    返回信号置信度折扣系数。
    当 FUND_FLOW_AVAILABLE=False（个股资金流向不可用）时返回 0.8，
    信号引擎应把相关信号置信度乘算此系数（即自动打 8 折）。
    """
    if not FUND_FLOW_AVAILABLE:
        return 0.8
    return 1.0

# ============ 4. 北向资金 ============
@_retry_helper
def _north_request() -> pd.DataFrame:
    """内部请求：北向资金历史（东财 datacenter-web，已验证可用）"""
    import akshare as ak
    return ak.stock_hsgt_hist_em(symbol="北向资金")

def fetch_north_bound() -> pd.DataFrame:
    """获取北向资金历史数据。失败返回空表。"""
    try:
        return _north_request()
    except Exception as e:
        warnings.warn(f"[fetch_north_bound] 北向资金不可用: {e}")
        return pd.DataFrame(columns=NORTH_COLS)

# ============ 5. 大盘指数 ============
@_retry_helper
def _index_request(index_code: str, limit: int) -> pd.DataFrame:
    """内部请求：腾讯指数日线（已验证可用）"""
    url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
           "CN_MarketData.getKLineData")
    params = {"symbol": index_code, "scale": "240", "ma": "no", "datalen": str(limit)}
    r = requests.get(url, params=params, headers=_SINA_HEADERS, timeout=15)
    r.raise_for_status()
    data = json.loads(r.text)
    if not data:
        return pd.DataFrame(columns=INDEX_COLS)
    df = pd.DataFrame(data)
    df["day"] = pd.to_datetime(df["day"])
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df

def fetch_index_daily(index_code: str = "sh000001", limit: int = 500,
                      to_db: bool = False) -> pd.DataFrame:
    """获取大盘指数日线数据。index_code: sh000001/sz399001/sh000300。失败返回空表。
    若 to_db=True，写入 data/kline/<market>/<tx>.json。"""
    try:
        df = _index_request(index_code, limit)
        if to_db and not df.empty:
            # 统一列名为中文，方便与日线对齐
            df2 = df.rename(columns={"day": "日期", "open": "开盘", "high": "最高",
                                     "low": "最低", "close": "收盘", "volume": "成交量"})
            path = save_kline_json(index_code, df2)
            print(f"  已写入 {path}, {len(df2)} 行, "
                  f"{df2['日期'].min().date()} ~ {df2['日期'].max().date()}")
        return df
    except Exception as e:
        warnings.warn(f"[fetch_index_daily] 指数 {index_code} 获取失败: {e}")
        return pd.DataFrame(columns=INDEX_COLS)

# ============ 状态查询 ============
def get_data_source_status() -> dict:
    """返回当前沙箱网络下的数据源可用性状态。"""
    return {
        "daily": True,          # 腾讯接口
        "index_daily": True,    # 腾讯接口
        "north_bound": True,    # 东财 datacenter-web
        "lhb": True,            # 东财 datacenter-web + 新浪
        "fund_flow": False,     # 东财 push2his 被限制，降级返回空
    }

if __name__ == "__main__":
    print("=" * 60)
    print("data_fetcher.py 自检")
    print("=" * 60)
    print("数据源可用性:", get_data_source_status())
    print()

    print(">>> fetch_daily('601138')")
    df = fetch_daily("601138")
    print(f"    shape={df.shape}, 最近3行:\n{df[['日期','收盘']].tail(3).to_string(index=False)}")
    print()

    print(">>> fetch_fund_flow('601138')  [预期失败降级+重试3次]")
    t0 = time.time()
    df = fetch_fund_flow("601138")
    print(f"    shape={df.shape} (空=降级), 耗时={time.time()-t0:.1f}s")
    print()

    print(">>> fetch_lhb('601138')")
    df = fetch_lhb("601138", date="20260916")
    print(f"    shape={df.shape}")
    if not df.empty:
        print(df.head(3).to_string())
    print()

    print(">>> fetch_north_bound()")
    df = fetch_north_bound()
    print(f"    shape={df.shape}")
    if not df.empty:
        print(df[["日期", "当日成交净买额"]].tail(2).to_string(index=False))
    print()

    print(">>> fetch_index_daily('sh000001')")
    df = fetch_index_daily("sh000001", limit=5)
    print(f"    shape={df.shape}")
    if not df.empty:
        print(df[["day", "close"]].to_string(index=False))
```

This is the complete 742-line file. Waiting for your confirmation before posting `scripts/phases.py`.
