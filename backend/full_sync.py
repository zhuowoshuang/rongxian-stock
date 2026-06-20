"""
全量数据同步脚本
分步处理全部 A 股：价格 → 财务 → 估值 → 技术指标 → 评分 → 信号
"""
import os
os.environ["MOCK_DATA"] = "false"

import time
import json
import urllib.request
from datetime import date, datetime, timedelta
from sqlalchemy import func

from app.db.session import SessionLocal
from app.models.stock import Stock
from app.models.daily_price import DailyPrice
from app.models.financial_metric import FinancialMetric
from app.models.technical_indicator import TechnicalIndicator
from app.models.stock_score import StockScore
from app.models.trade_signal import TradeSignal
from app.data_providers.eastmoney_provider import EastMoneyProvider


def fetch_sina(symbol, days=150):
    tc = f"sh{symbol}" if symbol.startswith(("6", "5")) else f"sz{symbol}"
    url = f"https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol={tc}&scale=240&ma=no&datalen={days}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read().decode("utf-8"))
    except:
        return []


def step1_prices(db, provider):
    """步骤1: 拉取全部 A 股价格数据"""
    stocks = db.query(Stock).filter(
        Stock.status == "ACTIVE",
        Stock.market == "A_SHARE",
        ~Stock.id.in_(db.query(DailyPrice.stock_id).distinct())
    ).all()
    print(f"[1/6] 拉取价格: {len(stocks)} 只待处理")

    ok, fail = 0, 0
    for i, stock in enumerate(stocks):
        if i % 100 == 0 and i > 0:
            print(f"  进度: {i}/{len(stocks)} 成功={ok} 失败={fail}")
            db.commit()

        klines = fetch_sina(stock.symbol, 150)
        if not klines:
            fail += 1
            continue

        prev = None
        for item in klines:
            try:
                td = datetime.strptime(item["day"][:10], "%Y-%m-%d").date()
            except:
                continue
            close = float(item["close"])
            db.add(DailyPrice(
                stock_id=stock.id, trade_date=td,
                open=float(item["open"]), high=float(item["high"]),
                low=float(item["low"]), close=close, pre_close=prev,
                volume=float(item["volume"]), turnover=0, turnover_rate=0,
            ))
            prev = close
        ok += 1
        time.sleep(0.15)

    db.commit()
    print(f"  完成: 成功={ok} 失败={fail}")
    return ok


def step2_financials(db, provider):
    """步骤2: 拉取财务数据"""
    stocks = db.query(Stock).filter(
        Stock.status == "ACTIVE",
        Stock.market == "A_SHARE",
        Stock.id.in_(db.query(DailyPrice.stock_id).distinct()),
        ~Stock.id.in_(db.query(FinancialMetric.stock_id).distinct())
    ).all()
    print(f"[2/6] 拉取财务: {len(stocks)} 只待处理")

    ok, fail = 0, 0
    for i, stock in enumerate(stocks):
        if i % 50 == 0 and i > 0:
            print(f"  进度: {i}/{len(stocks)} 成功={ok} 失败={fail}")
            db.commit()

        df = provider.fetch_financial_metrics(stock.symbol)
        if df.empty:
            fail += 1
            continue

        for _, row in df.iterrows():
            period = row.get("report_period", "")
            if not period:
                continue
            if db.query(FinancialMetric).filter(
                FinancialMetric.stock_id == stock.id,
                FinancialMetric.report_period == period
            ).first():
                continue
            db.add(FinancialMetric(
                stock_id=stock.id, report_period=period,
                revenue=row.get("revenue"), revenue_yoy=row.get("revenue_yoy"),
                net_profit=row.get("net_profit"), net_profit_yoy=row.get("net_profit_yoy"),
                gross_margin=row.get("gross_margin"), net_margin=row.get("net_margin"),
                roe=row.get("roe"), roa=row.get("roa"), debt_ratio=row.get("debt_ratio"),
                operating_cashflow=row.get("operating_cashflow"),
                free_cashflow=row.get("free_cashflow"),
                eps=row.get("eps"), book_value_per_share=row.get("book_value_per_share"),
            ))
        ok += 1
        time.sleep(0.3)

    db.commit()
    print(f"  完成: 成功={ok} 失败={fail}")
    return ok


def step3_valuations(db, provider):
    """步骤3: 回填估值"""
    stocks = db.query(Stock).filter(
        Stock.status == "ACTIVE",
        Stock.market == "A_SHARE",
        Stock.id.in_(db.query(DailyPrice.stock_id).distinct())
    ).all()
    print(f"[3/6] 回填估值: {len(stocks)} 只")

    ok = 0
    for i, stock in enumerate(stocks):
        if i % 100 == 0 and i > 0:
            print(f"  进度: {i}/{len(stocks)} 成功={ok}")
            db.commit()

        latest = db.query(DailyPrice).filter(
            DailyPrice.stock_id == stock.id
        ).order_by(DailyPrice.trade_date.desc()).first()

        if not latest or latest.pe is not None:
            ok += 1
            continue

        try:
            val = provider.fetch_valuation(stock.symbol)
            if val.get("pe") is not None:
                latest.pe = val["pe"]
            if val.get("pb") is not None:
                latest.pb = val["pb"]
            if val.get("market_cap") is not None:
                latest.market_cap = val["market_cap"]
            ok += 1
        except:
            pass
        time.sleep(0.1)

    db.commit()
    print(f"  完成: {ok} 只")
    return ok


def step4_technicals(db):
    """步骤4: 计算技术指标"""
    from app.seed import _compute_technicals
    stock_map = {s.symbol: s.id for s in db.query(Stock).filter(Stock.status == "ACTIVE").all()}
    print(f"[4/6] 计算技术指标: {len(stock_map)} 只")
    count = _compute_technicals(db, stock_map)
    print(f"  完成: {count} 个指标")
    return count


def step5_scoring(db):
    """步骤5: 评分"""
    from app.services.scoring import score_stock
    stocks = db.query(Stock).filter(
        Stock.status == "ACTIVE",
        Stock.id.in_(db.query(DailyPrice.stock_id).distinct()),
        Stock.id.in_(db.query(FinancialMetric.stock_id).distinct())
    ).all()
    print(f"[5/6] 评分: {len(stocks)} 只")

    ok = 0
    for stock in stocks:
        sc = score_stock(db, stock.id, date.today())
        if sc:
            ok += 1
    print(f"  完成: {ok} 只")
    return ok


def step6_signals(db):
    """步骤6: 生成信号"""
    from app.services.signal import generate_all_signals
    print("[6/6] 生成信号...")
    db.query(TradeSignal).delete()
    db.commit()
    signals = generate_all_signals(db, date.today())
    dist = {}
    for s in signals:
        dist[s.signal_type] = dist.get(s.signal_type, 0) + 1
    print(f"  完成: {len(signals)} 个")
    print(f"  BUY={dist.get('BUY',0)} ADD={dist.get('ADD',0)} WATCH={dist.get('WATCH',0)} REDUCE={dist.get('REDUCE',0)} SELL={dist.get('SELL',0)}")
    return len(signals)


def main():
    db = SessionLocal()
    provider = EastMoneyProvider()

    t0 = time.time()
    step1_prices(db, provider)
    step2_financials(db, provider)
    step3_valuations(db, provider)
    step4_technicals(db)
    step5_scoring(db)
    step6_signals(db)

    # 最终统计
    p = db.query(func.count(func.distinct(DailyPrice.stock_id))).scalar()
    f = db.query(func.count(func.distinct(FinancialMetric.stock_id))).scalar()
    t = db.query(func.count(func.distinct(TechnicalIndicator.stock_id))).scalar()
    s = db.query(func.count(func.distinct(StockScore.stock_id))).scalar()
    sig = db.query(TradeSignal).filter(TradeSignal.status == "ACTIVE").count()

    elapsed = time.time() - t0
    print(f"\n{'='*50}")
    print(f"全量同步完成! 耗时 {elapsed/60:.1f} 分钟")
    print(f"  价格: {p} 只")
    print(f"  财务: {f} 只")
    print(f"  技术: {t} 只")
    print(f"  评分: {s} 只")
    print(f"  信号: {sig} 个")
    print(f"{'='*50}")

    db.close()


if __name__ == "__main__":
    main()
