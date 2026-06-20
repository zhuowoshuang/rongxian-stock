"""回测中心 API"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.backtest import BacktestRequest
from app.services.backtest import run_backtest
from app.api.auth import get_current_analyst

router = APIRouter(prefix="/api/backtest", tags=["回测"])


@router.post("/run")
def run_backtest_api(req: BacktestRequest, db: Session = Depends(get_db), user=Depends(get_current_analyst)):
    """
    运行回测
    请求体：strategy, market, start_date, end_date, rebalance, initial_capital
    """
    result = run_backtest(
        db=db,
        strategy=req.strategy,
        market=req.market,
        start_date=req.start_date,
        end_date=req.end_date,
        rebalance=req.rebalance,
        initial_capital=req.initial_capital,
    )
    return result
