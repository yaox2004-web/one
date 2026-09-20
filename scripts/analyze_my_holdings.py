#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
我的持仓股分析
=================================================
设计思路（为什么这样写）：
  专门分析用户的持仓股！
  用我们的判断逻辑，看看每只股票现在处于什么阶段。

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
    # 找文件
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
    
    # 关键位
    df['support_60'] = df['low'].rolling(60).min()
    df['resistance_60'] = df['high'].rolling(60).max()
    df['dist_to_support'] = (df['close'] - df['support_60']) / df['support_60'] * 100
    df['dist_to_resistance'] = (df['resistance_60'] - df['close']) / df['close'] * 100
    
    # 量价形态
    df['is_volume_up'] = df['vol_ratio_ma5'] > 1.5
    df['is_volume_down'] = df['vol_ratio_ma5'] < 0.7
    df['is_big_yang'] = df['pct_chg'] > 3
    df['is_big_yin'] = df['pct_chg'] < -3
    df['price_up_vol_up'] = (df['pct_chg'] > 0) & (df['vol_ratio_ma5'] > 1.2)
    df['price_down_vol_down'] = (df['pct_chg'] < 0) & (df['vol_ratio_ma5'] < 0.8)
    
    return df


# ============================================================
# 主力行为判断
# ============================================================
def judge_main_behavior(df):
    latest = df.iloc[-1]
    
    position = latest['position_pct']
    dist_to_support = latest['dist_to_support']
    dist_to_resistance = latest['dist_to_resistance']
    
    if pd.isna(position):
        return None
    
    scores = {
        '建仓初期': 0,
        '建仓后期': 0,
        '洗盘': 0,
        '拉升': 0,
        '出货': 0,
    }
    
    reasons = []
    
    # 1. 在关键支撑位附近
    if not pd.isna(dist_to_support) and dist_to_support < 5:
        if latest['is_volume_down'] and latest['pct_chg'] > -1:
            scores['建仓初期'] += 40
            reasons.append(f'在支撑位{latest["support_60"]:.2f}附近缩量止跌')
        elif latest['is_volume_up'] and latest['is_big_yang']:
            scores['建仓后期'] += 40
            reasons.append(f'在支撑位{latest["support_60"]:.2f}附近放量大涨')
    
    # 2. 在关键压力位下方
    if not pd.isna(dist_to_resistance) and dist_to_resistance < 5:
        if latest['is_volume_down'] and abs(latest['pct_chg']) < 1:
            scores['洗盘'] += 40
            reasons.append(f'在压力位{latest["resistance_60"]:.2f}下方缩量横盘')
        elif latest['is_volume_up'] and latest['is_big_yang']:
            scores['拉升'] += 40
            reasons.append(f'放量突破压力位{latest["resistance_60"]:.2f}')
    
    # 3. 高位
    if position > 70:
        if latest['is_volume_up'] and abs(latest['pct_chg']) < 1:
            scores['出货'] += 40
            reasons.append(f'高位{position:.1f}%放量滞涨')
        elif latest['is_volume_up'] and latest['is_big_yin']:
            scores['出货'] += 40
            reasons.append(f'高位{position:.1f}%放量大跌')
    
    # 4. 低位
    if position < 30:
        if latest['price_down_vol_down']:
            scores['建仓初期'] += 30
            reasons.append(f'低位{position:.1f}%价跌量缩')
        elif latest['price_up_vol_up']:
            scores['建仓后期'] += 30
            reasons.append(f'低位{position:.1f}%价升量增')
    
    # 5. 中位
    if 50 < position < 70:
        if latest['is_volume_down'] and latest['pct_chg'] < 0:
            scores['洗盘'] += 30
            reasons.append(f'中位{position:.1f}%缩量回调')
    
    best_stage = max(scores, key=scores.get)
    best_score = scores[best_stage]
    total_score = sum(scores.values())
    confidence = best_score / total_score * 100 if total_score > 0 else 0
    
    return {
        'stage': best_stage,
        'confidence': confidence,
        'position': position,
        'vol_ratio': latest['vol_ratio_ma5'],
        'pct_20d': latest['pct_20d'],
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
    print("我的持仓股分析")
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
    
    # 生成HTML
    today = datetime.now().strftime('%Y-%m-%d')
    html_content = generate_html(results, today)
    
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / f"my_holdings_{today}.html"
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n已生成HTML分析报告: {output_file}")


if __name__ == "__main__":
    main()

