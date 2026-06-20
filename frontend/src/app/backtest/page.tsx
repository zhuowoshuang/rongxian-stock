"use client";

import { useState } from "react";
import { runBacktest } from "@/lib/api";
import type { BacktestResult } from "@/types";
import { formatPercent, getChangeColor } from "@/lib/utils";
import { useTranslation } from "@/lib/i18n";
import GlassCard from "@/components/ui/GlassCard";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, BarChart, Bar, Legend } from "recharts";

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload?.length) {
    return (
      <div className="bg-dark-card border border-white/10 rounded-lg px-3 py-2 shadow-xl backdrop-blur-xl">
        <p className="text-xs text-dark-muted mb-1">{label}</p>
        {payload.map((p: any, i: number) => (
          <p key={i} className="text-sm" style={{ color: p.color }}>{p.name}: <span className="font-mono font-bold">{typeof p.value === "number" ? p.value.toFixed(2) : p.value}</span></p>
        ))}
      </div>
    );
  }
  return null;
};

export default function BacktestPage() {
  const { t } = useTranslation();
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [params, setParams] = useState({
    strategy: "fundamental_medium_long",
    market: "A_SHARE",
    start_date: "2020-01-01",
    end_date: "2025-12-31",
    rebalance: "monthly",
    initial_capital: 1000000,
  });

  const handleRun = async () => {
    setLoading(true);
    try { const data = await runBacktest(params); setResult(data); } catch (e) { console.error(e); }
    setLoading(false);
  };

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      <h1 className="text-xl font-bold text-white flex items-center gap-2">
        <span className="w-1 h-6 bg-primary-500 rounded-full" />
        {t("backtest.title")}
      </h1>

      <GlassCard title={t("backtest.strategy")}>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
          <div>
            <label className="text-xs text-dark-muted">{t("backtest.strategy")}</label>
            <select value={params.strategy} onChange={(e) => setParams({ ...params, strategy: e.target.value })} className="w-full mt-1">
              <option value="fundamental_medium_long">{t("backtest.fundamental")}</option>
              <option value="value_investing">价值投资</option>
              <option value="growth_investing">成长投资</option>
              <option value="momentum">趋势动量</option>
              <option value="quality_first">质量优先</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-dark-muted">{t("backtest.market")}</label>
            <select value={params.market} onChange={(e) => setParams({ ...params, market: e.target.value })} className="w-full mt-1">
              <option value="A_SHARE">{t("market.aShare")}</option>
              <option value="HK">{t("market.hk")}</option>
            </select>
          </div>
          <div>
            <label className="text-xs text-dark-muted">{t("backtest.startDate")}</label>
            <input type="date" value={params.start_date} onChange={(e) => setParams({ ...params, start_date: e.target.value })} className="w-full mt-1" />
          </div>
          <div>
            <label className="text-xs text-dark-muted">{t("backtest.endDate")}</label>
            <input type="date" value={params.end_date} onChange={(e) => setParams({ ...params, end_date: e.target.value })} className="w-full mt-1" />
          </div>
          <div>
            <label className="text-xs text-dark-muted">{t("backtest.rebalance")}</label>
            <select value={params.rebalance} onChange={(e) => setParams({ ...params, rebalance: e.target.value })} className="w-full mt-1">
              <option value="monthly">{t("backtest.monthly")}</option>
              <option value="quarterly">{t("backtest.quarterly")}</option>
            </select>
          </div>
          <div className="flex items-end">
            <button onClick={handleRun} disabled={loading} className="w-full btn-primary px-4 py-2 text-sm disabled:opacity-50">
              {loading ? t("backtest.running") : t("backtest.run")}
            </button>
          </div>
        </div>
      </GlassCard>

      {result && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: t("backtest.totalReturn"), value: formatPercent(result.total_return), color: getChangeColor(result.total_return) },
              { label: t("backtest.annualReturn"), value: formatPercent(result.annual_return), color: getChangeColor(result.annual_return) },
              { label: t("backtest.excessReturn"), value: formatPercent(result.excess_return), color: getChangeColor(result.excess_return) },
              { label: t("backtest.maxDrawdown"), value: formatPercent(result.max_drawdown), color: "text-red-400" },
              { label: t("backtest.sharpeRatio"), value: result.sharpe_ratio.toFixed(2), color: result.sharpe_ratio >= 1 ? "text-emerald-400" : "text-amber-400" },
              { label: t("backtest.winRate"), value: `${result.win_rate.toFixed(1)}%`, color: "text-white" },
              { label: t("backtest.totalTrades"), value: String(result.total_trades), color: "text-white" },
              { label: t("backtest.benchmark"), value: formatPercent(result.benchmark_return), color: getChangeColor(result.benchmark_return) },
            ].map((m) => (
              <GlassCard key={m.label} className="text-center">
                <p className="text-xs text-dark-muted">{m.label}</p>
                <p className={`text-2xl font-bold mt-1 font-mono ${m.color}`}>{m.value}</p>
              </GlassCard>
            ))}
          </div>

          <GlassCard title={t("backtest.equityCurve")}>
            <div className="h-[400px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={result.equity_curve}>
                  <CartesianGrid stroke="#1E293B" />
                  <XAxis dataKey="date" tick={{ fontSize: 10, fill: "#94A3B8" }} interval="preserveStartEnd" />
                  <YAxis tick={{ fontSize: 10, fill: "#94A3B8" }} />
                  <Tooltip content={<CustomTooltip />} />
                  <Legend wrapperStyle={{ color: "#94A3B8" }} />
                  <Line type="monotone" dataKey="equity" stroke="#6366f1" strokeWidth={2} dot={false} name={t("backtest.strategyEquity")} />
                  <Line type="monotone" dataKey="benchmark" stroke="#94A3B8" strokeWidth={1} dot={false} name={t("backtest.benchmark")} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </GlassCard>

          <GlassCard title={t("backtest.monthlyExcess")}>
            <div className="h-[300px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={result.monthly_returns.slice(-24)}>
                  <CartesianGrid stroke="#1E293B" />
                  <XAxis dataKey="month" tick={{ fontSize: 10, fill: "#94A3B8" }} />
                  <YAxis tick={{ fontSize: 10, fill: "#94A3B8" }} />
                  <Tooltip content={<CustomTooltip />} />
                  <Bar dataKey="excess_return" fill="#6366f1" name={t("backtest.excessReturnPct")} radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </GlassCard>
        </>
      )}

      <div className="disclaimer">{t("app.disclaimer")}</div>
    </div>
  );
}
