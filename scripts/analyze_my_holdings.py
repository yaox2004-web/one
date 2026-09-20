#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
我的持仓股分析
=================================================
设计思路（为什么这样写）：
  专门分析用户的持仓股！
  修正版：判断逻辑更合理，覆盖更多情况！

硬约束：
  - 绝对不用未来函数
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# ============================================================
# 配置 - 你的持仓股
# ============================================================
MY_HOLDINGS = [
    {'code': 'sh600584', 'name': '长电科技'},
    {'code': 'sz002156', 'name': '通富微电'},
    {'code': 'sh603283', 'name': '赛腾股份'},
    {'code': 'sz300394', 'name': '天孚通信'},
    {'code': 'sh601138', 'name': '工业富联'},
    {'code': 'sh601231', 'name': '环旭电子'},
    {'code': 'sz300476', 'name': '胜宏科技'},
    {'code': 'sh603516', 'name': '淳中科技'},
]

DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

MIN_DATA_DAYS = 60


# ============================================================
# 数据读取
# ============================================================
def load_klines(stock_code):
    for market_dir in DATA_DIR.iterdir():
        if market_dir.is_dir():
            filepath = market_dir / f"{stock_code}.json"
            if filepath.exists():
                with open(filepath, 'r') as f:
                    data = json.load(f)
                klines = data.get('klines', [])
                if klines:
                    ncols = len(klines[0])
                    if ncols == 6:
                        cols = ['date', 'open', 'close', 'high', 'low', 'volume']
                    else:
                        cols = ['date', 'open', 'close', 'high', 'low', 'volume', 'amount']
                    df = pd.DataFrame(klines)
                    df = df.iloc[:, :ncols]
                    df.columns = cols[:ncols]
                    for col in ['open', 'close', 'high', 'low', 'volume']:
                        df[col] = pd.to_numeric(df[col], errors='coerce')
                    df = df.dropna(subset=['open', 'close', 'high', 'low', 'volume'])
                    return df, data.get('name', stock_code)
    return None, None


# ============================================================
# 计算当日指标
# ============================================================
def calc_daily_indicators(df):
    df['pct_chg'] = (df['close'] - df['close'].shift(1)) / df['close'].shift(1) * 100
    
    df['vol_ma5'] = df['volume'].rolling(5).mean()
    df['vol_ratio_ma5'] = df['volume'] / df['vol_ma5']
    
    df['high_120'] = df['high'].rolling(120).max()
    df['low_120'] = df['low'].rolling(120).min()
    df['position_pct'] = (df['close'] - df['low_120']) / (df['high_120'] - df['low_120']) * 100
    
    df['ma20'] = df['close'].rolling(20).mean()
    df['ma60'] = df['close'].rolling(60).mean()
    
    df['pct_20d'] = (df['close'] - df['close'].shift(20)) / df['close'].shift(20) * 100
    
    return df


# ============================================================
# 主力行为判断（修正版 - 更合理）
# ============================================================
def judge_main_behavior(df):
    latest = df.iloc[-1]
    
    position = latest['position_pct']
    vol_ratio = latest['vol_ratio_ma5']
    pct_chg = latest['pct_chg']
    pct_20d = latest['pct_20d']
    
    if pd.isna(position) or pd.isna(vol_ratio):
        return None
    
    scores = {
        '建仓初期': 0,
        '建仓后期': 0,
        '洗盘': 0,
        '拉升': 0,
        '出货': 0,
    }
    
    reasons = []
    
    # ============================================================
    # 核心逻辑：量价关系 + 位置
    # ============================================================
    
    # 1. 当日大涨+放量 → 拉升（不管位置在哪，大涨放量就是拉升）
    if pct_chg > 3 and vol_ratio > 1.5:
        scores['拉升'] += 50
        reasons.append(f'当日大涨{pct_chg:.2f}%+放量（量比{vol_ratio:.2f}）→ 拉升')
    
    # 2. 当日大跌+放量 → 出货
    elif pct_chg < -3 and vol_ratio > 1.5:
        scores['出货'] += 50
        reasons.append(f'当日大跌{pct_chg:.2f}%+放量（量比{vol_ratio:.2f}）→ 出货')
    
    # 3. 当日上涨+放量 → 建仓后期或拉升
    elif pct_chg > 1 and vol_ratio > 1.3:
        if position < 30:
            scores['建仓后期'] += 30
            reasons.append(f'低位{position:.1f}%涨{pct_chg:.2f}%+放量 → 建仓后期')
        else:
            scores['拉升'] += 30
            reasons.append(f'位置{position:.1f}%涨{pct_chg:.2f}%+放量 → 拉升')
    
    # 4. 当日下跌+缩量 → 洗盘或建仓
    elif pct_chg < -1 and vol_ratio < 0.8:
        if position < 30:
            scores['建仓初期'] += 30
            reasons.append(f'低位{position:.1f}%跌{pct_chg:.2f}%+缩量 → 建仓初期')
        else:
            scores['洗盘'] += 30
            reasons.append(f'位置{position:.1f}%跌{pct_chg:.2f}%+缩量 → 洗盘')
    
    # 5. 20日大涨+放量 → 拉升
    if not pd.isna(pct_20d):
        if pct_20d > 15 and vol_ratio > 1.2:
            scores['拉升'] += 30
            reasons.append(f'20日大涨{pct_20d:.1f}% → 拉升')
        
        # 6. 20日大跌 → 建仓初期或出货
        elif pct_20d < -15:
            if position < 30:
                scores['建仓初期'] += 30
                reasons.append(f'低位{position:.1f}%跌{pct_20d:.1f}% → 建仓初期')
            else:
                scores['出货'] += 20
                reasons.append(f'高位跌{pct_20d:.1f}% → 出货')
    
    # 7. 位置高的 → 出货
    if position > 80:
        scores['出货'] += 30
        reasons.append(f'位置极高{position:.1f}% → 出货')
    elif position > 70:
        scores['出货'] += 20
        reasons.append(f'位置高{position:.1f}% → 出货')
    
    # 8. 位置低的 → 建仓
    if position < 10:
        scores['建仓初期'] += 30
        reasons.append(f'位置极低{position:.1f}% → 建仓初期')
    elif position < 30:
        scores['建仓后期'] += 20
        reasons.append(f'位置低{position:.1f}% → 建仓后期')
    
    # 找最高分
    best_stage = max(scores, key=scores.get)
    best_score = scores[best_stage]
    
    total_score = sum(scores.values())
    confidence = best_score / total_score * 100 if total_score > 0 else 0
    
    # 如果所有scores都是0，给个默认判断
    if total_score == 0:
        if position < 30:
            best_stage = '建仓后期'
            reasons.append(f'位置{position:.1f}%（默认判断）')
        elif position < 70:
            best_stage = '洗盘'
            reasons.append(f'位置{position:.1f}%（默认判断）')
        else:
            best_stage = '出货'
            reasons.append(f'位置{position:.1f}%（默认判断）')
        confidence = 50.0
    
    return {
        'stage': best_stage,
        'confidence': confidence,
        'position': position,
        'vol_ratio': vol_ratio,
        'pct_20d': pct_20d,
        'reasons': reasons,
    }


# ============================================================
# 生成HTML
# ============================================================
def generate_html(results, date_str):
    html = f"""
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>我的持仓股分析 - {date_str}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; line-height: 1.6; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #1e3c72 0%, #2a5298 100%); color: white; padding: 30px; border-radius: 12px; margin-bottom: 20px; }}
        .header h1 {{ font-size: 28px; margin-bottom: 10px; }}
        .header .date {{ opacity: 0.8; font-size: 16px; }}
        .stock-card {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .stock-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }}
        .stock-name {{ font-size: 20px; font-weight: bold; color: #333; }}
        .stock-price {{ font-size: 24px; font-weight: bold; color: #d32f2f; }}
        .stage-badge {{ padding: 5px 15px; border-radius: 20px; font-size: 14px; font-weight: bold; color: white; }}
        .stage-建仓初期 {{ background: #1976d2; }}
        .stage-建仓后期 {{ background: #388e3c; }}
        .stage-洗盘 {{ background: #f57c00; }}
        .stage-拉升 {{ background: #c2185b; }}
        .stage-出货 {{ background: #d32f2f; }}
        .info-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-bottom: 15px; }}
        .info-item {{ background: #f8f9fa; padding: 10px; border-radius: 8px; }}
        .info-label {{ font-size: 12px; color: #666; }}
        .info-value {{ font-size: 16px; font-weight: bold; color: #333; }}
        .reasons {{ background: #fff3e0; padding: 15px; border-radius: 8px; }}
        .reasons-title {{ font-weight: bold; color: #f57c00; margin-bottom: 10px; }}
        .reasons ul {{ margin-left: 20px; color: #555; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>我的持仓股分析</h1>
            <div class="date">{date_str}</div>
        </div>
    """
    
    for r in results:
        stage_class = f"stage-{r['stage']}"
        html += f"""
        <div class="stock-card">
            <div class="stock-header">
                <div>
                    <div class="stock-name">{r['name']} ({r['code']})</div>
                    <div class="stock-price">{r['price']:.2f}元</div>
                </div>
                <div class="stage-badge {stage_class}">{r['stage']} ({r['confidence']:.1f}%)</div>
            </div>
            <div class="info-grid">
                <div class="info-item">
                    <div class="info-label">位置分位</div>
                    <div class="info-value">{r['position']:.1f}%</div>
                </div>
                <div class="info-item">
                    <div class="info-label">量比(vs5日)</div>
                    <div class="info-value">{r['vol_ratio']:.2f}</div>
                </div>
                <div class="info-item">
                    <div class="info-label">20日涨跌幅</div>
                    <div class="info-value">{r['pct_20d']:.2f}%</div>
                </div>
            </div>
            <div class="reasons">
                <div class="reasons-title">判断依据：</div>
                <ul>
        """
        for reason in r['reasons']:
            html += f"<li>{reason}</li>\n"
        html += """
                </ul>
            </div>
        </div>
        """
    
    html += """
    </div>
</body>
</html>
    """
    
    return html


# ============================================================
# 主函数
# ============================================================
def main():
    print("="*70)
    print("我的持仓股分析（修正版）")
    print("="*70)
    
    results = []
    
    for stock in MY_HOLDINGS:
        code = stock['code']
        name = stock['name']
        
        print(f"\n分析 {name} ({code})...")
        
        df, actual_name = load_klines(code)
        if df is None:
            print(f"  数据不存在！")
            continue
        
        if len(df) < MIN_DATA_DAYS:
            print(f"  数据不够！")
            continue
        
        df = calc_daily_indicators(df)
        result = judge_main_behavior(df)
        
        if result is None:
            print(f"  判断失败！")
            continue
        
        results.append({
            'code': code,
            'name': actual_name,
            'price': df['close'].iloc[-1],
            'position': result['position'],
            'vol_ratio': result['vol_ratio'],
            'pct_20d': result['pct_20d'],
            'stage': result['stage'],
            'confidence': result['confidence'],
            'reasons': result['reasons'],
        })
        
        print(f"  当前价格：{df['close'].iloc[-1]:.2f}")
        print(f"  位置分位：{result['position']:.1f}%")
        print(f"  判断：{result['stage']}（置信度{result['confidence']:.1f}%）")
        print(f"  依据：{', '.join(result['reasons'])}")
    
    today = datetime.now().strftime('%Y-%m-%d')
    html_content = generate_html(results, today)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"my_holdings_{today}.html"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n已生成HTML分析报告: {output_file}")


if __name__ == "__main__":
    main()
