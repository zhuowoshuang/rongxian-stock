"""AI 分析 API"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.db.session import get_db
from app.models.stock import Stock
from app.models.daily_price import DailyPrice
from app.models.stock_score import StockScore
from app.models.trade_signal import TradeSignal
from app.api.auth import get_current_user

router = APIRouter(prefix="/api/ai", tags=["AI 分析"])


class ChatRequest(BaseModel):
    prompt: str
    system_prompt: Optional[str] = ""


@router.post("/chat")
async def ai_chat(req: ChatRequest, user=Depends(get_current_user)):
    """通用 AI 对话接口"""
    from app.services.llm_service import call_llm, SYSTEM_PROMPT_STOCK_ANALYST

    system = req.system_prompt or SYSTEM_PROMPT_STOCK_ANALYST
    result = await call_llm(req.prompt, system_prompt=system)
    return {"response": result}


@router.get("/stock-analysis/{symbol}")
async def ai_stock_analysis(symbol: str, db: Session = Depends(get_db), user=Depends(get_current_user)):
    """AI 股票深度分析"""
    from app.services.llm_service import call_llm, SYSTEM_PROMPT_STOCK_ANALYST, PROMPT_STOCK_ANALYSIS

    stock = db.query(Stock).filter(Stock.symbol == symbol).first()
    if not stock:
        raise HTTPException(status_code=404, detail=f"股票 {symbol} 不存在")

    # 获取最新价格
    latest_price = db.query(DailyPrice).filter(
        DailyPrice.stock_id == stock.id
    ).order_by(DailyPrice.trade_date.desc()).first()

    # 获取评分
    score = db.query(StockScore).filter(
        StockScore.stock_id == stock.id
    ).order_by(StockScore.score_date.desc()).first()

    # 获取信号
    signal = db.query(TradeSignal).filter(
        TradeSignal.stock_id == stock.id
    ).order_by(TradeSignal.signal_date.desc()).first()

    # 构建提示词
    prompt = PROMPT_STOCK_ANALYSIS.format(
        symbol=stock.symbol,
        name=stock.name,
        industry=stock.industry or "未知",
        market=stock.market,
        close=f"{latest_price.close:.2f}" if latest_price else "N/A",
        pe=f"{latest_price.pe:.1f}" if latest_price and latest_price.pe else "N/A",
        pb=f"{latest_price.pb:.1f}" if latest_price and latest_price.pb else "N/A",
        market_cap=f"{latest_price.market_cap/1e8:.0f}亿" if latest_price and latest_price.market_cap else "N/A",
        total_score=f"{score.total_score:.0f}" if score else "N/A",
        quality_score=f"{score.quality_score:.0f}" if score else "N/A",
        valuation_score=f"{score.valuation_score:.0f}" if score else "N/A",
        growth_score=f"{score.growth_score:.0f}" if score else "N/A",
        trend_score=f"{score.trend_score:.0f}" if score else "N/A",
        risk_score=f"{score.risk_score:.0f}" if score else "N/A",
        rating=score.rating if score else "N/A",
    )

    result = await call_llm(prompt, system_prompt=SYSTEM_PROMPT_STOCK_ANALYST, max_tokens=3000)
    return {
        "symbol": symbol,
        "name": stock.name,
        "analysis": result,
    }


@router.get("/market-analysis")
async def ai_market_analysis(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """AI 市场综合分析"""
    from app.services.llm_service import call_llm, SYSTEM_PROMPT_STOCK_ANALYST, PROMPT_MARKET_ANALYSIS
    from datetime import date

    today = date.today()

    # 获取市场数据
    from app.models.daily_price import DailyPrice
    stocks = db.query(Stock).filter(Stock.status == "ACTIVE").limit(20).all()
    market_lines = []
    for s in stocks:
        price = db.query(DailyPrice).filter(DailyPrice.stock_id == s.id).order_by(DailyPrice.trade_date.desc()).first()
        if price:
            change_pct = ((price.close - price.pre_close) / price.pre_close * 100) if price.pre_close else 0
            market_lines.append(f"- {s.symbol} {s.name}: {price.close:.2f} ({change_pct:+.2f}%)")
    market_data = "\n".join(market_lines) if market_lines else "暂无市场数据"

    # 获取信号分布
    signals = db.query(TradeSignal).filter(TradeSignal.signal_date == today).all()
    dist = {"BUY": 0, "ADD": 0, "WATCH": 0, "REDUCE": 0, "SELL": 0}
    for s in signals:
        if s.signal_type in dist:
            dist[s.signal_type] += 1
    signal_distribution = "\n".join([f"- {k}: {v}个" for k, v in dist.items()])

    prompt = PROMPT_MARKET_ANALYSIS.format(
        market_data=market_data,
        signal_distribution=signal_distribution,
    )

    result = await call_llm(prompt, system_prompt=SYSTEM_PROMPT_STOCK_ANALYST, max_tokens=3000)
    return {"analysis": result}


@router.get("/risk-alert")
async def ai_risk_alert(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """AI 风险评估"""
    from app.services.llm_service import call_llm, SYSTEM_PROMPT_STOCK_ANALYST, PROMPT_RISK_ALERT
    from app.models.portfolio import Portfolio, PortfolioPosition

    # 获取持仓数据
    portfolio = db.query(Portfolio).first()
    if not portfolio:
        return {"analysis": "暂无持仓数据，无法进行风险评估。"}

    positions = db.query(PortfolioPosition).filter(
        PortfolioPosition.portfolio_id == portfolio.id
    ).all()

    pos_lines = []
    for pos in positions:
        stock = db.query(Stock).filter(Stock.id == pos.stock_id).first()
        if stock:
            ret = pos.unrealized_return or 0
            pos_lines.append(f"- {stock.symbol} {stock.name}: 仓位{pos.position_ratio:.1f}% | 成本{pos.cost_price:.2f} | 现价{pos.current_price:.2f} | 收益{ret:+.2f}%")
    portfolio_data = "\n".join(pos_lines) if pos_lines else "暂无持仓"

    # 市场环境
    market_context = f"组合名称: {portfolio.name}\n目标仓位: {portfolio.target_position}%\n现金比例: {portfolio.cash_ratio}%"

    prompt = PROMPT_RISK_ALERT.format(
        portfolio_data=portfolio_data,
        market_context=market_context,
    )

    result = await call_llm(prompt, system_prompt=SYSTEM_PROMPT_STOCK_ANALYST, max_tokens=2000)
    return {"analysis": result}
