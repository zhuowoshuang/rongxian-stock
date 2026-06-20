"""股票相关 API"""
from datetime import date
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.stock import Stock
from app.models.daily_price import DailyPrice
from app.models.financial_metric import FinancialMetric
from app.models.technical_indicator import TechnicalIndicator
from app.api.auth import get_current_admin, get_current_user
from app.models.stock_score import StockScore
from app.models.trade_signal import TradeSignal
from app.models.report import Report
from app.models.research_report import ResearchReport
from app.core.constants import ReportType

router = APIRouter(prefix="/api/stocks", tags=["股票"])


@router.get("/search")
def search_stocks(
    keyword: str = Query(..., description="股票代码/名称/关键词"),
    market: str = Query(None, description="市场: A_SHARE / HK"),
    db: Session = Depends(get_db),
    user=Depends(get_current_user),
):
    """搜索股票"""
    query = db.query(Stock).filter(Stock.status == "ACTIVE")
    if market:
        query = query.filter(Stock.market == market)
    query = query.filter(
        (Stock.symbol.ilike(f"%{keyword}%")) | (Stock.name.ilike(f"%{keyword}%"))
    )
    stocks = query.limit(20).all()
    return [
        {
            "id": s.id,
            "symbol": s.symbol,
            "name": s.name,
            "market": s.market,
            "exchange": s.exchange,
            "industry": s.industry,
        }
        for s in stocks
    ]


@router.post("/sync")
def sync_stocks(
    market: str = Query("ALL", description="同步市场: A_SHARE / HK / ALL"),
    db: Session = Depends(get_db),
    user=Depends(get_current_admin),
):
    """从东方财富同步全部股票列表到数据库"""
    from app.services.stock_sync import sync_stock_list
    result = sync_stock_list(db, market=market)
    return {
        "status": "ok",
        "message": f"同步完成: 新增 {result['added']}，更新 {result['updated']}，共 {result['total']}",
        **result,
    }


@router.get("/count")
def stock_count(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """获取数据库中的股票数量"""
    total = db.query(Stock).filter(Stock.status == "ACTIVE").count()
    a_share = db.query(Stock).filter(Stock.status == "ACTIVE", Stock.market == "A_SHARE").count()
    hk = db.query(Stock).filter(Stock.status == "ACTIVE", Stock.market == "HK").count()
    return {"total": total, "a_share": a_share, "hk": hk}


@router.get("/{symbol}")
def get_stock_detail(symbol: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """获取股票详情：基本信息、行情、财务、评分、信号、报告"""
    from app.services.stock_detail import get_stock_detail as _get_detail
    result = _get_detail(db, symbol)
    if not result:
        raise HTTPException(status_code=404, detail="Stock not found")
    return result
