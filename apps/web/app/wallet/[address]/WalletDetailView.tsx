'use client';

import type { WalletDetail } from '../../../lib/robincop-api';
import CopyAddressButton from '../../CopyAddressButton';
import InteractivePnlChart, { type PnlPoint } from './InteractivePnlChart';
import WalletDataTabs, { type HistoryRow, type PositionRow, type TradeRow } from './WalletDataTabs';

type Json = Record<string, unknown>;
type MetricCard = { label: string; value: string; tone?: string };

const array = (value: unknown): Json[] => Array.isArray(value)
  ? value.filter((item): item is Json => !!item && typeof item === 'object')
  : [];
const object = (value: unknown): Json => value && typeof value === 'object' && !Array.isArray(value) ? value as Json : {};
const numberOrNull = (value: unknown): number | null => {
  if (value === null || value === undefined || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const firstNumber = (...values: unknown[]): number | null => {
  for (const value of values) {
    const parsed = numberOrNull(value);
    if (parsed !== null) return parsed;
  }
  return null;
};
const money = (value: number | null, signed = true) => {
  if (value === null) return 'N/A';
  const sign = signed ? (value >= 0 ? '+' : '-') : '';
  return `${sign}$${Math.abs(value).toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
};
const percent = (value: number | null) => value === null ? 'N/A' : `${value.toFixed(2)}%`;
const count = (value: number | null) => value === null ? 'N/A' : Math.round(value).toLocaleString('en-US');
const metricTone = (value: number | null, positiveIsGood = true) => {
  if (value === null || value === 0) return '';
  return (value > 0) === positiveIsGood ? 'positive' : 'negative';
};
const timestampMs = (value: unknown): number | null => {
  const parsed = numberOrNull(value);
  if (parsed === null || parsed <= 0) return null;
  return parsed < 1_000_000_000_000 ? parsed * 1000 : parsed;
};

export default function WalletDetailView({ address, wallet }: { address: string; wallet: WalletDetail }) {
  const metrics = object(wallet.metrics);
  const equityPoints: PnlPoint[] = array(metrics.equity_curve).flatMap((point) => {
    const time = timestampMs(point.timestamp_ms);
    const targetPnl = numberOrNull(point.target_pnl_usd);
    const copyPnl = numberOrNull(point.copy_pnl_usd);
    return time !== null && targetPnl !== null && copyPnl !== null
      ? [{ timestampMs: time, targetPnl, copyPnl }]
      : [];
  });
  let chartPoints = equityPoints;
  if (chartPoints.length < 2) {
    const targetDaily = array(metrics.target_daily_pnl_14d).length ? array(metrics.target_daily_pnl_14d) : wallet.target_daily_pnl_14d as unknown as Json[];
    const copyDaily = array(metrics.copy_daily_pnl_14d).length ? array(metrics.copy_daily_pnl_14d) : wallet.copy_daily_pnl_14d as unknown as Json[];
    let targetTotal = 0;
    let copyTotal = 0;
    chartPoints = targetDaily.slice(0, Math.min(targetDaily.length, copyDaily.length)).flatMap((target, index) => {
      targetTotal += numberOrNull(target.pnl) ?? 0;
      copyTotal += numberOrNull(copyDaily[index]?.pnl) ?? 0;
      const time = Date.parse(`${String(target.date || copyDaily[index]?.date || '')}T00:00:00Z`);
      return Number.isFinite(time) ? [{ timestampMs: time, targetPnl: targetTotal, copyPnl: copyTotal }] : [];
    });
  }
  const hasChart = chartPoints.length >= 2;

  const actualPnl = firstNumber(wallet.actual_pnl, metrics.actual_pnl);
  const backtestPnl = firstNumber(wallet.copy_pnl, metrics.copy_backtest_pnl);
  const copyLossRate = firstNumber(metrics.copy_loss_rate, wallet.copy_loss_rate);
  const retention = firstNumber(metrics.pnl_retention_rate);
  const recent20 = object(metrics.recent_20_stats);
  const recent20CopyPnl = firstNumber(recent20.copy_backtest_pnl, wallet.recent_20.copy_backtest_pnl);
  const copyRoi = firstNumber(metrics.copy_roi_on_required_cash);
  const tokenWinRate = firstNumber(metrics.token_win_rate, wallet.win_rate);
  const sellWinRate = firstNumber(metrics.sell_win_rate);
  const pnlRatio = firstNumber(metrics.avg_profit_loss_ratio, wallet.pnl_ratio);
  const tradingDays = firstNumber(metrics.trading_days, wallet.trading_days);
  const tradingVolume = firstNumber(metrics.trading_volume, wallet.trading_volume);
  const requiredCapital = firstNumber(metrics.required_starting_cash_usd);
  const tokensTraded = firstNumber(metrics.tokens_traded, wallet.tokens_traded);
  const tradesAnalyzed = firstNumber(metrics.processed_trade_count);
  const openPositions = firstNumber(metrics.open_token_count);
  const buyCount = firstNumber(metrics.buy_count);
  const sellCount = firstNumber(metrics.sell_count);
  const avgInvestment = firstNumber(metrics.avg_invest_per_token, wallet.avg_invest);
  const lastActive = String(metrics.last_active || wallet.analyzed_at || 'N/A');
  const metricCards: MetricCard[] = [
    { label: 'Actual PnL', value: money(actualPnl), tone: metricTone(actualPnl) },
    { label: 'Copy Backtest PnL', value: money(backtestPnl), tone: metricTone(backtestPnl) },
    { label: 'Copy Loss Rate', value: percent(copyLossRate), tone: copyLossRate !== null && copyLossRate > 30 ? 'negative' : '' },
    { label: 'Recent 20 Copy PnL', value: money(recent20CopyPnl), tone: metricTone(recent20CopyPnl) },
    { label: 'Profit Retention', value: percent(retention) },
    { label: 'Copy ROI', value: percent(copyRoi), tone: metricTone(copyRoi) },
    { label: 'Token Win Rate', value: percent(tokenWinRate) },
    { label: 'Sell Win Rate', value: percent(sellWinRate) },
    { label: 'PnL Ratio', value: pnlRatio === null ? 'N/A' : pnlRatio.toFixed(2) },
    { label: 'Trading Days', value: count(tradingDays), tone: 'amber' },
    { label: 'Trading Volume', value: money(tradingVolume, false) },
    { label: 'Required Capital', value: money(requiredCapital, false) },
    { label: 'Tokens Traded', value: count(tokensTraded) },
    { label: 'Trades Analyzed', value: count(tradesAnalyzed) },
    { label: 'Open Positions', value: count(openPositions) },
    { label: 'Buy / Sell Trades', value: buyCount === null && sellCount === null ? 'N/A' : `${count(buyCount)} / ${count(sellCount)}` },
    { label: 'Avg Investment', value: money(avgInvestment, false) },
    { label: 'Last Activity', value: lastActive },
  ];

  const perToken = array(metrics.per_token);
  const allTokens = array(metrics.all_tokens).length ? array(metrics.all_tokens) : perToken;
  const lastActivityByToken = new Map(allTokens.flatMap((row) => {
    const tokenAddress = String(row.token_address || row.condition_id || '').toLowerCase();
    const lastActivity = timestampMs(row.last_active || row.last_timestamp_ms);
    return tokenAddress && lastActivity !== null ? [[tokenAddress, lastActivity] as const] : [];
  }));
  const canonicalPositions = array(metrics.position_rows);
  const positionSource = canonicalPositions.length
    ? canonicalPositions
    : perToken.filter((row) => (numberOrNull(row.copy_ending_quantity) ?? 0) > 0);
  const positions: PositionRow[] = positionSource.map((row) => {
    const target = object(row.target);
    const copy = object(row.copy);
    return {
      symbol: String(row.token_symbol || row.symbol || row.title || ''),
      address: String(row.token_address || row.condition_id || ''),
      lastActivityMs: timestampMs(row.last_active || row.last_timestamp_ms)
        ?? lastActivityByToken.get(String(row.token_address || row.condition_id || '').toLowerCase())
        ?? null,
      invested: firstNumber(row.copy_cost_basis_usd, copy.ending_cost_basis_usd, row.invested),
      marketValue: firstNumber(row.copy_market_value_usd, copy.market_value_usd),
      markPrice: firstNumber(row.mark_price_usd, row.copy_exit_mark_price_usd),
      actualPnl: firstNumber(row.actual_pnl, target.total_pnl_usd),
      copyPnl: firstNumber(row.copy_pnl, row.bt_copy_pnl, copy.total_pnl_usd),
      actualProfitRate: firstNumber(row.actual_profit_rate),
      copyProfitRate: firstNumber(row.copy_profit_rate),
    };
  }).filter((row) => row.invested !== null && row.invested >= 0.01).slice(0, 500);

  const history: HistoryRow[] = allTokens.map((row) => {
    const target = object(row.target);
    const copy = object(row.copy);
    const closed = row.is_closed == null ? (numberOrNull(row.target_ending_quantity) ?? 0) <= 0 : Boolean(row.is_closed);
    const firstBuyMs = timestampMs(row.first_buy_time || row.first_timestamp_ms || row.opened_at);
    const lastActivityMs = timestampMs(row.last_active || row.last_timestamp_ms);
    const analyzedAtMs = Date.parse(String(wallet.analyzed_at || ''));
    const holdingEndMs = closed
      ? lastActivityMs
      : Number.isFinite(analyzedAtMs) ? analyzedAtMs : lastActivityMs;
    const reportedHoldingSeconds = firstNumber(row.holding_time_seconds, row.hold_time_seconds, row.holding_duration_seconds);
    return {
      symbol: String(row.symbol || row.title || row.token_symbol || ''),
      address: String(row.token_address || row.condition_id || ''),
      invested: firstNumber(row.invested, target.gross_buy_usd),
      actualPnl: firstNumber(row.actual_pnl, target.total_pnl_usd),
      copyPnl: firstNumber(row.bt_copy_pnl, row.copy_pnl, copy.total_pnl_usd),
      actualProfitRate: firstNumber(row.actual_profit_rate),
      copyProfitRate: firstNumber(row.copy_profit_rate),
      closed,
      lastActivityMs,
      holdingSeconds: reportedHoldingSeconds ?? (firstBuyMs !== null && holdingEndMs !== null
        ? Math.max(0, (holdingEndMs - firstBuyMs) / 1000)
        : null),
    };
  }).slice(0, 500);

  const exactTrades = array(metrics.trade_results).slice(-200).reverse();
  const recentActivity = exactTrades.length ? exactTrades : [...allTokens]
    .sort((left, right) => (numberOrNull(right.last_active) ?? 0) - (numberOrNull(left.last_active) ?? 0))
    .slice(0, 200);
  const trades: TradeRow[] = recentActivity.map((row) => {
    const isSummary = exactTrades.length === 0;
    const timestamp = timestampMs(row.timestamp_ms || row.last_active);
    return {
      timestampMs: timestamp,
      symbol: String(row.token_symbol || row.symbol || row.title || ''),
      address: String(row.token_address || row.condition_id || ''),
      side: isSummary ? (Boolean(row.is_closed) ? 'closed' : 'open') : String(row.side || ''),
      quantity: firstNumber(row.executed_token_amount, row.closed_size),
      targetPrice: firstNumber(row.target_price_usd, row.avg_buy_price),
      copyPrice: firstNumber(row.copy_price_usd, row.avg_sell_price),
      notional: firstNumber(row.target_notional_usd, row.invested),
      isSummary,
    };
  });

  const displayName = wallet.display_name || `${address.slice(0, 6)}...${address.slice(-5)}`;
  const tags = [...(wallet.labels || [])];
  if (wallet.data_source === 'snapshot') tags.push('Analysis snapshot');
  const score = numberOrNull(wallet.score) ?? 0;

  return (
    <>
      <section className="wallet-hero"><div><div className="wallet-title-copy-layout"><div className="wallet-title-copy-info"><h1>{displayName}</h1><div className="full-address-line"><div className="full-address">{address}</div><CopyAddressButton address={address} /></div></div><a className="copy-trade-link detail-copy-trade-link" href={`https://t.me/RobinCop_AI_Bot?start=A_ZETLYPGS_${address}`} target="_blank" rel="noopener noreferrer" aria-label={`Copy trade wallet ${address}`} title="Open this wallet in RobinCop Bot">Copy</a></div>{tags.length > 0 && <div className="tag-row detail-tags">{tags.map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div>}</div><div className="detail-score"><span>ROBIN SCORE</span><strong>{score}</strong><small>{score > 30 ? 'QUALIFIED' : 'RESEARCH'}</small></div></section>
      <section className="metric-grid">{metricCards.map(({ label, value, tone }) => <article className="metric-card" key={label}><span>{label}</span><strong className={tone}>{value}</strong></article>)}</section>
      <section className="detail-panel chart-panel"><div className="panel-head"><div><p className="eyebrow">PERFORMANCE GAP</p><h2>Cumulative PnL</h2></div>{hasChart && <div className="legend"><span className="target-dot" />Target wallet <span className="copy-dot" />Copy simulation</div>}</div>{hasChart ? <div className="chart-area"><InteractivePnlChart points={chartPoints} /></div> : <div className="chart-empty">No performance series is available for this analysis.</div>}</section>
      <WalletDataTabs walletAddress={address} positions={positions} history={history} trades={trades} totalHistory={tokensTraded} />
    </>
  );
}
