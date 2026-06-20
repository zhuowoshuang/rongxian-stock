"""
组合数据源 - 路由各方法到最优数据源
行情: 腾讯 (快速, 无限流, 通过 EastMoneyProvider)
财务: Yahoo Finance (A股 + 港股) -> 东方财富 fallback
研报: 东方财富
指数: 腾讯 (通过 EastMoneyProvider)
股票列表: Sina + Tencent (在 stock_sync 模块中)
"""
import logging
from datetime import date
import pandas as pd

from app.data_providers.base import DataProviderBase
from app.data_providers.yahoo_provider import YahooFinanceProvider
from app.data_providers.eastmoney_provider import EastMoneyProvider

logger = logging.getLogger(__name__)


class CompositeProvider(DataProviderBase):
    """组合数据源 - 自动选择最优数据源"""

    def __init__(self):
        self.yahoo = YahooFinanceProvider()
        self.eastmoney = EastMoneyProvider()

    def fetch_stock_list(self, market: str) -> pd.DataFrame:
        return self.eastmoney.fetch_stock_list(market)

    def fetch_daily_prices(self, symbol: str, start_date: date, end_date: date) -> pd.DataFrame:
        return self.eastmoney.fetch_daily_prices(symbol, start_date, end_date)

    def fetch_financial_metrics(self, symbol: str) -> pd.DataFrame:
        df = self.yahoo.fetch_financial_metrics(symbol)
        if df.empty:
            logger.info(f"Yahoo financials empty for {symbol}, falling back to EastMoney")
            df = self.eastmoney.fetch_financial_metrics(symbol)
        return df

    def fetch_market_index(self, market: str) -> list:
        return self.eastmoney.fetch_market_index(market)

    def fetch_news(self, symbol: str, limit: int = 10) -> list:
        return self.yahoo.fetch_news(symbol, limit)

    def fetch_valuation(self, symbol: str) -> dict:
        val = self.yahoo.fetch_valuation(symbol)
        # Yahoo 返回的 dict 可能有 key 但值为 None，需要检查关键字段
        if not val or (val.get("pe") is None and val.get("pb") is None):
            logger.info(f"Yahoo valuation incomplete for {symbol} (pe={val.get('pe')}, pb={val.get('pb')}), merging with EastMoney")
            fallback = self.eastmoney.fetch_valuation(symbol)
            if fallback:
                # 用 EastMoney 的值填充 Yahoo 缺失的字段
                for k, v in fallback.items():
                    if val.get(k) is None and v is not None:
                        val[k] = v
                if not val:
                    val = fallback
        return val

    def fetch_reports(self, symbol: str = None, page: int = 1, page_size: int = 20) -> dict:
        return self.eastmoney.fetch_reports(symbol, page, page_size)
