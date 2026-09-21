#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
八步客观描述报告 - HTML版
=================================================
设计思路（为什么这样写）：
  客观描述，不做主观判断！
  对着我们推导的八步，每一步都客观描述！

硬约束：
  - 绝对不用未来函数
  - 客观描述，不做主观判断
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path

# ============================================================
# 配置
# ============================================================
DATA_DIR = Path(__file__).parent.parent / "data" / "kline"
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "analysis"

# 你的持仓股（8只）
HOLDINGS = [
    ("sh", "600584"),  # 长电科技
    ("sz", "002156"),  # 通富微电
    ("sh", "603283"),  # 赛腾股份
    ("sz", "300394"),  # 天孚通信
    ("sh", "601138"),  # 工业富联
    ("sh", "601231"),  # 环旭电子
    ("sz", "300476"),  # 胜宏科技
    ("sh", "603516"),  # 淳中科技
]


# ============================================================
# 数据读取
# ============================================================
def load_klines(market, code):
    possible_paths = [
        DATA_DIR / market / f"{code}.json",
        DATA_DIR / market / f"{market}{code}.json",
        DATA_DIR / f"{market}{code}.json",
    ]
    
    for filepath in possible_paths:
        if filepath.exists():
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            klines = data.get('klines', [])
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
            
            return df, data.get('name', code)
    
    return None, None


# ============================================================
# 生成单只股票的报告数据
# ============================================================
def get_stock_data(market, code):
    df, name = load_klines(market, code)
    
    if df is None:
        return None
    
    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    
    today_price = today['close']
    today_volume = today['volume']
    
    # 计算指标
    pct_chg = (today['close'] - yesterday['close']) / yesterday['close'] * 100
    amplitude = (today['high'] - today['low']) / yesterday['close'] * 100
    body_size = abs(today['close'] - today['open'])
    body_ratio = body_size / (today['high'] - today['low']) * 100
    vol_ratio_yesterday = today_volume / yesterday['volume']
    
    # 连续趋势
    pct_3d = (today['close'] - df.iloc[-4]['close']) / df.iloc[-4]['close'] * 100 if len(df) > 4 else 0
    pct_5d = (today['close'] - df.iloc[-6]['close']) / df.iloc[-6]['close'] * 100 if len(df) > 6 else 0
    pct_10d = (today['close'] - df.iloc[-11]['close']) / df.iloc[-11]['close'] * 100 if len(df) > 11 else 0
    
    # 连续放量/缩量
    v1 = df.iloc[-1]['volume']
    v2 = df.iloc[-2]['volume']
    v3 = df.iloc[-3]['volume']
    if v1 > v2 > v3:
        vol_trend = "连续放量"
    elif v1 < v2 < v3:
        vol_trend = "连续缩量"
    else:
        vol_trend = "无连续趋势"
    
    # 历史重要位置
    recent_20 = df.iloc[-20:]
    recent_high = recent_20['high'].max()
    recent_low = recent_20['low'].min()
    
    mid_high = mid_low = long_high = long_low = None
    mid_vol_high = mid_vol_low = long_vol_high = long_vol_low = None
    
    if len(df) > 60:
        recent_60 = df.iloc[-60:]
        mid_high = recent_60['high'].max()
        mid_low = recent_60['low'].min()
        mid_vol_high = recent_60['volume'].max()
        mid_vol_low = recent_60['volume'].min()
    
    if len(df) > 120:
        recent_120 = df.iloc[-120:]
        long_high = recent_120['high'].max()
        long_low = recent_120['low'].min()
        long_vol_high = recent_120['volume'].max()
        long_vol_low = recent_120['volume'].min()
    
    # 位置计算
    pos_20 = (today_price - recent_low) / (recent_high - recent_low) * 100
    pos_60 = (today_price - mid_low) / (mid_high - mid_low) * 100 if mid_high else 0
    pos_120 = (today_price - long_low) / (long_high - long_low) * 100 if long_high else 0
    
    # 量能位置
    vol_pos_20 = (today_volume - recent_20['volume'].min()) / (recent_20['volume'].max() - recent_20['volume'].min()) * 100
    vol_pos_60 = (today_volume - mid_vol_low) / (mid_vol_high - mid_vol_low) * 100 if mid_vol_high else 0
    vol_pos_120 = (today_volume - long_vol_low) / (long_vol_high - long_vol_low) * 100 if long_vol_high else 0
    
    # 支撑位/压力位
    supports = [(recent_low, "20日低点")]
    if mid_low:
        supports.append((mid_low, "60日低点"))
    if long_low:
        supports.append((long_low, "120日低点"))
    supports = [(p, l) for p, l in supports if p < today_price]
    supports.sort(key=lambda x: x[0], reverse=True)
    
    resistances = [(recent_high, "20日高点")]
    if mid_high:
        resistances.append((mid_high, "60日高点"))
    if long_high:
        resistances.append((long_high, "120日高点"))
    resistances = [(p, l) for p, l in resistances if p > today_price]
    resistances.sort(key=lambda x: x[0])
    
    return {
        'name': name,
        'code': f"{market}{code}",
        'date': today['date'],
        'open': today['open'],
        'close': today_price,
        'high': today['high'],
        'low': today['low'],
        'volume': today_volume,
        'pct_chg': pct_chg,
        'amplitude': amplitude,
        'body_ratio': body_ratio,
        'vol_ratio_yesterday': vol_ratio_yesterday,
        'is_yang': today['close'] > today['open'],
        'pct_3d': pct_3d,
        'pct_5d': pct_5d,
        'pct_10d': pct_10d,
        'vol_trend': vol_trend,
        'pos_20': pos_20,
        'pos_60': pos_60,
        'pos_120': pos_120,
        'vol_pos_20': vol_pos_20,
        'vol_pos_60': vol_pos_60,
        'vol_pos_120': vol_pos_120,
        'supports': supports[:3],
        'resistances': resistances[:3],
    }


# ============================================================
# 生成HTML
# ============================================================
def generate_html(stocks_data, today_str):
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>八步客观描述报告 - {today_str}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; padding: 20px; line-height: 1.6; }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{ background: linear-gradient(135deg, #1a237e 0%, #283593 100%); color: white; padding: 30px; border-radius: 12px; margin-bottom: 20px; }}
        .header h1 {{ font-size: 24px; margin-bottom: 8px; }}
        .header .date {{ opacity: 0.8; font-size: 14px; }}
        .header .note {{ margin-top: 10px; font-size: 13px; opacity: 0.7; }}
        
        .stock-card {{ background: white; border-radius: 12px; padding: 20px; margin-bottom: 15px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .stock-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; padding-bottom: 15px; border-bottom: 1px solid #eee; }}
        .stock-name {{ font-size: 18px; font-weight: bold; color: #333; }}
        .stock-code {{ font-size: 12px; color: #999; }}
        .stock-price {{ font-size: 22px; font-weight: bold; }}
        .price-up {{ color: #d32f2f; }}
        .price-down {{ color: #388e3c; }}
        
        .step-section {{ margin-bottom: 15px; }}
        .step-title {{ font-size: 14px; font-weight: bold; color: #1a237e; margin-bottom: 8px; padding-left: 8px; border-left: 3px solid #1a237e; }}
        .step-content {{ background: #f8f9fa; padding: 12px; border-radius: 8px; font-size: 13px; color: #555; }}
        .step-content p {{ margin-bottom: 4px; }}
        
        .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
        .grid-item {{ background: #f8f9fa; padding: 8px; border-radius: 6px; font-size: 13px; }}
        .grid-item .label {{ color: #999; font-size: 11px; }}
        .grid-item .value {{ font-weight: bold; color: #333; }}
        
        .support-resistance {{ display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }}
        .sr-box {{ background: #f8f9fa; padding: 10px; border-radius: 8px; }}
        .sr-title {{ font-size: 12px; color: #999; margin-bottom: 5px; }}
        .sr-item {{ font-size: 13px; color: #333; margin-bottom: 3px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>八步客观描述报告</h1>
            <div class="date">{today_str}</div>
            <div class="note">客观描述，不做主观判断 | 数据截止到收盘</div>
        </div>
"""
    
    for stock in stocks_data:
        if stock is None:
            continue
        
        price_class = "price-up" if stock['pct_chg'] > 0 else "price-down"
        vol_type = "放量" if stock['vol_ratio_yesterday'] > 1.5 else "缩量" if stock['vol_ratio_yesterday'] < 0.7 else "平量"
        position_type = "高位" if stock['pos_120'] > 70 else "低位" if stock['pos_120'] < 30 else "中位"
        vol_pos_type = "天量" if stock['vol_pos_120'] > 80 else "地量" if stock['vol_pos_120'] < 20 else "正常"
        
        supports_html = ""
        for price, label in stock['supports']:
            dist = (stock['close'] - price) / stock['close'] * 100
            supports_html += f'<div class="sr-item">{price:.2f}（{label}）-{dist:.1f}%</div>'
        
        resistances_html = ""
        for price, label in stock['resistances']:
            dist = (price - stock['close']) / stock['close'] * 100
            resistances_html += f'<div class="sr-item">{price:.2f}（{label}）+{dist:.1f}%</div>'
        
        html += f"""
        <div class="stock-card">
            <div class="stock-header">
                <div>
                    <div class="stock-name">{stock['name']}</div>
                    <div class="stock-code">{stock['code']}</div>
                </div>
                <div class="stock-price {price_class}">{stock['close']:.2f}元 ({stock['pct_chg']:+.2f}%)</div>
            </div>
            
            <div class="step-section">
                <div class="step-title">第一步：今日数据</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">开盘价</div>
                            <div class="value">{stock['open']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">收盘价</div>
                            <div class="value">{stock['close']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">最高价</div>
                            <div class="value">{stock['high']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">最低价</div>
                            <div class="value">{stock['low']:.2f}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">第二步：今日情况</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">涨跌幅</div>
                            <div class="value">{stock['pct_chg']:+.2f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">振幅</div>
                            <div class="value">{stock['amplitude']:.2f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">实体占比</div>
                            <div class="value">{stock['body_ratio']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量比(vs昨日)</div>
                            <div class="value">{stock['vol_ratio_yesterday']:.2f}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">第三步：今日多空力量</div>
                <div class="step-content">
                    <p>{"阳线：买方占优" if stock['is_yang'] else "阴线：卖方占优"}</p>
                    <p>{vol_type}：成交{"活跃" if vol_type == "放量" else "冷清" if vol_type == "缩量" else "正常"}</p>
                    <p>实体占比{stock['body_ratio']:.1f}%：{"实体明确" if stock['body_ratio'] > 50 else "影线较多"}</p>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">第四步：连续趋势</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">近3日涨跌</div>
                            <div class="value">{stock['pct_3d']:+.2f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">近5日涨跌</div>
                            <div class="value">{stock['pct_5d']:+.2f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">近10日涨跌</div>
                            <div class="value">{stock['pct_10d']:+.2f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量能趋势</div>
                            <div class="value">{stock['vol_trend']}</div>
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">第五步：和历史对比</div>
                <div class="step-content">
                    <p>价格位置：近20日{stock['pos_20']:.1f}% | 近60日{stock['pos_60']:.1f}% | 近120日{stock['pos_120']:.1f}%</p>
                    <p>量能位置：近20日{stock['vol_pos_20']:.1f}% | 近60日{stock['vol_pos_60']:.1f}% | 近120日{stock['vol_pos_120']:.1f}%</p>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">第六步：历史重要位置</div>
                <div class="step-content">
                    <p>短期(20日)：最高{stock['resistances'][0][0] if stock['resistances'] else '-'} | 最低{stock['supports'][0][0] if stock['supports'] else '-'}</p>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">第七步：支撑位/压力位</div>
                <div class="step-content">
                    <div class="support-resistance">
                        <div class="sr-box">
                            <div class="sr-title">下方支撑位</div>
                            {supports_html}
                        </div>
                        <div class="sr-box">
                            <div class="sr-title">上方压力位</div>
                            {resistances_html}
                        </div>
                    </div>
                </div>
            </div>
            
            <div class="step-section">
                <div class="step-title">第八步：客观总结</div>
                <div class="step-content">
                    <p>今日{stock['name']}{'上涨' if stock['pct_chg'] > 0 else '下跌'}{abs(stock['pct_chg']):.2f}%，{vol_type}。</p>
                    <p>价格位置：近120日{stock['pos_120']:.1f}%（{position_type}）。</p>
                    <p>量能位置：近120日{stock['vol_pos_120']:.1f}%（{vol_pos_type}）。</p>
                    <p>下方最近支撑：{stock['supports'][0][0]:.2f}（{stock['supports'][0][1]}）。</p>
                    <p>上方最近压力：{stock['resistances'][0][0]:.2f}（{stock['resistances'][0][1]}）。</p>
                </div>
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
    print("=" * 60)
    print("八步客观描述报告 - HTML版")
    print("=" * 60)
    
    stocks_data = []
    today_str = ""
    
    for market, code in HOLDINGS:
        try:
            data = get_stock_data(market, code)
            if data:
                stocks_data.append(data)
                today_str = data['date']
                print(f"  已生成：{data['name']}")
        except Exception as e:
            print(f"  Error: {market}{code} {e}")
    
    # 生成HTML
    html_content = generate_html(stocks_data, today_str)
    
    # 保存
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    html_file = OUTPUT_DIR / f"my_holdings_report_{today_str}.html"
    
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n已生成HTML报告: {html_file}")


if __name__ == "__main__":
    main()
