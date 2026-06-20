"""
评分模型服务
实现 100 分制评分体系：
  quality_score (30) + valuation_score (20) + growth_score (20) + trend_score (20) + risk_score (10)
"""
from typing import Optional
from datetime import date
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.daily_price import DailyPrice
from app.models.financial_metric import FinancialMetric
from app.models.technical_indicator import TechnicalIndicator
from app.models.stock_score import StockScore


def calculate_quality_score(financial: FinancialMetric, industry: str = "") -> tuple[float, list[dict]]:
    """
    质量评分（满分 30）
    - ROE > 15%: +10
    - 经营现金流为正: +8
    - 毛利率稳定或大于行业中位: +6
    - 资产负债率合理: +6（金融行业使用不同的阈值）
    """
    # 金融行业负债率阈值（银行/保险/券商负债率 80-95% 是正常的）
    is_financial = industry in ("银行", "保险", "券商", "金融", "Banking", "Insurance", "Securities")
    score = 0
    details = []

    # ROE 评分
    if financial.roe is not None:
        if financial.roe > 15:
            score += 10
            details.append({"item": "ROE", "value": f"{financial.roe:.1f}%", "score": 10, "max": 10, "status": "优秀"})
        elif financial.roe > 10:
            score += 6
            details.append({"item": "ROE", "value": f"{financial.roe:.1f}%", "score": 6, "max": 10, "status": "良好"})
        elif financial.roe > 5:
            score += 3
            details.append({"item": "ROE", "value": f"{financial.roe:.1f}%", "score": 3, "max": 10, "status": "一般"})
        else:
            details.append({"item": "ROE", "value": f"{financial.roe:.1f}%", "score": 0, "max": 10, "status": "较差"})
    else:
        details.append({"item": "ROE", "value": "N/A", "score": 0, "max": 10, "status": "无数据"})

    # 经营现金流评分（东方财富返回的是每股值，雅虎返回的是总值亿）
    if financial.operating_cashflow is not None:
        if financial.operating_cashflow > 0:
            score += 8
            details.append({"item": "经营现金流", "value": f"{financial.operating_cashflow:.2f}", "score": 8, "max": 8, "status": "正向"})
        else:
            details.append({"item": "经营现金流", "value": f"{financial.operating_cashflow:.2f}", "score": 0, "max": 8, "status": "负向"})
    else:
        details.append({"item": "经营现金流", "value": "N/A", "score": 0, "max": 8, "status": "无数据"})

    # 毛利率评分
    if financial.gross_margin is not None:
        if financial.gross_margin > 40:
            score += 6
            details.append({"item": "毛利率", "value": f"{financial.gross_margin:.1f}%", "score": 6, "max": 6, "status": "优秀"})
        elif financial.gross_margin > 25:
            score += 4
            details.append({"item": "毛利率", "value": f"{financial.gross_margin:.1f}%", "score": 4, "max": 6, "status": "良好"})
        elif financial.gross_margin > 15:
            score += 2
            details.append({"item": "毛利率", "value": f"{financial.gross_margin:.1f}%", "score": 2, "max": 6, "status": "一般"})
        else:
            details.append({"item": "毛利率", "value": f"{financial.gross_margin:.1f}%", "score": 0, "max": 6, "status": "较低"})
    else:
        details.append({"item": "毛利率", "value": "N/A", "score": 0, "max": 6, "status": "无数据"})

    # 资产负债率评分（金融行业使用更宽松的阈值）
    if financial.debt_ratio is not None:
        if is_financial:
            # 金融行业：负债率 85-95% 是正常的
            if financial.debt_ratio < 92:
                score += 6
                details.append({"item": "资产负债率", "value": f"{financial.debt_ratio:.1f}%", "score": 6, "max": 6, "status": "健康"})
            elif financial.debt_ratio < 95:
                score += 4
                details.append({"item": "资产负债率", "value": f"{financial.debt_ratio:.1f}%", "score": 4, "max": 6, "status": "合理"})
            elif financial.debt_ratio < 98:
                score += 2
                details.append({"item": "资产负债率", "value": f"{financial.debt_ratio:.1f}%", "score": 2, "max": 6, "status": "偏高"})
            else:
                details.append({"item": "资产负债率", "value": f"{financial.debt_ratio:.1f}%", "score": 0, "max": 6, "status": "过高"})
        else:
            if financial.debt_ratio < 40:
                score += 6
                details.append({"item": "资产负债率", "value": f"{financial.debt_ratio:.1f}%", "score": 6, "max": 6, "status": "健康"})
            elif financial.debt_ratio < 60:
                score += 4
                details.append({"item": "资产负债率", "value": f"{financial.debt_ratio:.1f}%", "score": 4, "max": 6, "status": "合理"})
            elif financial.debt_ratio < 75:
                score += 2
                details.append({"item": "资产负债率", "value": f"{financial.debt_ratio:.1f}%", "score": 2, "max": 6, "status": "偏高"})
            else:
                details.append({"item": "资产负债率", "value": f"{financial.debt_ratio:.1f}%", "score": 0, "max": 6, "status": "过高"})
    else:
        details.append({"item": "资产负债率", "value": "N/A", "score": 0, "max": 6, "status": "无数据"})

    return score, details


def calculate_valuation_score(price: DailyPrice, financial: FinancialMetric) -> tuple[float, list[dict]]:
    """
    估值评分（满分 20）
    - PE <= 30: +8
    - PB <= 5: +5
    - PE 低于历史中位: +5
    - 股息率较高: +2
    """
    score = 0
    details = []

    # PE/PB 降级取值：优先用 DailyPrice（腾讯 TTM PE），否则从年报 EPS 计算
    pe = price.pe
    if pe is None and financial.eps and financial.eps > 0 and price.close:
        # 用年报 EPS 计算（已经是年度数据）
        pe = round(price.close / financial.eps, 2)
    # 负 PE 表示亏损，设为 None 不参与评分
    if pe is not None and pe <= 0:
        pe = None

    pb = price.pb
    if pb is None and financial.book_value_per_share and financial.book_value_per_share > 0 and price.close:
        pb = round(price.close / financial.book_value_per_share, 2)
    if pb is not None and pb <= 0:
        pb = None

    # PE 评分
    if pe is not None:
        if pe <= 15:
            score += 8
            details.append({"item": "PE", "value": f"{pe:.1f}", "score": 8, "max": 8, "status": "低估值"})
        elif pe <= 30:
            score += 6
            details.append({"item": "PE", "value": f"{pe:.1f}", "score": 6, "max": 8, "status": "合理"})
        elif pe <= 50:
            score += 3
            details.append({"item": "PE", "value": f"{pe:.1f}", "score": 3, "max": 8, "status": "偏高"})
        else:
            details.append({"item": "PE", "value": f"{pe:.1f}", "score": 0, "max": 8, "status": "高估值"})
    else:
        details.append({"item": "PE", "value": "N/A", "score": 0, "max": 8, "status": "无数据"})

    # PB 评分
    if pb is not None:
        if pb <= 2:
            score += 5
            details.append({"item": "PB", "value": f"{pb:.1f}", "score": 5, "max": 5, "status": "低估值"})
        elif pb <= 5:
            score += 3
            details.append({"item": "PB", "value": f"{pb:.1f}", "score": 3, "max": 5, "status": "合理"})
        elif pb <= 10:
            score += 1
            details.append({"item": "PB", "value": f"{pb:.1f}", "score": 1, "max": 5, "status": "偏高"})
        else:
            details.append({"item": "PB", "value": f"{pb:.1f}", "score": 0, "max": 5, "status": "高估值"})
    else:
        details.append({"item": "PB", "value": "N/A", "score": 0, "max": 5, "status": "无数据"})

    # PEG 估值（PE / 净利润增长率，越低越好）
    if pe is not None and financial.net_profit_yoy is not None and financial.net_profit_yoy > 0:
        peg = pe / financial.net_profit_yoy
        if peg < 0.5:
            score += 5
            details.append({"item": "PEG", "value": f"{peg:.2f}", "score": 5, "max": 5, "status": "极低估"})
        elif peg < 1.0:
            score += 4
            details.append({"item": "PEG", "value": f"{peg:.2f}", "score": 4, "max": 5, "status": "低估"})
        elif peg < 1.5:
            score += 2
            details.append({"item": "PEG", "value": f"{peg:.2f}", "score": 2, "max": 5, "status": "合理"})
        else:
            details.append({"item": "PEG", "value": f"{peg:.2f}", "score": 0, "max": 5, "status": "偏贵"})
    else:
        details.append({"item": "PEG", "value": "N/A", "score": 0, "max": 5, "status": "无数据"})

    # 股息率评分
    if price.dividend_yield is not None:
        if price.dividend_yield > 3:
            score += 2
            details.append({"item": "股息率", "value": f"{price.dividend_yield:.1f}%", "score": 2, "max": 2, "status": "高股息"})
        elif price.dividend_yield > 1:
            score += 1
            details.append({"item": "股息率", "value": f"{price.dividend_yield:.1f}%", "score": 1, "max": 2, "status": "中等"})
        else:
            details.append({"item": "股息率", "value": f"{price.dividend_yield:.1f}%", "score": 0, "max": 2, "status": "低股息"})
    else:
        details.append({"item": "股息率", "value": "N/A", "score": 0, "max": 2, "status": "无数据"})

    return score, details


def calculate_growth_score(financial: FinancialMetric, financial_history: list = None) -> tuple[float, list[dict]]:
    """
    成长评分（满分 20）
    - 营收同比增长 > 10%: +8
    - 净利润同比增长 > 10%: +8
    - 近3年复合增长（CAGR）为正: +4
    """
    score = 0
    details = []

    # 营收增长评分
    if financial.revenue_yoy is not None:
        if financial.revenue_yoy > 20:
            score += 8
            details.append({"item": "营收增长", "value": f"{financial.revenue_yoy:.1f}%", "score": 8, "max": 8, "status": "高速增长"})
        elif financial.revenue_yoy > 10:
            score += 6
            details.append({"item": "营收增长", "value": f"{financial.revenue_yoy:.1f}%", "score": 6, "max": 8, "status": "较快增长"})
        elif financial.revenue_yoy > 0:
            score += 3
            details.append({"item": "营收增长", "value": f"{financial.revenue_yoy:.1f}%", "score": 3, "max": 8, "status": "温和增长"})
        else:
            details.append({"item": "营收增长", "value": f"{financial.revenue_yoy:.1f}%", "score": 0, "max": 8, "status": "下滑"})
    else:
        details.append({"item": "营收增长", "value": "N/A", "score": 0, "max": 8, "status": "无数据"})

    # 净利润增长评分
    if financial.net_profit_yoy is not None:
        if financial.net_profit_yoy > 20:
            score += 8
            details.append({"item": "利润增长", "value": f"{financial.net_profit_yoy:.1f}%", "score": 8, "max": 8, "status": "高速增长"})
        elif financial.net_profit_yoy > 10:
            score += 6
            details.append({"item": "利润增长", "value": f"{financial.net_profit_yoy:.1f}%", "score": 6, "max": 8, "status": "较快增长"})
        elif financial.net_profit_yoy > 0:
            score += 3
            details.append({"item": "利润增长", "value": f"{financial.net_profit_yoy:.1f}%", "score": 3, "max": 8, "status": "温和增长"})
        else:
            details.append({"item": "利润增长", "value": f"{financial.net_profit_yoy:.1f}%", "score": 0, "max": 8, "status": "下滑"})
    else:
        details.append({"item": "利润增长", "value": "N/A", "score": 0, "max": 8, "status": "无数据"})

    # 复合增长率（CAGR）：用多期财务数据计算净利润的年复合增长率
    cagr = None
    if financial_history and len(financial_history) >= 2:
        # 按报告期排序（旧→新）
        sorted_hist = sorted(financial_history, key=lambda f: f.report_period)
        oldest = sorted_hist[0]
        newest = sorted_hist[-1]
        if oldest.net_profit and newest.net_profit and oldest.net_profit > 0 and newest.net_profit > 0:
            # 计算年数差（支持 "2024-12-31" 和 "2024Q4" 两种格式）
            try:
                from datetime import datetime as _dt
                def _parse_period(p):
                    s = str(p)
                    try:
                        return _dt.strptime(s[:10], "%Y-%m-%d")
                    except ValueError:
                        # 处理 "2024Q4" 格式
                        if "Q" in s:
                            year = int(s[:4])
                            quarter = int(s[5])
                            month = quarter * 3
                            return _dt(year, month, 28)
                        raise

                d1 = _parse_period(oldest.report_period)
                d2 = _parse_period(newest.report_period)
                n_years = max((d2 - d1).days / 365, 0.5)
                if n_years >= 0.5:
                    cagr = (newest.net_profit / oldest.net_profit) ** (1 / n_years) - 1
            except (ValueError, TypeError):
                pass

    if cagr is not None:
        cagr_pct = cagr * 100
        if cagr_pct > 15:
            score += 4
            details.append({"item": "复合增长(CAGR)", "value": f"{cagr_pct:.1f}%", "score": 4, "max": 4, "status": "高增长"})
        elif cagr_pct > 5:
            score += 3
            details.append({"item": "复合增长(CAGR)", "value": f"{cagr_pct:.1f}%", "score": 3, "max": 4, "status": "稳增长"})
        elif cagr_pct > 0:
            score += 2
            details.append({"item": "复合增长(CAGR)", "value": f"{cagr_pct:.1f}%", "score": 2, "max": 4, "status": "微增长"})
        else:
            details.append({"item": "复合增长(CAGR)", "value": f"{cagr_pct:.1f}%", "score": 0, "max": 4, "status": "负增长"})
    else:
        # 降级：用 ROE > 0 近似
        if financial.roe is not None and financial.roe > 0:
            score += 2
            details.append({"item": "复合增长(ROE降级)", "value": f"ROE {financial.roe:.1f}%", "score": 2, "max": 4, "status": "正向"})
        else:
            details.append({"item": "复合增长", "value": "N/A", "score": 0, "max": 4, "status": "无数据"})

    return score, details


def calculate_trend_score(price: DailyPrice, tech: Optional[TechnicalIndicator]) -> tuple[float, list[dict]]:
    """
    趋势评分（满分 20）
    - 收盘价 > MA60: +6
    - MA60 向上: +6
    - MACD 非空头: +4
    - 成交量温和放大: +4
    """
    score = 0
    details = []

    if tech is None:
        details.append({"item": "趋势数据", "value": "无技术指标", "score": 0, "max": 20, "status": "无数据"})
        return score, details

    # 收盘价 > MA60
    if tech.ma60 is not None and price.close is not None:
        if price.close > tech.ma60:
            score += 6
            details.append({"item": "价格>MA60", "value": f"收盘{price.close:.2f} > MA60{tech.ma60:.2f}", "score": 6, "max": 6, "status": "多头"})
        else:
            details.append({"item": "价格>MA60", "value": f"收盘{price.close:.2f} < MA60{tech.ma60:.2f}", "score": 0, "max": 6, "status": "空头"})

    # MA60 向上（MA60 > MA120，或 MA20 > MA60 作为备选）
    if tech.ma60 is not None and tech.ma120 is not None:
        if tech.ma60 > tech.ma120:
            score += 6
            details.append({"item": "MA60方向", "value": "MA60 > MA120 上行", "score": 6, "max": 6, "status": "上行"})
        else:
            details.append({"item": "MA60方向", "value": "MA60 < MA120 下行", "score": 0, "max": 6, "status": "下行"})
    elif tech.ma20 is not None and tech.ma60 is not None:
        if tech.ma20 > tech.ma60:
            score += 4
            details.append({"item": "MA方向", "value": "MA20 > MA60 上行", "score": 4, "max": 6, "status": "上行"})
        else:
            details.append({"item": "MA方向", "value": "MA20 < MA60 下行", "score": 0, "max": 6, "status": "下行"})

    # MACD 非空头
    if tech.macd is not None and tech.macd_signal is not None:
        if tech.macd > tech.macd_signal:
            score += 4
            details.append({"item": "MACD", "value": "多头排列", "score": 4, "max": 4, "status": "多头"})
        elif tech.macd_hist is not None and tech.macd_hist > 0:
            score += 2
            details.append({"item": "MACD", "value": "柱状图为正", "score": 2, "max": 4, "status": "偏多"})
        else:
            details.append({"item": "MACD", "value": "空头排列", "score": 0, "max": 4, "status": "空头"})

    # 成交量温和放大
    if tech.volume_ma5 is not None and tech.volume_ma20 is not None:
        ratio = tech.volume_ma5 / tech.volume_ma20 if tech.volume_ma20 > 0 else 0
        if 1.1 <= ratio <= 2.0:
            score += 4
            details.append({"item": "成交量", "value": f"5日/20日={ratio:.2f} 温和放大", "score": 4, "max": 4, "status": "温和放大"})
        elif ratio > 2.0:
            score += 2
            details.append({"item": "成交量", "value": f"5日/20日={ratio:.2f} 放量过大", "score": 2, "max": 4, "status": "放量过大"})
        else:
            details.append({"item": "成交量", "value": f"5日/20日={ratio:.2f} 缩量", "score": 0, "max": 4, "status": "缩量"})

    return score, details


def calculate_risk_score(financial: FinancialMetric, price: DailyPrice, price_history: list = None) -> tuple[float, list[dict]]:
    """
    风险评分（满分 10，分数越高风险越低）
    - 最大回撤可控: +4
    - 无重大业绩下滑: +3
    - 无异常高负债/现金流恶化: +3
    """
    score = 0
    details = []

    # 最大回撤计算
    max_drawdown = None
    if price_history and len(price_history) >= 20:
        closes = [p.close for p in price_history if p.close and p.close > 0]
        if len(closes) >= 20:
            peak = closes[0]
            max_dd = 0
            for c in closes:
                if c > peak:
                    peak = c
                dd = (peak - c) / peak
                if dd > max_dd:
                    max_dd = dd
            max_drawdown = max_dd

    if max_drawdown is not None:
        dd_pct = max_drawdown * 100
        if dd_pct < 15:
            score += 4
            details.append({"item": "最大回撤", "value": f"{dd_pct:.1f}%", "score": 4, "max": 4, "status": "可控"})
        elif dd_pct < 30:
            score += 2
            details.append({"item": "最大回撤", "value": f"{dd_pct:.1f}%", "score": 2, "max": 4, "status": "偏高"})
        else:
            details.append({"item": "最大回撤", "value": f"{dd_pct:.1f}%", "score": 0, "max": 4, "status": "过高"})
    else:
        # 无价格历史时降级用 PE 估值风险
        pe = price.pe
        if pe is None and financial.eps and financial.eps > 0 and price.close:
            pe = round(price.close / financial.eps, 2)
        if pe is not None and pe > 0:
            if pe < 50:
                score += 4
                details.append({"item": "估值风险(降级)", "value": f"PE {pe:.1f} 可控", "score": 4, "max": 4, "status": "可控"})
            elif pe < 80:
                score += 2
                details.append({"item": "估值风险(降级)", "value": f"PE {pe:.1f} 偏高", "score": 2, "max": 4, "status": "偏高"})
            else:
                details.append({"item": "估值风险(降级)", "value": f"PE {pe:.1f} 过高", "score": 0, "max": 4, "status": "过高"})
        else:
            details.append({"item": "回撤/估值", "value": "N/A", "score": 0, "max": 4, "status": "无数据"})

    # 业绩稳定性
    if financial.net_profit_yoy is not None:
        if financial.net_profit_yoy > -10:
            score += 3
            details.append({"item": "业绩稳定性", "value": f"净利润增长{financial.net_profit_yoy:.1f}%", "score": 3, "max": 3, "status": "稳定"})
        else:
            details.append({"item": "业绩稳定性", "value": f"净利润下滑{financial.net_profit_yoy:.1f}%", "score": 0, "max": 3, "status": "下滑"})

    # 负债与现金流（任一可用即评分）
    if financial.debt_ratio is not None and financial.operating_cashflow is not None:
        if financial.debt_ratio < 70 and financial.operating_cashflow > 0:
            score += 3
            details.append({"item": "负债/现金流", "value": "负债合理，现金流正向", "score": 3, "max": 3, "status": "健康"})
        elif financial.debt_ratio < 80:
            score += 1
            details.append({"item": "负债/现金流", "value": "负债偏高或现金流弱", "score": 1, "max": 3, "status": "关注"})
        else:
            details.append({"item": "负债/现金流", "value": "负债过高或现金流恶化", "score": 0, "max": 3, "status": "风险"})
    elif financial.debt_ratio is not None:
        # 只有负债率，没有现金流数据
        if financial.debt_ratio < 60:
            score += 2
            details.append({"item": "负债率(降级)", "value": f"{financial.debt_ratio:.1f}%", "score": 2, "max": 3, "status": "健康"})
        elif financial.debt_ratio < 80:
            score += 1
            details.append({"item": "负债率(降级)", "value": f"{financial.debt_ratio:.1f}%", "score": 1, "max": 3, "status": "偏高"})
        else:
            details.append({"item": "负债率(降级)", "value": f"{financial.debt_ratio:.1f}%", "score": 0, "max": 3, "status": "过高"})
    elif financial.operating_cashflow is not None:
        # 只有现金流，没有负债率数据
        if financial.operating_cashflow > 0:
            score += 2
            details.append({"item": "现金流(降级)", "value": "正向", "score": 2, "max": 3, "status": "健康"})
        else:
            details.append({"item": "现金流(降级)", "value": "负向", "score": 0, "max": 3, "status": "风险"})
    else:
        details.append({"item": "负债/现金流", "value": "N/A", "score": 0, "max": 3, "status": "无数据"})

    return score, details


def get_rating(total_score: float) -> str:
    """根据总分返回评级"""
    if total_score >= 85:
        return "BUY"
    elif total_score >= 75:
        return "ADD"
    elif total_score >= 65:
        return "WATCH"
    elif total_score >= 50:
        return "REDUCE"
    else:
        return "SELL"


def score_stock(
    db: Session,
    stock_id: int,
    score_date: date,
) -> Optional[StockScore]:
    """
    对单只股票进行评分，结果写入 stock_scores 表
    """
    stock = db.query(Stock).filter(Stock.id == stock_id).first()
    if not stock:
        return None

    # 获取最新行情
    price = (
        db.query(DailyPrice)
        .filter(DailyPrice.stock_id == stock_id)
        .order_by(DailyPrice.trade_date.desc())
        .first()
    )
    if not price:
        return None

    # 获取最新财务数据（优先年报，因为季报 ROE 等指标未年化）
    financial = (
        db.query(FinancialMetric)
        .filter(FinancialMetric.stock_id == stock_id)
        .filter(FinancialMetric.report_period.like("%年报%"))
        .order_by(FinancialMetric.report_period.desc())
        .first()
    )
    if not financial:
        # 如果没有年报，用最新一期
        financial = (
            db.query(FinancialMetric)
            .filter(FinancialMetric.stock_id == stock_id)
            .order_by(FinancialMetric.report_period.desc())
            .first()
        )
    if not financial:
        return None

    # 获取多期财务历史（用于 CAGR 计算）
    financial_history = (
        db.query(FinancialMetric)
        .filter(FinancialMetric.stock_id == stock_id)
        .order_by(FinancialMetric.report_period.desc())
        .limit(8)
        .all()
    )

    # 获取最新技术指标
    tech = (
        db.query(TechnicalIndicator)
        .filter(TechnicalIndicator.stock_id == stock_id)
        .order_by(TechnicalIndicator.trade_date.desc())
        .first()
    )

    # 获取近 90 天价格历史（用于计算最大回撤）
    price_history = (
        db.query(DailyPrice)
        .filter(DailyPrice.stock_id == stock_id)
        .order_by(DailyPrice.trade_date.desc())
        .limit(90)
        .all()
    )
    price_history = list(reversed(price_history))  # 按日期正序

    # 计算各项评分
    quality_score, quality_details = calculate_quality_score(financial, stock.industry or "")
    valuation_score, valuation_details = calculate_valuation_score(price, financial)
    growth_score, growth_details = calculate_growth_score(financial, financial_history)

    # 财务数据过期检查：超过 6 个月的数据扣分
    staleness_penalty = 0
    try:
        from datetime import datetime as _dt
        period_str = str(financial.report_period)
        if "Q" in period_str:
            year = int(period_str[:4])
            quarter = int(period_str[5])
            report_date = _dt(year, quarter * 3, 28)
        else:
            report_date = _dt.strptime(period_str[:10], "%Y-%m-%d")
        age_days = (score_date - report_date.date()).days
        if age_days > 365:
            staleness_penalty = -5
        elif age_days > 180:
            staleness_penalty = -2
    except (ValueError, TypeError):
        pass
    trend_score, trend_details = calculate_trend_score(price, tech)
    risk_score, risk_details = calculate_risk_score(financial, price, price_history)

    total_score = quality_score + valuation_score + growth_score + trend_score + risk_score + staleness_penalty
    rating = get_rating(total_score)

    # 构建评分摘要
    all_details = quality_details + valuation_details + growth_details + trend_details + risk_details
    strengths = [d["item"] for d in all_details if d["score"] >= d["max"] * 0.7]
    weaknesses = [d["item"] for d in all_details if d["score"] <= d["max"] * 0.3 and d["max"] > 0]
    reason_summary = f"优势: {', '.join(strengths[:3])}" if strengths else ""
    if weaknesses:
        reason_summary += f" | 风险: {', '.join(weaknesses[:3])}"

    # 更新或创建评分记录
    existing = (
        db.query(StockScore)
        .filter(StockScore.stock_id == stock_id, StockScore.score_date == score_date)
        .first()
    )
    if existing:
        existing.total_score = total_score
        existing.quality_score = quality_score
        existing.valuation_score = valuation_score
        existing.growth_score = growth_score
        existing.trend_score = trend_score
        existing.risk_score = risk_score
        existing.rating = rating
        existing.reason_summary = reason_summary
        score = existing
    else:
        score = StockScore(
            stock_id=stock_id,
            score_date=score_date,
            total_score=total_score,
            quality_score=quality_score,
            valuation_score=valuation_score,
            growth_score=growth_score,
            trend_score=trend_score,
            risk_score=risk_score,
            rating=rating,
            reason_summary=reason_summary,
        )
        db.add(score)

    db.commit()
    db.refresh(score)
    return score


def score_all_stocks(db: Session, score_date: date) -> list[StockScore]:
    """对所有活跃股票进行评分"""
    stocks = db.query(Stock).filter(Stock.status == "ACTIVE").all()
    results = []
    for stock in stocks:
        s = score_stock(db, stock.id, score_date)
        if s:
            results.append(s)
    return results
