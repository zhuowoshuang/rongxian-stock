"""
仪表盘数据聚合服务
"""
import time
from datetime import date
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.models.stock import Stock
from app.models.stock_score import StockScore
from app.models.trade_signal import TradeSignal
from app.models.daily_price import DailyPrice
from app.models.portfolio import Portfolio, PortfolioPosition
from app.data_providers import get_provider
from app.services.price_helper import get_latest_prices

# Dashboard 响应缓存（避免每次都重新计算）
_dashboard_cache: dict = {}
_dashboard_cache_time: float = 0
_dashboard_cache_ttl: int = 120  # 缓存 120 秒


def get_dashboard_data(db: Session, today: date) -> dict:
    """聚合仪表盘所需的全部数据（带缓存）"""
    global _dashboard_cache, _dashboard_cache_time

    cache_key = str(today)
    now = time.time()
    if cache_key in _dashboard_cache and now - _dashboard_cache_time < _dashboard_cache_ttl:
        return _dashboard_cache[cache_key]

    provider = get_provider()

    # 1. 市场概览 - 使用真实东方财富数据
    try:
        market_a = provider.fetch_market_index("A_SHARE")
    except Exception as e:
        market_a = [
            {"name": "上证指数", "code": "000001.SH", "current": 0, "change": 0, "change_pct": 0},
            {"name": "深证成指", "code": "399001.SZ", "current": 0, "change": 0, "change_pct": 0},
            {"name": "创业板指", "code": "399006.SZ", "current": 0, "change": 0, "change_pct": 0},
        ]
    try:
        market_hk = provider.fetch_market_index("HK")
    except Exception as e:
        market_hk = [
            {"name": "恒生指数", "code": "HSI", "current": 0, "change": 0, "change_pct": 0},
            {"name": "恒生科技", "code": "HSTECH", "current": 0, "change": 0, "change_pct": 0},
        ]

    # 2. 策略总结
    signals = db.query(TradeSignal).filter(TradeSignal.signal_date == today).all()
    dist = {"BUY": 0, "ADD": 0, "WATCH": 0, "REDUCE": 0, "SELL": 0}
    for s in signals:
        if s.signal_type in dist:
            dist[s.signal_type] += 1

    buy_add = dist["BUY"] + dist["ADD"]
    reduce_sell = dist["REDUCE"] + dist["SELL"]
    if buy_add > reduce_sell * 2:
        market_status = "偏多"
        suggested_pos = "70-80%"
    elif buy_add > reduce_sell:
        market_status = "中性偏多"
        suggested_pos = "50-70%"
    elif reduce_sell > buy_add * 2:
        market_status = "偏空"
        suggested_pos = "20-30%"
    else:
        market_status = "中性"
        suggested_pos = "40-60%"

    strategy_summary = {
        "market_status": market_status,
        "suggested_position": suggested_pos,
        "core_strategy": "基本面中长期选股 + 趋势确认入场",
        "risk_warning": "关注宏观经济变化和行业政策风险，控制单只仓位不超过10%",
    }

    # 3. Top 信号
    top_signals = (
        db.query(TradeSignal, Stock)
        .join(Stock, TradeSignal.stock_id == Stock.id)
        .filter(TradeSignal.signal_date == today, TradeSignal.signal_type.in_(["BUY", "ADD"]))
        .order_by(TradeSignal.signal_strength.desc())
        .limit(10)
        .all()
    )
    # 批量获取最新价格（避免 N+1）
    signal_stock_ids = [stock.id for sig, stock in top_signals]
    signal_prices = get_latest_prices(db, signal_stock_ids)

    top_signal_list = []
    for sig, stock in top_signals:
        latest_price = signal_prices.get(stock.id)
        top_signal_list.append({
            "symbol": stock.symbol,
            "name": stock.name,
            "market": stock.market,
            "signal_type": sig.signal_type,
            "signal_strength": sig.signal_strength,
            "suggested_position": sig.suggested_position,
            "logic": sig.logic_json.get("reason", "") if sig.logic_json else "",
            "risk": sig.risk_json.get("items", []) if sig.risk_json else [],
            "latest_close": latest_price.close if latest_price else None,
            "change_pct": round((latest_price.close - latest_price.pre_close) / latest_price.pre_close * 100, 2) if latest_price and latest_price.pre_close and latest_price.pre_close != 0 else None,
        })

    # 4. 信号分布
    signal_distribution = dist

    # 5. 组合表现（从 NAV 历史计算真实指标）
    from app.services.portfolio import get_portfolio_summary, compute_portfolio_metrics
    from app.models.portfolio import Portfolio, PortfolioPosition, PortfolioNAV
    pf = get_portfolio_summary(db)

    # 从 NAV 历史获取真实指标
    metrics = compute_portfolio_metrics(db)

    # 获取最新净值
    portfolio = db.query(Portfolio).first()
    latest_nav = db.query(PortfolioNAV).filter(
        PortfolioNAV.portfolio_id == portfolio.id
    ).order_by(PortfolioNAV.nav_date.desc()).first() if portfolio else None

    total_assets = latest_nav.total_value if latest_nav else 1000000

    # 获取当月收益
    monthly_return = 0
    if metrics["monthly_returns"]:
        monthly_return = metrics["monthly_returns"][-1]["strategy_return"]

    portfolio_summary = {
        "monthly_return": monthly_return,
        "benchmark_return": metrics["monthly_returns"][-1]["benchmark_return"] if metrics["monthly_returns"] else 0,
        "excess_return": metrics["monthly_returns"][-1]["excess_return"] if metrics["monthly_returns"] else 0,
        "max_drawdown": metrics["max_drawdown"],
        "sharpe_ratio": metrics["sharpe"],
        "total_assets": round(total_assets, 2),
        "cash_ratio": pf["cash_ratio"] or 35.0,
        "position_count": pf["position_count"],
        "name": pf["name"],
    }

    # 6. 股票池
    scores = (
        db.query(StockScore, Stock)
        .join(Stock, StockScore.stock_id == Stock.id)
        .filter(StockScore.score_date == today)
        .all()
    )
    pools = {"quality": [], "undervalued": [], "trend": [], "risk": []}
    for sc, st in scores:
        item = {
            "symbol": st.symbol,
            "name": st.name,
            "market": st.market,
            "score": sc.total_score,
            "rating": sc.rating,
        }
        if sc.quality_score and sc.quality_score >= 22:
            pools["quality"].append(item)
        if sc.valuation_score and sc.valuation_score >= 15:
            pools["undervalued"].append(item)
        if sc.trend_score and sc.trend_score >= 15:
            pools["trend"].append(item)
        if sc.risk_score and sc.risk_score < 5:
            pools["risk"].append(item)

    # 7. 风险预警（从 REDUCE/SELL 信号中提取，这些才有真正的风险信息）
    risk_signals = (
        db.query(TradeSignal, Stock)
        .join(Stock, TradeSignal.stock_id == Stock.id)
        .filter(TradeSignal.signal_date == today, TradeSignal.signal_type.in_(["REDUCE", "SELL"]))
        .limit(10)
        .all()
    )
    risk_alerts = []
    for sig, stock in risk_signals:
        if sig.risk_json and sig.risk_json.get("items"):
            risk_alerts.append({
                "symbol": stock.symbol,
                "name": stock.name,
                "market": stock.market,
                "level": "high" if sig.signal_type == "SELL" else "medium",
                "message": "，".join(sig.risk_json["items"]),
            })

    result = {
        "market_summary": market_a + market_hk,
        "strategy_summary": strategy_summary,
        "top_signals": top_signal_list,
        "signal_distribution": signal_distribution,
        "portfolio_summary": portfolio_summary,
        "stock_pools": pools,
        "risk_alerts": risk_alerts,
    }

    # 更新缓存
    _dashboard_cache[cache_key] = result
    _dashboard_cache_time = time.time()
    return result
