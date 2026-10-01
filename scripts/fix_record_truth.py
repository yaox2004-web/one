#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键修补 record_truth.py v2.1 -> v2.2（小白版，幂等可重复运行）
A: 残缺日诊断日志（解304之谜）
B: 残缺的历史日期 → 保留文件次日重试，不再丢真相
C: 账本新增 market_vol_ratio（上证量比，回测可剔大盘因素）
D: 指数1分钟文件也清理，防磁盘无限堆积
用法：python3 fix_record_truth.py  （自动备份，语法失败自动还原）"""
from pathlib import Path

SCRIPT = Path(__file__).parent / "record_truth.py"

MKT_FUNC = '''
# ============================================================
# 【v2.2 补丁C】大盘背景量：上证当日量能 / 自身5日均量
# 供账本记录 market_vol_ratio，回测时可剔除大盘放量的干扰
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

'''

def main():
    if not SCRIPT.exists():
        print(f"❌ 找不到 {SCRIPT}，请把本文件放在 scripts 目录")
        return

    text = SCRIPT.read_text(encoding="utf-8")

    if "market_vol_ratio" in text:
        print("✅ record_truth.py 已修补过（v2.2），无需重复修补")
        return

    backup = SCRIPT.with_suffix(".py.bak")
    backup.write_text(text, encoding="utf-8")
    print(f"💾 已备份原文件 -> {backup.name}")

    ok = True

    # ---- 1/5 插入大盘量比函数 ----
    if "\ndef main():" in text:
        text = text.replace("\ndef main():", MKT_FUNC + "\ndef main():", 1)
        print("  ✔ 1/5 插入 load_market_volume 函数")
    else:
        print("  ✘ 1/5 未找到 main 函数锚点")
        ok = False

    # ---- 2/5 定义 today_str（补丁B需要）----
    anchor2 = '''print(f"[账本] 北京时间: {bj_now.strftime('%Y-%m-%d %H:%M:%S')}")'''
    if anchor2 in text:
        text = text.replace(anchor2,
                            anchor2 + '\n    today_str = bj_now.strftime(\'%Y-%m-%d\')', 1)
        print("  ✔ 2/5 定义 today_str")
    else:
        print("  ✘ 2/5 未找到北京时间打印锚点")
        ok = False

    # ---- 3/5 主循环里加载大盘量比 ----
    anchor3 = "    hist_index = HistoryIndex()"
    if anchor3 in text:
        text = text.replace(anchor3,
                            anchor3 + "\n    mkt_vol = load_market_volume()", 1)
        print("  ✔ 3/5 主循环加载大盘量比")
    else:
        print("  ✘ 3/5 未找到历史索引锚点")
        ok = False

    # ---- 4/5 补丁A+B：残缺日诊断日志 + 历史残缺保留文件 ----
    old4 = ("            if len(day_klines) < MIN_FULL_DAY_BARS:\n"
            "                skipped_incomplete += 1\n"
            "                continue")
    new4 = ("            if len(day_klines) < MIN_FULL_DAY_BARS:\n"
            "                skipped_incomplete += 1\n"
            "                print(f\"  [残缺] {code} {d} 仅{len(day_klines)}根(<{MIN_FULL_DAY_BARS})\")\n"
            "                # 补丁B：残缺的\"历史\"日期不是今天 → 保留文件次日重试\n"
            "                if d != today_str:\n"
            "                    failed_files.setdefault(f, []).append(f\"残缺:{d}:{len(day_klines)}根\")\n"
            "                continue")
    if old4 in text:
        text = text.replace(old4, new4, 1)
        print("  ✔ 4/5 补丁A+B（诊断日志+残缺保留）")
    else:
        print("  ✘ 4/5 未找到残缺跳过锚点")
        ok = False

    # ---- 5/5 补丁C+D：账本加大盘量比字段 + 指数文件也清理 ----
    anchor5 = '                "ver": LEDGER_VERSION,'
    if anchor5 in text:
        text = text.replace(anchor5,
                            '                "market_vol_ratio": mkt_vol.get(d),\n' + anchor5, 1)
        print("  ✔ 5a/5 账本新增 market_vol_ratio 字段")
    else:
        print("  ✘ 5a/5 未找到账本写入锚点")
        ok = False

    old5b = ("        if f.stem in INDEX_CODES:\n"
             "            continue")
    new5b = ("        if f.stem in INDEX_CODES:\n"
             "            # 补丁D：指数原始数据不入账本，也同样删除，防磁盘无限堆积\n"
             "            try:\n"
             "                f.unlink()\n"
             "                deleted += 1\n"
             "            except Exception:\n"
             "                pass\n"
             "            continue")
    if old5b in text:
        text = text.replace(old5b, new5b, 1)
        print("  ✔ 5b/5 补丁D（指数文件也清理）")
    else:
        print("  ⚠ 5b/5 未找到指数清理锚点（不影响其他补丁），跳过")

    # ---- 语法检查，失败自动还原 ----
    try:
        compile(text, str(SCRIPT), "exec")
        print("🔍 语法检查通过")
    except SyntaxError as e:
        print(f"❌ 语法检查失败: {e}，已还原备份，原文件未受影响")
        SCRIPT.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
        return

    if ok:
        SCRIPT.write_text(text, encoding="utf-8")
        print("\n🎉 record_truth.py 修补完成（v2.2）！")
        print("   下次记账时验证：出现 [残缺] 诊断行、账本记录含 market_vol_ratio")
    else:
        print("\n❌ 修补未完成，已还原备份，请把本输出发给助手")

if __name__ == "__main__":
    main()
