"""
股票详情服务 - 聚合单只股票的全部信息
"""
from typing import Optional
from sqlalchemy.orm import Session

from app.models.stock import Stock
from app.models.daily_price import DailyPrice
from app.models.financial_metric import FinancialMetric
from app.models.technical_indicator import TechnicalIndicator
from app.models.stock_score import StockScore
from app.models.trade_signal import TradeSignal
from app.models.research_report import ResearchReport


def get_stock_detail(db: Session, symbol: str) -> Optional[dict]:
    """获取股票详情：基本信息、行情、财务、评分、信号、报告
    Returns: 完整的股票详情 dict，如果股票不存在返回 None
    """
    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    if not stock:
        return None

    # 最新行情 + 历史行情（合并为一次查询）
    all_prices = (
        db.query(DailyPrice)
        .filter(DailyPrice.stock_id == stock.id)
        .order_by(DailyPrice.trade_date.desc())
        .limit(120)
        .all()
    )
    latest_price = all_prices[0] if all_prices else None

    # 财务指标
    financials = (
        db.query(FinancialMetric)
        .filter(FinancialMetric.stock_id == stock.id)
        .order_by(FinancialMetric.report_period.desc())
        .limit(8)
        .all()
    )

    # 技术指标
    tech = (
        db.query(TechnicalIndicator)
        .filter(TechnicalIndicator.stock_id == stock.id)
        .order_by(TechnicalIndicator.trade_date.desc())
        .first()
    )

    # 评分
    score = (
        db.query(StockScore)
        .filter(StockScore.stock_id == stock.id)
        .order_by(StockScore.score_date.desc())
        .first()
    )

    # 最新信号
    signal = (
        db.query(TradeSignal)
        .filter(TradeSignal.stock_id == stock.id)
        .order_by(TradeSignal.signal_date.desc())
        .first()
    )

    # 信号历史（最近 20 条）
    signal_history = (
        db.query(TradeSignal)
        .filter(TradeSignal.stock_id == stock.id)
        .order_by(TradeSignal.signal_date.desc())
        .limit(20)
        .all()
    )

    # 相关研报
    research_reports = (
        db.query(ResearchReport)
        .filter(ResearchReport.stock_code == symbol)
        .order_by(ResearchReport.publish_date.desc())
        .limit(10)
        .all()
    )

    return {
        "stock": {
            "id": stock.id,
            "symbol": stock.symbol,
            "name": stock.name,
            "market": stock.market,
            "exchange": stock.exchange,
            "industry": stock.industry,
            "sector": stock.sector,
        },
        "latest_price": {
            "trade_date": str(latest_price.trade_date),
            "close": latest_price.close,
            "open": latest_price.open,
            "high": latest_price.high,
            "low": latest_price.low,
            "volume": latest_price.volume,
            "turnover": latest_price.turnover,
            "pe": latest_price.pe,
            "pb": latest_price.pb,
            "market_cap": latest_price.market_cap,
            "dividend_yield": latest_price.dividend_yield,
        } if latest_price else None,
        "price_history": [
            {
                "date": str(p.trade_date),
                "open": p.open,
                "high": p.high,
                "low": p.low,
                "close": p.close,
                "volume": p.volume,
            }
            for p in reversed(all_prices)
        ],
        "financial_metrics": [
            {
                "period": f.report_period,
                "revenue": f.revenue,
                "revenue_yoy": f.revenue_yoy,
                "net_profit": f.net_profit,
                "net_profit_yoy": f.net_profit_yoy,
                "gross_margin": f.gross_margin,
                "roe": f.roe,
                "debt_ratio": f.debt_ratio,
                "eps": f.eps,
            }
            for f in financials
        ],
        "technical_indicators": {
            "ma20": tech.ma20,
            "ma60": tech.ma60,
            "ma120": tech.ma120,
            "macd": tech.macd,
            "macd_signal": tech.macd_signal,
            "rsi14": tech.rsi14,
        } if tech else None,
        "score": {
            "total": score.total_score,
            "quality": score.quality_score,
            "valuation": score.valuation_score,
            "growth": score.growth_score,
            "trend": score.trend_score,
            "risk": score.risk_score,
            "rating": score.rating,
            "reason": score.reason_summary,
            "date": str(score.score_date),
        } if score else None,
        "signal": {
            "type": signal.signal_type,
            "strength": signal.signal_strength,
            "position": signal.suggested_position,
            "entry_price": signal.entry_price,
            "target_price": signal.target_price,
            "stop_loss": signal.stop_loss_price,
            "holding_period": signal.holding_period,
            "logic": signal.logic_json,
            "risk": signal.risk_json,
            "date": str(signal.signal_date),
        } if signal else None,
        "signal_history": [
            {
                "date": str(s.signal_date),
                "type": s.signal_type,
                "strength": s.signal_strength,
                "status": s.status,
                "entry_price": s.entry_price,
                "target_price": s.target_price,
                "logic": s.logic_json.get("reason", "") if s.logic_json else "",
            }
            for s in signal_history
        ],
        "reports": [
            {
                "title": r.title,
                "org_name": r.org_name,
                "publish_date": str(r.publish_date) if r.publish_date else "",
                "rating": r.rating,
                "researcher": r.researcher,
                "url": r.url,
            }
            for r in research_reports
        ],
    }
