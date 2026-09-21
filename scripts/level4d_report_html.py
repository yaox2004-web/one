#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
四维循环看盘法报告 - HTML版（完整版）
包含：大阴实顶 + 四维对比 + 所有量线 + 量柱形态 + 个股解读
"""

import os
import json
from datetime import datetime, timedelta

# ============================================================
# 配置参数（所有参数都要适配当前市场环境）
# ============================================================

# 持仓股列表
HOLDINGS = {
    "sh600584": "长电科技",
    "sz002156": "通富微电",
    "sh603283": "赛腾股份",
    "sz300394": "天孚通信",
    "sh601138": "工业富联",
    "sh601231": "环旭电子",
    "sz300476": "胜宏科技",
    "sh603516": "淳中科技",
}

# 大阴实顶参数
BIG_YIN_THRESHOLD = 0.03  # 阴线实体幅度≥3%
BIG_YIN_LOOKBACK = 60  # 近60日搜索

# 峰顶谷底参数
PEAK_SIDE_MARGIN = 3  # 峰边距（左右各3天）

# 精准线参数
PRECISE_LINE_MIN_POINTS = 3  # 至少3个点
PRECISE_LINE_ERROR = 0.01  # 误差≤1%

# 高量柱参数
HIGH_VOLUME_PERIODS = [20, 60, 120]  # 20日/60日/120日

# 量柱形态参数
DOUBLE_VOLUME_RATIO = 1.9  # 倍量柱阈值
SAME_VOLUME_RANGE = 0.2  # 平量柱±20%
GRADIENT_DAYS = 3  # 梯量柱/缩量柱连续天数

# 时间影响力参数
TIME_IMPACT_RECENT = 10  # 很近（≤10天）
TIME_IMPACT_NEAR = 30  # 较近（11-30天）
TIME_IMPACT_FAR = 60  # 较远（31-60天）

# 数据路径
KLINE_DIR = "/home/runner/work/one/one/data/kline"
OUTPUT_DIR = "/home/runner/work/one/one/data/analysis"


# ============================================================
# 数据读取
# ============================================================

def load_kline(code):
    """读取K线数据"""
    market = code[:2]
    symbol = code[2:]
    filepath = os.path.join(KLINE_DIR, market, f"{symbol}.json")
    
    if not os.path.exists(filepath):
        return None
    
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    # 按日期排序
    data.sort(key=lambda x: x['date'])
    return data


# ============================================================
# 大阴实顶识别
# ============================================================

def find_big_yin_top(df):
    """找最近的大阴实顶"""
    for i in range(len(df)-1, max(len(df)-BIG_YIN_LOOKBACK-1, 0), -1):
        row = df[i]
        open_price = row['open']
        close_price = row['close']
        high_price = row['high']
        low_price = row['low']
        
        # 判断是否是阴线
        if close_price < open_price:
            body = open_price - close_price
            amplitude = high_price - low_price
            if amplitude > 0:
                body_ratio = body / amplitude
                # 实体幅度≥3%
                if body / close_price >= BIG_YIN_THRESHOLD and body_ratio >= 0.5:
                    return {
                        'date': row['date'],
                        'price': open_price,  # 实体顶部
                        'open': open_price,
                        'close': close_price,
                        'high': high_price,
                        'low': low_price,
                        'volume': row['volume'],
                        'days_ago': len(df) - 1 - i
                    }
    return None


# ============================================================
# ① 从右向左看：比较价柱的高低阴阳
# ============================================================

def analyze_right_to_left(df, big_yin):
    """从右向左看：比较价柱的高低阴阳"""
    if not big_yin:
        return {}
    
    # 找到大阴实顶的索引
    big_yin_idx = None
    for i, row in enumerate(df):
        if row['date'] == big_yin['date']:
            big_yin_idx = i
            break
    
    if big_yin_idx is None:
        return {}
    
    # 统计从大阴实顶到今天的阴阳数量
    yang_count = 0
    yin_count = 0
    
    for i in range(big_yin_idx, len(df)):
        row = df[i]
        if row['close'] >= row['open']:
            yang_count += 1
        else:
            yin_count += 1
    
    yin_yang_ratio = yang_count / max(yin_count, 1)
    
    # 价格对比
    current_price = df[-1]['close']
    price_vs_big_yin = (current_price - big_yin['price']) / big_yin['price'] * 100
    
    # 20日高低点
    recent_20 = df[-20:]
    high_20 = max(row['high'] for row in recent_20)
    low_20 = min(row['low'] for row in recent_20)
    
    return {
        'price_vs_big_yin': price_vs_big_yin,
        'yang_count': yang_count,
        'yin_count': yin_count,
        'yin_yang_ratio': yin_yang_ratio,
        'high_20': high_20,
        'low_20': low_20,
    }


# ============================================================
# 量线识别
# ============================================================

def find_balance_line(big_yin):
    """平衡线（大阴实顶）"""
    if not big_yin:
        return None
    return {
        'price': big_yin['price'],
        'date': big_yin['date'],
    }


def find_precise_lines(df):
    """精准线：多个价格点重合"""
    precise_lines = []
    
    # 取最近120天的数据
    recent = df[-120:]
    
    # 统计每个价格出现的次数
    price_counts = {}
    for row in recent:
        price = round(row['close'], 2)
        if price not in price_counts:
            price_counts[price] = []
        price_counts[price].append(row['date'])
    
    # 找出至少3个点重合的价格
    for price, dates in price_counts.items():
        if len(dates) >= PRECISE_LINE_MIN_POINTS:
            precise_lines.append({
                'price': price,
                'points': len(dates),
                'start_date': dates[0],
                'end_date': dates[-1],
            })
    
    # 按点数排序，取前3个
    precise_lines.sort(key=lambda x: x['points'], reverse=True)
    return precise_lines[:3]


def find_trend_lines(df):
    """斜衡线：连接峰顶/谷底的斜线"""
    # 简化版：找最近的上升/下降趋势
    recent_60 = df[-60:]
    
    # 找最近的两个谷底（上升趋势线）
    lows = []
    for i in range(PEAK_SIDE_MARGIN, len(recent_60) - PEAK_SIDE_MARGIN):
        is_low = True
        for j in range(i - PEAK_SIDE_MARGIN, i + PEAK_SIDE_MARGIN + 1):
            if j != i and recent_60[j]['low'] <= recent_60[i]['low']:
                is_low = False
                break
        if is_low:
            lows.append(recent_60[i])
    
    # 找最近的两个峰顶（下降趋势线）
    highs = []
    for i in range(PEAK_SIDE_MARGIN, len(recent_60) - PEAK_SIDE_MARGIN):
        is_high = True
        for j in range(i - PEAK_SIDE_MARGIN, i + PEAK_SIDE_MARGIN + 1):
            if j != i and recent_60[j]['high'] >= recent_60[i]['high']:
                is_high = False
                break
        if is_high:
            highs.append(recent_60[i])
    
    return {
        'up_trend': lows[-2:] if len(lows) >= 2 else None,
        'down_trend': highs[-2:] if len(highs) >= 2 else None,
    }


def find_peak_valley_lines(df):
    """峰顶线/谷底线：多空双方激烈博弈过的高点/低点"""
    result = {}
    
    for period in [20, 60, 120]:
        if len(df) < period:
            continue
        
        recent = df[-period:]
        
        # 找峰顶（需要右确认）
        peaks = []
        for i in range(PEAK_SIDE_MARGIN, len(recent) - PEAK_SIDE_MARGIN):
            is_peak = True
            for j in range(i - PEAK_SIDE_MARGIN, i + PEAK_SIDE_MARGIN + 1):
                if j != i and recent[j]['high'] >= recent[i]['high']:
                    is_peak = False
                    break
            if is_peak:
                peaks.append({
                    'price': recent[i]['high'],
                    'date': recent[i]['date'],
                })
        
        # 找谷底（需要右确认）
        valleys = []
        for i in range(PEAK_SIDE_MARGIN, len(recent) - PEAK_SIDE_MARGIN):
            is_valley = True
            for j in range(i - PEAK_SIDE_MARGIN, i + PEAK_SIDE_MARGIN + 1):
                if j != i and recent[j]['low'] <= recent[i]['low']:
                    is_valley = False
                    break
            if is_valley:
                valleys.append({
                    'price': recent[i]['low'],
                    'date': recent[i]['date'],
                })
        
        result[period] = {
            'peaks': peaks[-3:] if peaks else None,
            'valleys': valleys[-3:] if valleys else None,
        }
    
    return result


def find_high_volume_lines(df):
    """高量柱安全线/风险线"""
    result = {}
    
    for period in HIGH_VOLUME_PERIODS:
        if len(df) < period:
            continue
        
        recent = df[-period:]
        
        # 找高量柱
        max_vol = max(row['volume'] for row in recent)
        high_vol_row = None
        for row in recent:
            if row['volume'] == max_vol:
                high_vol_row = row
                break
        
        if high_vol_row:
            result[period] = {
                'safe_line': high_vol_row['high'],  # 安全线=最高价
                'risk_line': high_vol_row['low'],   # 风险线=最低价
                'date': high_vol_row['date'],
                'volume': max_vol,
            }
    
    return result


# ============================================================
# ② 从上往下看：比较量价的真假大小
# ============================================================

def analyze_top_to_bottom(df, big_yin):
    """从上往下看：比较量价的真假大小"""
    if not big_yin:
        return {}
    
    # 大阴实顶的量
    big_yin_vol = big_yin['volume']
    
    # 今日量
    today_vol = df[-1]['volume']
    
    # 量价真假判断
    if big_yin_vol > today_vol * 1.5:
        big_yin_vol_type = "放量"
    elif big_yin_vol < today_vol * 0.5:
        big_yin_vol_type = "缩量"
    else:
        big_yin_vol_type = "平量"
    
    # 量价真假判断
    if big_yin_vol_type == "缩量":
        volume_price_real = "量缩（真调整）"
    elif big_yin_vol_type == "放量":
        volume_price_real = "量放（可能假跌）"
    else:
        volume_price_real = "量平（正常调整）"
    
    # 今日量柱形态
    today_volume_type = classify_volume_type(df)
    
    return {
        'big_yin_vol_type': big_yin_vol_type,
        'volume_price_real': volume_price_real,
        'today_volume_type': today_volume_type,
    }


def classify_volume_type(df):
    """量柱形态分类"""
    today_vol = df[-1]['volume']
    yesterday_vol = df[-2]['volume'] if len(df) >= 2 else today_vol
    
    # 倍量柱
    if today_vol >= yesterday_vol * DOUBLE_VOLUME_RATIO:
        return "倍量柱"
    
    # 平量柱
    if abs(today_vol - yesterday_vol) / yesterday_vol <= SAME_VOLUME_RANGE:
        return "平量柱"
    
    # 梯量柱（连续3天放量）
    if len(df) >= GRADIENT_DAYS:
        vols = [row['volume'] for row in df[-GRADIENT_DAYS:]]
        if all(vols[i] < vols[i+1] for i in range(len(vols)-1)):
            return "梯量柱"
    
    # 缩量柱（连续3天缩量）
    if len(df) >= GRADIENT_DAYS:
        vols = [row['volume'] for row in df[-GRADIENT_DAYS:]]
        if all(vols[i] > vols[i+1] for i in range(len(vols)-1)):
            return "缩量柱"
    
    # 高量柱/低量柱
    recent_20 = df[-20:]
    max_vol = max(row['volume'] for row in recent_20)
    min_vol = min(row['volume'] for row in recent_20)
    
    if today_vol == max_vol:
        return "高量柱"
    elif today_vol == min_vol:
        return "低量柱"
    else:
        return "普通量柱"


# ============================================================
# ③ 从左往右看：比较量柱的远近多少
# ============================================================

def analyze_left_to_right(df, big_yin):
    """从左往右看：比较量柱的远近多少"""
    if not big_yin:
        return {}
    
    # 时间距离
    days_ago = big_yin['days_ago']
    
    # 时间影响力
    if days_ago <= TIME_IMPACT_RECENT:
        time_impact = "很近（影响力强）"
        time_impact_level = "强"
    elif days_ago <= TIME_IMPACT_NEAR:
        time_impact = "较近（影响力中）"
        time_impact_level = "中"
    elif days_ago <= TIME_IMPACT_FAR:
        time_impact = "较远（影响力弱）"
        time_impact_level = "弱"
    else:
        time_impact = "很远（影响力很弱）"
        time_impact_level = "很弱"
    
    # 量的多少对比
    today_vol = df[-1]['volume']
    big_yin_vol = big_yin['volume']
    vol_ratio = today_vol / big_yin_vol * 100
    
    if today_vol > big_yin_vol:
        vol_compare = "今天量更大"
    elif today_vol < big_yin_vol:
        vol_compare = "今天量更小"
    else:
        vol_compare = "今天量差不多"
    
    # 关键位量影响力
    if time_impact_level == "强" and vol_ratio > 100:
        key_impact = "强"
    elif time_impact_level == "中" or vol_ratio > 80:
        key_impact = "中"
    else:
        key_impact = "弱"
    
    return {
        'days_ago': days_ago,
        'time_impact': time_impact,
        'time_impact_level': time_impact_level,
        'vol_ratio': vol_ratio,
        'vol_compare': vol_compare,
        'key_impact': key_impact,
        'today_vs_key_vol': vol_ratio,
    }


# ============================================================
# ④ 从下往上看：比较量价的长短伸缩
# ============================================================

def analyze_bottom_to_top(df):
    """从下往上看：比较量价的长短伸缩"""
    today = df[-1]
    
    # 量柱长短
    recent_20 = df[-20:]
    max_vol = max(row['volume'] for row in recent_20)
    min_vol = min(row['volume'] for row in recent_20)
    today_vol = today['volume']
    
    vol_position = (today_vol - min_vol) / (max_vol - min_vol) * 100 if max_vol > min_vol else 50
    
    if vol_position >= 80:
        vol_length = "长量柱（天量）"
    elif vol_position <= 20:
        vol_length = "短量柱（地量）"
    else:
        vol_length = "正常量柱"
    
    # 价柱伸缩
    amplitude = today['high'] - today['low']
    recent_20_amplitudes = [(row['high'] - row['low']) for row in recent_20]
    max_amplitude = max(recent_20_amplitudes)
    min_amplitude = min(recent_20_amplitudes)
    
    amplitude_position = (amplitude - min_amplitude) / (max_amplitude - min_amplitude) * 100 if max_amplitude > min_amplitude else 50
    
    if amplitude_position >= 80:
        price_length = "长价柱（振幅大）"
    elif amplitude_position <= 20:
        price_length = "短价柱（振幅小）"
    else:
        price_length = "正常价柱"
    
    # 实体长短
    body = abs(today['close'] - today['open'])
    body_ratio = body / amplitude * 100 if amplitude > 0 else 0
    
    if body_ratio >= 70:
        body_length = "长实体"
    elif body_ratio <= 30:
        body_length = "短实体（影线多）"
    else:
        body_length = "正常实体"
    
    return {
        'vol_length': vol_length,
        'vol_position': vol_position,
        'price_length': price_length,
        'body_length': body_length,
        'body_ratio': body_ratio,
    }


# ============================================================
# ⑤ 和历史对比
# ============================================================

def analyze_history_compare(df):
    """和历史对比"""
    current_price = df[-1]['close']
    result = {}
    
    for period in [20, 60, 120]:
        if len(df) < period:
            continue
        
        recent = df[-period:]
        high = max(row['high'] for row in recent)
        low = min(row['low'] for row in recent)
        
        result[period] = {
            'high': high,
            'low': low,
            'vs_high': (current_price - high) / high * 100,
            'vs_low': (current_price - low) / low * 100,
        }
    
    return result


# ============================================================
# 个股解读
# ============================================================

def generate_stock_interpretation(stock_name, big_yin, step1, step2, step3, step4, history):
    """生成个股解读（客观描述，不做主观判断）"""
    lines = []
    
    # 大阴实顶
    if big_yin:
        current_price = step1.get('price_vs_big_yin', 0)
        if current_price > 0:
            lines.append(f'当前价格在大阴实顶（{big_yin["price"]:.2f}元，{big_yin["date"]}）上方，高出{current_price:.2f}%。说明大阴实顶那天卖出的人，卖出后价格又涨回来了。')
        else:
            lines.append(f'当前价格在大阴实顶（{big_yin["price"]:.2f}元，{big_yin["date"]}）下方，低出{abs(current_price):.2f}%。说明大阴实顶那天卖出的人，卖出后价格还在跌。')
    
    # 阴阳对比
    yang_count = step1.get('yang_count', 0)
    yin_count = step1.get('yin_count', 0)
    yin_yang_ratio = step1.get('yin_yang_ratio', 0)
    lines.append(f'从大阴实顶到今天，阳线{yang_count}根，阴线{yin_count}根，阴阳比{yin_yang_ratio:.2f}，多空双方力量{"相当" if 0.8 <= yin_yang_ratio <= 1.25 else ("多方占优" if yin_yang_ratio > 1.25 else "空方占优")}。')
    
    # 时间距离
    days_ago = step3.get('days_ago', 0)
    time_impact = step3.get('time_impact', '')
    lines.append(f'大阴实顶发生在{days_ago}天前，时间{time_impact.split("（")[0]}，这个位置的记忆{"还很新鲜" if days_ago <= 10 else ("还比较新鲜" if days_ago <= 30 else "已经比较模糊了")}。')
    
    # 量的对比
    vol_ratio = step3.get('vol_ratio', 0)
    if vol_ratio > 120:
        lines.append(f'今天的成交量是大阴实顶那天的{vol_ratio:.1f}%，说明今天的博弈比那天还激烈。')
    elif vol_ratio < 80:
        lines.append(f'今天的成交量是大阴实顶那天的{vol_ratio:.1f}%，说明今天的博弈比那天弱很多。')
    else:
        lines.append(f'今天的成交量是大阴实顶那天的{vol_ratio:.1f}%，说明今天的博弈和那天差不多。')
    
    # 量价建构
    vol_length = step4.get('vol_length', '')
    price_length = step4.get('price_length', '')
    lines.append(f'今天的量柱：{vol_length}；今天的价柱：{price_length}。')
    
    # 实体占比
    body_ratio = step4.get('body_ratio', 0)
    lines.append(f'今天K线实体占比{body_ratio:.1f}%，实体{"较长" if body_ratio >= 70 else ("较短" if body_ratio <= 30 else "正常")}，说明今天多空一方{"赢了，而且赢得比较彻底" if body_ratio >= 70 else ("双方都没赢，还在拉锯" if body_ratio <= 30 else "一方赢了，但赢得不彻底")}。')
    
    # 历史对比
    if 120 in history:
        h = history[120]
        position = (h['vs_low'] - h['vs_high']) / (h['vs_high'] - h['vs_low']) * 100 if h['vs_high'] != h['vs_low'] else 50
        lines.append(f'当前价格在近120日{"高位" if position >= 70 else ("低位" if position <= 30 else "中位")}。')
    
    return lines


# ============================================================
# ⑥ 全景总结
# ============================================================

def generate_summary(stock_name, df, big_yin, step4):
    """生成全景总结"""
    today = df[-1]
    pct_change = (today['close'] - today['open']) / today['open'] * 100
    
    # 判断多空
    if today['close'] >= today['open']:
        direction = "买方占优"
        color_class = "price-up"
    else:
        direction = "卖方占优"
        color_class = "price-down"
    
    # 位置
    recent_20 = df[-20:]
    recent_60 = df[-60:]
    recent_120 = df[-120:]
    
    high_120 = max(row['high'] for row in recent_120)
    low_120 = min(row['low'] for row in recent_120)
    position = (today['close'] - low_120) / (high_120 - low_120) * 100 if high_120 > low_120 else 50
    
    if position >= 70:
        pos_text = "高位"
    elif position <= 30:
        pos_text = "低位"
    else:
        pos_text = "中位"
    
    # 近期涨跌
    pct_3d = (today['close'] - df[-4]['close']) / df[-4]['close'] * 100 if len(df) >= 4 else 0
    pct_5d = (today['close'] - df[-6]['close']) / df[-6]['close'] * 100 if len(df) >= 6 else 0
    
    lines = [
        f'今日{"+" if pct_change >= 0 else ""}{pct_change:.2f}%，{pos_text}，{direction}。',
        f'量柱：{step4.get("vol_length", "")}，价柱：{step4.get("price_length", "")}。',
    ]
    
    if big_yin:
        lines.append(f'大阴实顶：{big_yin["price"]:.2f}（{big_yin["date"]}）')
    
    lines.append(f'近3日涨跌：{pct_3d:+.2f}%，近5日涨跌：{pct_5d:+.2f}%。')
    
    return lines


# ============================================================
# HTML生成
# ============================================================

def generate_html(stocks_data, today_str):
    """生成完整HTML报告"""
    
    # 信号说明区（完整版）
    signal_guide = '''
        <!-- 信号说明区（顶部，只放一次） -->
        <div class="signal-guide">
            <h2>四维看盘法说明</h2>
            
            <div class="signal-item">
                <h3>起点：大阴实顶</h3>
                <p><strong>定义：</strong>从今天往左找最近的中大阴线（实体幅度≥3%），其实体顶部就是"大阴实顶"</p>
                <p><strong>原理：</strong>大阴实顶是多空双方上次休战的"警戒点"，下次争夺的"起动点"</p>
                <p><strong>参数：</strong>近60日搜索，阴线实体幅度≥3%</p>
                <p><strong>设计思路：</strong>以最近的大阴线为基准，建立对比锚点</p>
                <p><strong>注意事项：</strong>必须是最近的，不能用太远的</p>
                <p class="source">来源：股海明灯（量学官网）</p>
            </div>
            
            <div class="signal-item">
                <h3>① 从右向左看：比较价柱的高低阴阳</h3>
                <p><strong>视线：</strong>从今天往左，往大阴实顶方向看</p>
                <p><strong>对比内容：</strong>价格高低、阴阳数量、阴阳比</p>
                <p><strong>参数：</strong>统计从大阴实顶到今天的所有K线</p>
                <p><strong>设计思路：</strong>看多空双方力量对比</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>② 从上往下看：比较量价的真假大小</h3>
                <p><strong>视线：</strong>从大阴实顶的价柱往下看量柱</p>
                <p><strong>对比内容：</strong>量柱大小、量价真假</p>
                <p><strong>量柱形态：</strong>高量柱、低量柱、平量柱、倍量柱、梯量柱、缩量柱</p>
                <p><strong>设计思路：</strong>判断大阴实顶那天的量是真还是假</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>③ 从左往右看：比较量柱的远近多少</h3>
                <p><strong>视线：</strong>从大阴实顶的量柱往右看，看到今天的量柱</p>
                <p><strong>对比内容：</strong>时间距离、量的多少对比</p>
                <p><strong>时间影响力：</strong>很近（≤10天）、较近（11-30天）、较远（31-60天）、很远（>60天）</p>
                <p><strong>关键位量影响力：</strong>强/中/弱</p>
                <p><strong>设计思路：</strong>看大阴实顶的量对当下的影响力</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>④ 从下往上看：比较量价的长短伸缩</h3>
                <p><strong>视线：</strong>从今天的量柱往上看价柱</p>
                <p><strong>对比内容：</strong>量柱长短、价柱伸缩、实体长短</p>
                <p><strong>实体占比：</strong>实体长度/振幅长度</p>
                <p><strong>设计思路：</strong>判断当下的量价建构</p>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>量线体系</h3>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>平衡线（大阴实顶）</h3>
                <p><strong>定义：</strong>最近大阴线的实体顶部</p>
                <p><strong>原理：</strong>多空双方上次休战的"警戒点"</p>
                <p><strong>参数：</strong>近60日搜索</p>
                <p><strong>设计思路：</strong>以最近的大阴实顶为基准</p>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>精准线</h3>
                <p><strong>定义：</strong>多个价格点重合在同一水平线上</p>
                <p><strong>原理：</strong>多空双方多次在同一价位博弈，形成"精准"支撑/压力</p>
                <p><strong>参数：</strong>至少3个价格点重合，误差≤1%</p>
                <p><strong>设计思路：</strong>找多空双方反复争夺的关键价位</p>
                <p><strong>注意事项：</strong>需要右确认（至少3个点）</p>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>斜衡线</h3>
                <p><strong>定义：</strong>连接两个或多个峰顶/谷底的斜线</p>
                <p><strong>原理：</strong>反映趋势的斜率和方向</p>
                <p><strong>参数：</strong>至少2个点，上升斜衡线=支撑，下降斜衡线=阻力</p>
                <p><strong>设计思路：</strong>看趋势的方向和斜率</p>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>峰顶线/谷底线</h3>
                <p><strong>定义：</strong>多空双方激烈博弈过的高点/低点</p>
                <p><strong>原理：</strong>峰顶=卖方赢了，谷底线=买方赢了</p>
                <p><strong>参数：</strong>峰边距≥3天（左右各3天，取中间最高/最低），成交量要求适配当前环境</p>
                <p><strong>设计思路：</strong>找真正博弈过的关键位，不用左侧历史极值法</p>
                <p><strong>注意事项：</strong>需要右确认（峰边距≥3天）</p>
                <p><strong>没有峰顶/谷底的情况：</strong>无峰顶=寻顶中（偏强势），无谷底=寻底中（偏弱势）</p>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>高量柱安全线/风险线</h3>
                <p><strong>定义：</strong>高量柱的最高价=安全线，最低价=风险线</p>
                <p><strong>原理：</strong>高量柱那天多空博弈最激烈，最高价和最低价就是关键位</p>
                <p><strong>参数：</strong>20日/60日/120日高量柱</p>
                <p><strong>设计思路：</strong>以高量柱的高低点为基准</p>
                <p><strong>注意事项：</strong>取实（最高价/最低价），不取虚</p>
                <p class="source">来源：股海明灯《量线捉涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>量柱六种形态</h3>
                <p class="source">来源：股海明灯《量柱擒涨停》黑马王子著</p>
            </div>
            
            <div class="signal-item">
                <h3>高量柱</h3>
                <p><strong>定义：</strong>近N日最大成交量</p>
                <p><strong>原理：</strong>多空博弈最激烈的一天</p>
                <p><strong>参数：</strong>近20日/60日/120日天量</p>
                <p><strong>设计思路：</strong>找博弈最激烈的位置</p>
            </div>
            
            <div class="signal-item">
                <h3>低量柱</h3>
                <p><strong>定义：</strong>近N日最小成交量</p>
                <p><strong>原理：</strong>多空双方都休息了，无人关注</p>
                <p><strong>参数：</strong>近20日/60日/120日地量</p>
                <p><strong>设计思路：</strong>找无人关注的位置</p>
            </div>
            
            <div class="signal-item">
                <h3>平量柱</h3>
                <p><strong>定义：</strong>与昨日量差不多（±20%以内）</p>
                <p><strong>原理：</strong>多空双方力量平衡</p>
                <p><strong>参数：</strong>±20%以内</p>
                <p><strong>设计思路：</strong>看量能是否平稳</p>
            </div>
            
            <div class="signal-item">
                <h3>倍量柱</h3>
                <p><strong>定义：</strong>今日量≥昨日量×1.9</p>
                <p><strong>原理：</strong>多空一方突然发力</p>
                <p><strong>参数：</strong>≥1.9倍</p>
                <p><strong>设计思路：</strong>看是否有突然放量</p>
            </div>
            
            <div class="signal-item">
                <h3>梯量柱</h3>
                <p><strong>定义：</strong>连续3天放量</p>
                <p><strong>原理：</strong>多空双方逐步加码</p>
                <p><strong>参数：</strong>连续3天递增</p>
                <p><strong>设计思路：</strong>看是否有连续放量</p>
            </div>
            
            <div class="signal-item">
                <h3>缩量柱</h3>
                <p><strong>定义：</strong>连续3天缩量</p>
                <p><strong>原理：</strong>多空双方逐步退场</p>
                <p><strong>参数：</strong>连续3天递减</p>
                <p><strong>设计思路：</strong>看是否有连续缩量</p>
            </div>
            
            <div class="signal-item">
                <h3>关键位量影响力</h3>
                <p><strong>定义：</strong>判断关键位的量对当下的影响力</p>
                <p><strong>原理：</strong>量越大、时间越近，影响力越强</p>
                <p><strong>参数：</strong>强/中/弱</p>
                <p><strong>设计思路：</strong>综合时间距离和量大小判断</p>
            </div>
            
            <div class="signal-item">
                <h3>个股解读</h3>
                <p><strong>原则：</strong>客观描述，不做主观判断</p>
                <p><strong>方法：</strong>用四维看盘法逐步描述</p>
            </div>
            
            <div class="signal-item">
                <h3>最高原则</h3>
                <p><strong>所有参数、阈值都要适配当前最新市场环境</strong></p>
                <p><strong>代码不要写死，能用参数阈值的就用参数阈值</strong></p>
            </div>
        </div>
'''
    
    # 个股卡片
    stock_cards_html = ""
    
    for stock in stocks_data:
        stock_cards_html += f'''
        <div class="stock-card">
            <div class="stock-header">
                <div>
                    <div class="stock-name">{stock['name']}</div>
                    <div class="stock-code">{stock['code']}</div>
                </div>
                <div class="stock-price {'price-up' if stock['pct_change'] >= 0 else 'price-down'}">{stock['price']:.2f}元 ({'+' if stock['pct_change'] >= 0 else ''}{stock['pct_change']:.2f}%)</div>
            </div>
'''
        
        # 起点：大阴实顶
        if stock['big_yin']:
            stock_cards_html += f'''
            <div class="step-section">
                <div class="step-title">起点：大阴实顶</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">大阴实顶（近60日）</div>
                            <div class="value">{stock['big_yin']['price']:.2f}（{stock['big_yin']['date']}）</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">当前位置</div>
                            <div class="value" style="color:#94a3b8">{'上方' if stock['step1']['price_vs_big_yin'] > 0 else '下方'}</div>
                        </div>
                    </div>
                </div>
            </div>
'''
        else:
            stock_cards_html += '''
            <div class="step-section">
                <div class="step-title">起点：大阴实顶</div>
                <div class="step-content">
                    <p style="color:#94a3b8">近60日无大阴实顶</p>
                </div>
            </div>
'''
        
        # ① 从右向左看
        if stock['step1']:
            s1 = stock['step1']
            stock_cards_html += f'''
            <div class="step-section">
                <div class="step-title">① 从右向左看：比较价柱的高低阴阳</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">价格vs大阴实顶</div>
                            <div class="value">{s1['price_vs_big_yin']:+.2f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">阳线/阴线数量</div>
                            <div class="value">{s1['yang_count']}阳 / {s1['yin_count']}阴</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">阴阳比</div>
                            <div class="value">{s1['yin_yang_ratio']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日高点</div>
                            <div class="value">{s1['high_20']:.2f}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">20日低点</div>
                            <div class="value">{s1['low_20']:.2f}</div>
                        </div>
                    </div>
                </div>
            </div>
'''
        
        # 量线体系
        stock_cards_html += '''
            <div class="step-section">
                <div class="step-title">量线体系</div>
                <div class="step-content">
'''
        
        # 平衡线
        if stock['balance_line']:
            stock_cards_html += f'''
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">平衡线（大阴实顶）</div>
                            <div class="value">{stock['balance_line']['price']:.2f}（{stock['balance_line']['date']}）</div>
                        </div>
                    </div>
'''
        
        # 精准线
        if stock['precise_lines']:
            stock_cards_html += '''
                    <div style="margin-top:10px;">
                        <p style="color:#60a5fa; font-size:12px; margin-bottom:5px;">精准线：</p>
                        <div class="grid-2">
'''
            for i, pl in enumerate(stock['precise_lines']):
                stock_cards_html += f'''
                <div class="grid-item">
                    <div class="label">精准线{i+1}（{pl['points']}点）</div>
                    <div class="value">{pl['price']:.2f}（{pl['start_date']}~{pl['end_date']}）</div>
                </div>
'''
            stock_cards_html += '''
                        </div>
                    </div>
'''
        
        # 斜衡线
        stock_cards_html += '''
                    <div style="margin-top:10px;">
                        <p style="color:#60a5fa; font-size:12px; margin-bottom:5px;">斜衡线：</p>
                        <div class="grid-2">
'''
        if stock['trend_lines']['up_trend']:
            up = stock['trend_lines']['up_trend']
            stock_cards_html += f'''
        <div class="grid-item">
            <div class="label">上升斜衡线（支撑）</div>
            <div class="value">
                {up[0]['low']:.2f}（{up[0]['date']}）
                → {up[1]['low']:.2f}（{up[1]['date']}）
            </div>
        </div>
'''
        else:
            stock_cards_html += '''
        <div class="grid-item">
            <div class="label">上升斜衡线（支撑）</div>
            <div class="value value-none">无</div>
        </div>
'''
        
        if stock['trend_lines']['down_trend']:
            down = stock['trend_lines']['down_trend']
            stock_cards_html += f'''
        <div class="grid-item">
            <div class="label">下降斜衡线（阻力）</div>
            <div class="value">
                {down[0]['high']:.2f}（{down[0]['date']}）
                → {down[1]['high']:.2f}（{down[1]['date']}）
            </div>
        </div>
'''
        else:
            stock_cards_html += '''
        <div class="grid-item">
            <div class="label">下降斜衡线（阻力）</div>
            <div class="value value-none">无</div>
        </div>
'''
        
        stock_cards_html += '''
                        </div>
                    </div>
'''
        
        # 峰顶线/谷底线
        stock_cards_html += '''
                    <div style="margin-top:10px;">
                        <p style="color:#60a5fa; font-size:12px; margin-bottom:5px;">峰顶线/谷底线：</p>
                        <div class="grid-2">
'''
        for period in [20, 60, 120]:
            if period in stock['peak_valley_lines']:
                pvl = stock['peak_valley_lines'][period]
                
                if pvl['peaks']:
                    peak = pvl['peaks'][-1]
                    stock_cards_html += f'''
    <div class="grid-item">
        <div class="label">{period}日峰顶线</div>
        <div class="value">{peak['price']:.2f}（{peak['date']}）</div>
    </div>
'''
                else:
                    stock_cards_html += f'''
    <div class="grid-item">
        <div class="label">{period}日峰顶线</div>
        <div class="value value-none value-strong">无（寻顶中·偏强势）</div>
    </div>
'''
                
                if pvl['valleys']:
                    valley = pvl['valleys'][-1]
                    stock_cards_html += f'''
    <div class="grid-item">
        <div class="label">{period}日谷底线</div>
        <div class="value">{valley['price']:.2f}（{valley['date']}）</div>
    </div>
'''
                else:
                    stock_cards_html += f'''
    <div class="grid-item">
        <div class="label">{period}日谷底线</div>
        <div class="value value-none value-weak">无（寻底中·偏弱势）</div>
    </div>
'''
        
        stock_cards_html += '''
                        </div>
                    </div>
'''
        
        # 高量柱安全线/风险线
        stock_cards_html += '''
                    <div style="margin-top:10px;">
                        <p style="color:#60a5fa; font-size:12px; margin-bottom:5px;">高量柱安全线/风险线：</p>
                        <div class="grid-2">
'''
        for period in [20, 60, 120]:
            if period in stock['high_volume_lines']:
                hvl = stock['high_volume_lines'][period]
                stock_cards_html += f'''
                            <div class="grid-item">
                                <div class="label">{period}日安全线</div>
                                <div class="value">{hvl['safe_line']:.2f}（{hvl['date']}）</div>
                            </div>
                            <div class="grid-item">
                                <div class="label">{period}日风险线</div>
                                <div class="value">{hvl['risk_line']:.2f}（{hvl['date']}）</div>
                            </div>
'''
        
        stock_cards_html += '''
                        </div>
                    </div>
                </div>
            </div>
'''
        
        # ② 从上往下看
        if stock['step2']:
            s2 = stock['step2']
            stock_cards_html += f'''
            <div class="step-section">
                <div class="step-title">② 从上往下看：比较量价的真假大小</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">大阴实顶的量</div>
                            <div class="value">{s2['big_yin_vol_type']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量价真假判断</div>
                            <div class="value">{s2['volume_price_real']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">今日量柱形态</div>
                            <div class="value">{s2['today_volume_type']}</div>
                        </div>
                    </div>
                </div>
            </div>
'''
        
        # ③ 从左往右看
        if stock['step3']:
            s3 = stock['step3']
            stock_cards_html += f'''
            <div class="step-section">
                <div class="step-title">③ 从左往右看：比较量柱的远近多少</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">时间距离</div>
                            <div class="value">{s3['days_ago']}天前</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">时间影响力</div>
                            <div class="value">{s3['time_impact']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">今天量vs大阴实顶量</div>
                            <div class="value">{s3['vol_ratio']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量的多少对比</div>
                            <div class="value">{s3['vol_compare']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">关键位量影响力</div>
                            <div class="value" style="color:{'#ef4444' if s3['key_impact'] == '强' else '#fbbf24' if s3['key_impact'] == '中' else '#22c55e'}">{s3['key_impact']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">今日量vs关键位量</div>
                            <div class="value">{s3['today_vs_key_vol']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
'''
        
        # ④ 从下往上看
        if stock['step4']:
            s4 = stock['step4']
            stock_cards_html += f'''
            <div class="step-section">
                <div class="step-title">④ 从下往上看：比较量价的长短伸缩</div>
                <div class="step-content">
                    <div class="grid-2">
                        <div class="grid-item">
                            <div class="label">量柱长短</div>
                            <div class="value">{s4['vol_length']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">量能位置(20日)</div>
                            <div class="value">{s4['vol_position']:.1f}%</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">价柱伸缩</div>
                            <div class="value">{s4['price_length']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">实体长短</div>
                            <div class="value">{s4['body_length']}</div>
                        </div>
                        <div class="grid-item">
                            <div class="label">实体占比</div>
                            <div class="value">{s4['body_ratio']:.1f}%</div>
                        </div>
                    </div>
                </div>
            </div>
'''
        
        # ⑤ 和历史对比
        if stock['history']:
            stock_cards_html += '''
            <div class="step-section">
                <div class="step-title">⑤ 和历史对比</div>
                <div class="step-content">
'''
            for period in [20, 60, 120]:
                if period in stock['history']:
                    h = stock['history'][period]
                    stock_cards_html += f'''
                    <p><strong>{'短期' if period == 20 else '中期' if period == 60 else '长期'}({period}日)：</strong>
                        离高点 {h['vs_high']:+.2f}% | 
                        离低点 {h['vs_low']:+.2f}%
                    </p>
'''
            stock_cards_html += '''
                </div>
            </div>
'''
        
        # 个股解读
        if stock['interpretation']:
            stock_cards_html += '''
            <div class="step-section">
                <div class="step-title">📖 个股解读（四维看盘法）</div>
                <div class="step-content" style="background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);">
'''
            for line in stock['interpretation']:
                stock_cards_html += f'''
                    <p style='margin:8px 0; padding-left:10px; border-left: 3px solid #fbbf24;'>{line}</p>
'''
            stock_cards_html += '''
                </div>
            </div>
'''
        
        # ⑥ 全景总结
        if stock['summary']:
            stock_cards_html += '''
            <div class="step-section">
                <div class="step-title">⑥ 全景总结</div>
                <div class="summary-box">
                    <p>
'''
            for line in stock['summary']:
                stock_cards_html += f'''
                        {line}<br>
'''
            stock_cards_html += '''
                    </p>
                </div>
            </div>
'''
        
        stock_cards_html += '''
        </div>
'''
    
    # 完整HTML
    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>四维循环看盘报告 - {today_str}</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; 
            background: #0f172a; 
            color: #e2e8f0; 
            line-height: 1.6;
            padding: 20px;
        }}
        .container {{ max-width: 900px; margin: 0 auto; }}
        .header {{ 
            background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%); 
            color: white; 
            padding: 30px; 
            border-radius: 12px; 
            margin-bottom: 20px;
            border-left: 4px solid #fbbf24;
        }}
        .header h1 {{ font-size: 24px; color: #fbbf24; margin-bottom: 8px; }}
        .header .date {{ opacity: 0.8; font-size: 14px; }}
        
        .signal-guide {{
            background: #1e293b;
            border-radius: 12px;
            padding: 20px;
            margin-bottom: 20px;
            border: 1px solid #334155;
        }}
        .signal-guide h2 {{
            font-size: 18px;
            color: #fbbf24;
            margin-bottom: 15px;
            padding-bottom: 10px;
            border-bottom: 1px solid #334155;
        }}
        .signal-item {{
            margin-bottom: 12px;
            padding: 10px;
            background: #0f172a;
            border-radius: 8px;
        }}
        .signal-item h3 {{
            font-size: 14px;
            color: #60a5fa;
            margin-bottom: 6px;
        }}
        .signal-item p {{
            font-size: 12px;
            color: #cbd5e1;
            margin-bottom: 4px;
        }}
        .signal-item .source {{
            font-size: 11px;
            color: #94a3b8;
            font-style: italic;
        }}
        
        .stock-card {{ 
            background: #1e293b; 
            border-radius: 12px; 
            padding: 20px; 
            margin-bottom: 15px; 
            border: 1px solid #334155;
        }}
        .stock-header {{ 
            display: flex; 
            justify-content: space-between; 
            align-items: center; 
            margin-bottom: 15px; 
            padding-bottom: 15px; 
            border-bottom: 1px solid #334155;
        }}
        .stock-name {{ font-size: 18px; font-weight: bold; color: #e2e8f0; }}
        .stock-code {{ font-size: 12px; color: #94a3b8; }}
        .stock-price {{ font-size: 22px; font-weight: bold; }}
        .price-up {{ color: #ef4444; }}
        .price-down {{ color: #22c55e; }}
        
        .step-section {{ margin-bottom: 15px; }}
        .step-title {{ 
            font-size: 14px; 
            font-weight: bold; 
            color: #60a5fa; 
            margin-bottom: 8px; 
            padding-left: 8px; 
            border-left: 3px solid #fbbf24; 
        }}
        .step-content {{ 
            background: #0f172a; 
            padding: 12px; 
            border-radius: 8px; 
            font-size: 13px; 
            color: #cbd5e1; 
        }}
        .step-content p {{ margin-bottom: 4px; }}
        
        .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }}
        .grid-item {{ 
            background: #0f172a; 
            padding: 8px; 
            border-radius: 6px; 
            font-size: 13px; 
        }}
        .grid-item .label {{ color: #94a3b8; font-size: 11px; }}
        .grid-item .value {{ font-weight: bold; color: #e2e8f0; font-size: 12px; }}
        .grid-item .value-none {{ color: #94a3b8; font-weight: normal; font-size: 11px; }}
        .grid-item .value-strong {{ color: #ef4444; font-weight: normal; font-size: 11px; }}
        .grid-item .value-weak {{ color: #22c55e; font-weight: normal; font-size: 11px; }}
        
        .summary-box {{
            background: linear-gradient(135deg, #1e3a8a 0%, #1e40af 100%);
            padding: 15px;
            border-radius: 8px;
            margin-top: 10px;
        }}
        .summary-box p {{ margin: 0; color: #fbbf24; font-size: 13px; line-height: 1.8; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>四维循环看盘报告</h1>
            <div class="date">{today_str}</div>
            <div class="note" style="margin-top:10px;font-size:13px;opacity:0.7">量学原版：大阴实顶 + 四维对比 + 所有量线 + 个股解读</div>
        </div>
        
{signal_guide}
        
{stock_cards_html}
        
    </div>
</body>
</html>'''
    
    return html


# ============================================================
# 主函数
# ============================================================

def main():
    print("=" * 60)
    print("四维循环看盘报告 - HTML版（完整版）")
    print("=" * 60)
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    stocks_data = []
    
    for code, name in HOLDINGS.items():
        print(f"\n已生成：{name}")
        
        # 读取数据
        df = load_kline(code)
        if not df or len(df) < 120:
            print(f"  数据不够，跳过")
            continue
        
        today = df[-1]
        price = today['close']
        pct_change = (today['close'] - today['open']) / today['open'] * 100
        
        # 找大阴实顶
        big_yin = find_big_yin_top(df)
        
        # ① 从右向左看
        step1 = analyze_right_to_left(df, big_yin)
        
        # 量线识别
        balance_line = find_balance_line(big_yin)
        precise_lines = find_precise_lines(df)
        trend_lines = find_trend_lines(df)
        peak_valley_lines = find_peak_valley_lines(df)
        high_volume_lines = find_high_volume_lines(df)
        
        # ② 从上往下看
        step2 = analyze_top_to_bottom(df, big_yin)
        
        # ③ 从左往右看
        step3 = analyze_left_to_right(df, big_yin)
        
        # ④ 从下往上看
        step4 = analyze_bottom_to_top(df)
        
        # ⑤ 和历史对比
        history = analyze_history_compare(df)
        
        # 个股解读
        interpretation = generate_stock_interpretation(
            name, big_yin, step1, step2, step3, step4, history
        )
        
        # ⑥ 全景总结
        summary = generate_summary(name, df, big_yin, step4)
        
        stocks_data.append({
            'code': code,
            'name': name,
            'price': price,
            'pct_change': pct_change,
            'big_yin': big_yin,
            'step1': step1,
            'step2': step2,
            'step3': step3,
            'step4': step4,
            'history': history,
            'balance_line': balance_line,
            'precise_lines': precise_lines,
            'trend_lines': trend_lines,
            'peak_valley_lines': peak_valley_lines,
            'high_volume_lines': high_volume_lines,
            'interpretation': interpretation,
            'summary': summary,
        })
    
    # 生成HTML
    html_content = generate_html(stocks_data, today_str)
    
    # 保存
    output_file = os.path.join(OUTPUT_DIR, f"my_holdings_4d_report_{today_str}.html")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(html_content)
    
    print(f"\n已生成HTML报告: {output_file}")


if __name__ == "__main__":
    main()
