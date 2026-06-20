"""股票池 API"""
from datetime import date
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.stock import Stock
from app.models.stock_score import StockScore
from app.models.user import User
from app.api.auth import get_current_user
from app.services.price_helper import get_latest_prices

router = APIRouter(prefix="/api/pools", tags=["股票池"])


@router.get("")
def get_stock_pool(
    type: str = Query("quality", description="池类型: quality/undervalued/trend/risk"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取股票池"""
    # 取最新评分日期
    from sqlalchemy import func
    latest = db.query(func.max(StockScore.score_date)).scalar()
    if not latest:
        return {"type": type, "items": []}

    query = (
        db.query(StockScore, Stock)
        .join(Stock, StockScore.stock_id == Stock.id)
        .filter(StockScore.score_date == latest, Stock.status == "ACTIVE")
    )

    if type == "quality":
        query = query.filter(StockScore.quality_score >= 22).order_by(StockScore.quality_score.desc())
    elif type == "undervalued":
        query = query.filter(StockScore.valuation_score >= 15).order_by(StockScore.valuation_score.desc())
    elif type == "trend":
        query = query.filter(StockScore.trend_score >= 15).order_by(StockScore.trend_score.desc())
    elif type == "risk":
        query = query.filter(StockScore.risk_score < 5).order_by(StockScore.risk_score.asc())
    else:
        query = query.order_by(StockScore.total_score.desc())

    results = query.all()

    # 批量获取最新价格（避免 N+1）
    stock_ids = [st.id for sc, st in results]
    latest_prices = get_latest_prices(db, stock_ids)

    items = []
    for sc, st in results:
        price = latest_prices.get(st.id)
        items.append({
            "symbol": st.symbol,
            "name": st.name,
            "market": st.market,
            "industry": st.industry,
            "total_score": sc.total_score,
            "quality_score": sc.quality_score,
            "valuation_score": sc.valuation_score,
            "growth_score": sc.growth_score,
            "trend_score": sc.trend_score,
            "risk_score": sc.risk_score,
            "rating": sc.rating,
            "reason": sc.reason_summary,
            "latest_close": price.close if price else None,
            "pe": price.pe if price else None,
            "pb": price.pb if price else None,
        })

    return {"type": type, "date": str(latest), "count": len(items), "items": items}
