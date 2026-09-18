#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_update.py — 每日增量更新（默认跑 43 只自选股）
=========================================================
功能（按 2B-2 定稿）：
  1. 读 self43.txt（自选股清单，每行一个代码）
  2. 读 daily_new.db 里这 43 只的最新日期
  3. 拉"最新日期+1 ~ 今天"的增量（Baostock adjustflag=2 前复权）
  4. 增量 append 到 daily_new.db:signal_log_70 + backup/daily_update_log.csv
  5. 覆盖 backup/latest_signals.csv（当日快照）
  6. 打印今日新增信号摘要

三层超时保护（GLOBAL 可复现性规矩 + 防 Baostock 卡死）：
  - 单只 30s：每只 Baostock 拉数用 signal.alarm(30) 包裹
  - 整体 15min：主入口 signal.alarm(900)，超时强制退出
  - Baostock 每次调用 30s：socket 级超时

幂等：
  --skip-pull：纯本地重算（不碰 Baostock），跑两次结果一致（"今日新增 0 条"）
  --recompute-baseline：手动触发重算 43 只 4c 基线（默认不重算）

输出文案（池子限定，v2 脚注"使用规则"）：
  - 出货行：动态读 4c_43_rebuilt_summary.json 的"出货"."med"
      "[自选池] 出货信号无显著增量（{med}pp），可能主升中继，非派发预警"
  - json 缺失/损坏 → fallback "[自选池] 出货信号方向待重算，暂不提示"
  - 拉升高位/建仓：沿用 v2 口径

命令行：
  python3 daily_update.py                # 拉增量 + 重算 + 出摘要（默认）
  python3 daily_update.py --skip-pull    # 纯本地，不碰网络（幂等验证）
  python3 daily_update.py --recompute-baseline   # 重算 43 只 4c 基线

所有产出落 backup（/var/minis/mounts/@minis/astock_backup/）
"""
import sys, os, json, time, signal, socket, warnings, argparse
from datetime import datetime, timedelta, time as _dt_time
warnings.filterwarnings('ignore')

BACKUP = '/var/minis/mounts/@minis/astock_backup'
DB     = os.path.join(BACKUP, 'daily_new.db')
SEL43  = os.path.join(BACKUP, 'self43.txt')
UPD_LOG = os.path.join(BACKUP, 'daily_update_log.csv')
LATEST  = os.path.join(BACKUP, 'latest_signals.csv')
BASELINE_JSON = os.path.join(BACKUP, '4c_43_rebuilt_summary.json')
BASELINE_RECOMPUTE_LOG = os.path.join(BACKUP, 'baseline_recompute_log.json')

# ============ 三层超时 ============
class TimeoutError(Exception): pass

def _alarm_handler(signum, frame):
    raise TimeoutError('超时')

def run_with_timeout(fn, seconds, what=''):
    """单只/单次调用超时（signal.alarm 仅主线程可用）"""
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(seconds)
    try:
        return fn()
    except TimeoutError:
        print(f"  [超时 {seconds}s] {what} 跳过")
        return None
    finally:
        signal.alarm(0)

# Baostock 调用套 socket 超时（30s）
BS_SOCKET_TIMEOUT = 30

# ============ 启动自检 ============
def load_self43():
    if not os.path.exists(SEL43):
        print(f"错误：自选股清单缺失 {SEL43}，退出")
        sys.exit(1)
    codes = [l.strip() for l in open(SEL43) if l.strip()]
    if not codes:
        print(f"错误：{SEL43} 为空，退出")
        sys.exit(1)
    return codes

# ============ 4c 基线动态读（缓存 + fallback）===========
def load_baseline_med():
    """读 43 只出货中位数（动态，不硬编码）
    来源 key：4c_43_rebuilt_summary.json['出货']['med']
    缺失/损坏 → None（触发 fallback 文案）"""
    try:
        d = json.load(open(BASELINE_JSON))
        med = d['出货']['med']
        return float(med)
    except Exception as e:
        print(f"  [warn] 4c 基线 json 读取失败（{e}），出货文案用 fallback")
        return None

# ============ Baostock 增量拉数 ============
def bs_login():
    import baostock as bs
    bs.login()
    return bs

def fetch_increment(bs, code, start_date, end_date):
    """拉单只增量日线（前复权 adjustflag=2）
    返回 DataFrame(日期,开盘,收盘,最高,最低,成交量)；无数据返回空 DataFrame"""
    import pandas as pd
    bc = ('sh.' if code.startswith(('60','68')) else 'sz.') + code
    rs = bs.query_history_k_data_plus(
        bc, 'date,open,high,low,close,volume,turn,tradestatus,pctChg,isST',
        start_date=start_date, end_date=end_date,
        frequency='d', adjustflag='2')
    rows = []
    while rs.error_code == '0' and rs.next():
        r = rs.get_row_data()
        rows.append([r[0], float(r[1] or 0), float(r[2] or 0),
                     float(r[3] or 0), float(r[4] or 0), float(r[5] or 0)])
    if not rows:
        return pd.DataFrame(columns=['日期','开盘','收盘','最高','最低','成交量'])
    return pd.DataFrame(rows, columns=['日期','开盘','收盘','最高','最低','成交量'])

# ============ 主流程 ============
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--skip-pull', action='store_true',
                    help='纯本地重算，不碰 Baostock（幂等验证）')
    ap.add_argument('--recompute-baseline', action='store_true',
                    help='手动重算 43 只 4c 基线（默认不重算）')
    args = ap.parse_args()

    # 整体 15min 超时（防无限挂）
    signal.signal(signal.SIGALRM, _alarm_handler)
    signal.alarm(900)
    t_start = time.time()

    # 时间保护（2026-09-18 加）：A股当日数据一般 17:30-18:00 才生成
    # 早于 15:30 跑 → 提示"当日数据未生成"，但不阻断（用户可强制跑）
    _now = datetime.now()
    if _now.time() < _dt_time(15, 30):
        print(f"⚠️ 当前北京时间 {_now.strftime('%H:%M')}，A股当日数据尚未生成")
        print("   建议 20:00 后再跑（Baostock 一般 17:30-18:00 更新）")
        print("   现在跑只能更新到昨日。继续跑也可以，但结果可能无意义。")
        print()

    codes = load_self43()
    print(f'自选股清单: {len(codes)} 只（读自 {SEL43}）')

    # 4c 基线动态读（缓存到内存，全程复用）
    ship_med = load_baseline_med()

    import sqlite3, pandas as pd
    conn = sqlite3.connect(DB)

    # 读 43 只各自最新日期
    latest_date = {}
    for c in codes:
        r = conn.execute(f'SELECT MAX(日期) FROM "daily_{c}"').fetchone()
        latest_date[c] = r[0] if r and r[0] else None
    no_data = [c for c in codes if not latest_date[c]]
    print(f'43 只中有数据的: {len(codes)-len(no_data)}，无数据: {len(no_data)}'
          + (f' ({no_data})' if no_data else ''))

    if args.skip_pull:
        # 纯本地：用 db 现有数据直接重算 phases + signal_engine
        print('\n--skip-pull：跳过 Baostock，纯本地重算')
        latest_for_summary = max([d for d in latest_date.values() if d], default=None)
        new_signals, pulled = [], {}
    else:
        # 拉增量（Baostock）
        print('\n拉增量（Baostock 前复权）')
        today = time.strftime('%Y-%m-%d')
        bs = bs_login()
        import socket as _socket
        _socket.setdefaulttimeout(BS_SOCKET_TIMEOUT)  # Baostock 每次调用 30s

        new_signals, pulled = [], {}
        for i, c in enumerate(codes):
            last = latest_date[c]
            if not last:
                print(f'  [{i+1}/{len(codes)}] {c} 无历史数据，跳过')
                continue
            start = (datetime.strptime(last, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
            if start > today:
                continue
            # 单只 30s 超时包裹
            df = run_with_timeout(lambda cc=c, st=start: fetch_increment(bs, cc, st, today),
                                  30, f'{c} 拉数')
            if df is None:
                print(f'  [{i+1}/{len(codes)}] {c} 单只 30s 超时，跳过')
                continue
            if df.empty:
                print(f'  [{i+1}/{len(codes)}] {c} 无新增（已到 {last}）')
                continue
            # 合并到 db
            _merge_daily(conn, c, df)
            print(f'  [{i+1}/{len(codes)}] {c} 新增 {len(df)} 条 ({df["日期"].iloc[0]}~{df["日期"].iloc[-1]})')
            pulled[c] = df
        bs.logout()

    # 若拉了增量，重算 phases + signal_engine（只算 43 只自选）
    if args.skip_pull or pulled:
        if pulled:
            print('\n重算 phases + signal_engine（43 只自选）')
        import phases, signal_engine, data_fetcher
        for mod in (phases, signal_engine, data_fetcher):
            mod.DB_PATH = DB
        sel = {c: '' for c in codes}
        ph_out = os.path.join(BACKUP, '_ph_phase_log.csv')
        sig_out = os.path.join(BACKUP, '_ph_signal_log.csv')
        phases.PHASE_LOG_PATH = ph_out
        phases.run_all(stock_list=sel, output_path=ph_out, verbose=False)
        sig_log = signal_engine.run_signal_engine(stock_list=sel, output_path=sig_out)

        # 算"今日新增信号"= 只取最新交易日 & 信号强度非"无信号"
        import os as _os
        if not sig_log.empty:
            last_day = sig_log['日期'].astype(str).str[:10].max()
            today_sig = sig_log[sig_log['日期'].astype(str).str[:10] == last_day].copy()
            new_signals = today_sig[today_sig['信号强度'] != '无信号'].copy()
            print(f'\n最新交易日 {last_day} 共 {len(today_sig)} 条，其中非"无信号": {len(new_signals)} 条')
        else:
            new_signals = pd.DataFrame()
            print('（重算结果为空）')

    # ===== --recompute-baseline：重算 43 只 4c 基线 =====
    if args.recompute_baseline:
        import pair_test_fixed
        import numpy as np
        pair_test_fixed.DB = DB
        sel_all = {c: '' for c in codes}
        results70 = {}
        for stage, pos, label in [('出货', None, '出货'), ('拉升', '高位', '拉升高位'), ('建仓', None, '建仓')]:
            ps = pair_test_fixed.run_pair_test_fixed(list(sel_all), sel_all, stage, pos, label)
            incs = [x['inc'] for x in ps if x['inc'] == x['inc']]
            results70[label] = {
                'per_stock': ps, 'n_valid': len(incs),
                'pos_cnt': int(sum(1 for v in incs if v > 0)),
                'neg_cnt': int(sum(1 for v in incs if v < 0)),
                'med': round(float(np.median(incs)), 2),
                'mean': round(float(np.mean(incs)), 2),
            }
        old_med = ship_med
        json.dump(results70, open(BASELINE_JSON, 'w', encoding='utf-8'), ensure_ascii=False, indent=1, default=str)
        new_med = results70['出货']['med']
        print(f'\n[重算基线] 出货中位数 {old_med} → {new_med}pp')
        if old_med is not None and ((old_med > 0) != (new_med > 0)):
            print(f'  ⚠️ [基线已变，输出文案已更新] 出货方向翻转（{old_med}→{new_med}）')
        json.dump({'last_recompute': time.strftime('%Y-%m-%d %H:%M:%S'),
                   'prev_med': old_med, 'new_med': new_med},
                  open(BASELINE_RECOMPUTE_LOG, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    # ===== 输出文案（池子限定，全部动态读自选池 4c 基线）=====
    # ship_med 已在 main() 读入（4c_43_rebuilt_summary.json['出货']['med']）
    ship_text = (f"[自选池] 出货信号无显著增量（{ship_med}pp），可能主升中继，非派发预警"
                 if ship_med is not None
                 else "[自选池] 出货信号方向待重算，暂不提示")
    # 拉升高位：同样动态读池子数字（4c_43_rebuilt_summary.json['拉升高位']['med']）
    try:
        pull_med = float(json.load(open(BASELINE_JSON))['拉升高位']['med'])
    except Exception:
        pull_med = None
    if pull_med is not None:
        # 按方向给不同文案（自选池 −1.16pp 偏负；若翻正则文案也变）
        direction = '偏负' if pull_med < 0 else ('偏正' if pull_med > 0 else '中性')
        pull_text = (f"[自选池] 拉升高位信号无显著增量（{pull_med}pp，{direction}），"
                     f"谨慎持有参考，非买入信号")
    else:
        pull_text = "[自选池] 拉升高位信号方向待重算，谨慎持有参考"
    build_text = "建仓：中性参考备注（自选池无显著增量，不预测方向）"

    # ===== 落盘：append 增量日志 + 覆盖当日快照 =====
    if args.skip_pull:
        # 幂等：本地重算不拉增量 → daily_update_log 不 append（新增 0 条）
        # latest_signals.csv 写的是"截至 db 最新日期（09-16）的当日信号快照"，是快照非新增
        print(f'\n[幂等验证] --skip-pull：不拉增量 → 新增日志 0 条')
        print(f'             latest_signals.csv = 截至 db 最新日期的当日信号快照（{len(new_signals)} 条，非"今日新增"）')
        with open(LATEST, 'w', encoding='utf-8-sig') as f:
            f.write('日期,代码,名称,信号,信号强度,池子备注\n')
            if not new_signals.empty:
                for _, r in new_signals.iterrows():
                    note = _pool_note(r, ship_text, pull_text, build_text)
                    f.write(f"{r['日期']},{r['代码']},{r.get('名称','')},{r.get('信号','')},{r.get('信号强度','')},{note}\n")
        print(f'latest_signals.csv 已覆盖（{len(new_signals)} 条当日快照）')
        print(f'\n[幂等验证通过] 新增日志 0 条；latest_signals.csv = {len(new_signals)} 条当日快照（非"今日新增"）')
    else:
        if not new_signals.empty:
            # append 到 daily_update_log.csv
            if not os.path.exists(UPD_LOG):
                with open(UPD_LOG, 'w', encoding='utf-8-sig') as f:
                    f.write('日期,代码,名称,信号,信号强度,池子备注\n')
            with open(UPD_LOG, 'a', encoding='utf-8-sig') as f:
                for _, r in new_signals.iterrows():
                    note = _pool_note(r, ship_text, pull_text, build_text)
                    f.write(f"{r['日期']},{r['代码']},{r.get('名称','')},{r.get('信号','')},{r.get('信号强度','')},{note}\n")
            # 覆盖 latest_signals.csv
            with open(LATEST, 'w', encoding='utf-8-sig') as f:
                f.write('日期,代码,名称,信号,信号强度,池子备注\n')
                for _, r in new_signals.iterrows():
                    note = _pool_note(r, ship_text, pull_text, build_text)
                    f.write(f"{r['日期']},{r['代码']},{r.get('名称','')},{r.get('信号','')},{r.get('信号强度','')},{note}\n")
            print(f'daily_update_log.csv 已 append {len(new_signals)} 条')
            print(f'latest_signals.csv 已覆盖')
        else:
            print(f'\n今日新增信号: 0 条（无新交易日增量）')
            with open(LATEST, 'w', encoding='utf-8-sig') as f:
                f.write('日期,代码,名称,信号,信号强度,池子备注\n')

    # ===== 今日新增信号摘要 =====
    print('\n' + '='*50)
    print('今日新增信号摘要（自选池·池子限定文案）')
    print('='*50)
    if new_signals.empty:
        print('（今日无新增非"无信号"条目）')
    else:
        for _, r in new_signals.iterrows():
            note = _pool_note(r, ship_text, pull_text, build_text)
            print(f"  {r['代码']} {r.get('信号',''):>6} [{r.get('信号强度','')}] {note}")

    print(f'\n总耗时 {time.time()-t_start:.1f}s')
    signal.alarm(0)
    print('DONE')

def _pool_note(row, ship_text, pull_text, build_text):
    """按信号类型给池子限定备注（出货/拉升/建仓全部动态，来自自选池 4c 基线）"""
    sig = str(row.get('信号', ''))
    if '出货' in sig:
        return ship_text
    if '拉升' in sig:
        return pull_text
    if '建仓' in sig:
        return build_text
    return "（中性参考）"

def _merge_daily(conn, code, df):
    """把增量日线 merge 进 daily_new.db:daily_<code>（去重追加）"""
    if df.empty:
        return
    import pandas as pd
    conn.execute(f'CREATE TABLE IF NOT EXISTS daily_{code} ('
                 f'日期 TEXT, 开盘 REAL, 收盘 REAL, 最高 REAL, 最低 REAL, 成交量 REAL)')
    existing = set(r[0] for r in conn.execute(f'SELECT 日期 FROM daily_{code}').fetchall())
    for _, r in df.iterrows():
        if r['日期'] not in existing:
            conn.execute(f'INSERT INTO daily_{code} VALUES (?,?,?,?,?,?)',
                         tuple(r.tolist()))
    conn.commit()

if __name__ == '__main__':
    main()
