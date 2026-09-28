import Image from 'next/image';
import Link from 'next/link';
import { Suspense } from 'react';
import { getWallets, type WalletListItem } from '../lib/robincop-api';
import Leaderboard, { type WalletRow } from './Leaderboard';

function finiteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function median(values: number[]) {
  if (values.length === 0) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 0 ? (sorted[middle - 1] + sorted[middle]) / 2 : sorted[middle];
}

function medianHoldingSeconds(wallet: WalletListItem): number | null {
  const metrics = wallet.metrics ?? {};
  const directSeconds = [
    wallet.median_holding_time_seconds,
    wallet.median_hold_time_seconds,
    metrics.median_holding_time_seconds,
    metrics.median_hold_time_seconds,
    metrics.median_holding_time,
  ].map(finiteNumber).find((value) => value !== null);
  if (directSeconds !== undefined) return Math.max(0, directSeconds);

  const directMilliseconds = finiteNumber(wallet.median_holding_time_ms ?? metrics.median_holding_time_ms);
  if (directMilliseconds !== null) return Math.max(0, directMilliseconds / 1000);

  const tokens = Array.isArray(metrics.all_tokens) ? metrics.all_tokens : [];
  const closedDurations = tokens.flatMap((entry) => {
    if (!entry || typeof entry !== 'object') return [];
    const token = entry as Record<string, unknown>;
    if (token.is_closed !== true) return [];
    const openedAt = finiteNumber(token.first_buy_time);
    const closedAt = finiteNumber(token.last_active);
    return openedAt !== null && closedAt !== null && closedAt >= openedAt ? [closedAt - openedAt] : [];
  });
  return median(closedDurations);
}

async function LeaderboardContent() {
  const response = await getWallets();
  const rows: WalletRow[] = response?.items.map((item) => ({
    name: item.display_name, address: item.address, tags: item.labels, score: item.score,
    copyDaily: item.copy_daily_pnl_14d.map((day) => day.pnl),
    actualPnl: item.actual_pnl, copyPnl: item.copy_pnl, winRate: item.win_rate, lossRate: item.copy_loss_rate ?? 0,
    pnlRatio: item.pnl_ratio, days: item.trading_days, recentPnl: Number(item.recent_20.copy_backtest_pnl ?? 0),
    recentWinRate: Number(item.recent_20.win_rate ?? 0), recentLossRate: item.recent_20.copy_loss_rate == null ? null : Number(item.recent_20.copy_loss_rate),
    tokens: item.tokens_traded, pnlVolume: item.trading_volume > 0 ? (item.copy_pnl / item.trading_volume) * 100 : 0, avgInvest: item.avg_invest,
    medianHoldSeconds: medianHoldingSeconds(item),
  })) ?? [];
  const total = response?.total ?? rows.length;
  const isSnapshot = response?.items.some((item) => item.data_source === 'snapshot') ?? false;

  return <Leaderboard rows={rows} total={total} categoryCounts={response?.category_counts} isSnapshot={isSnapshot} />;
}

function LeaderboardLoading() {
  return <section className="leaderboard leaderboard-loading" role="status" aria-live="polite">
    <div className="compact-leader-head"><div className="compact-title"><h1>Smart money wallets worth copying</h1></div></div>
    <div className="leaderboard-loading-cards" aria-hidden="true">{Array.from({ length: 6 }, (_, index) => <i key={index} />)}</div>
    <div className="leaderboard-loading-copy"><span className="detail-loading-spinner" />Loading wallet rankings…</div>
  </section>;
}

export default function Home() {
  return <main className="app-shell">
    <header className="topbar">
      <Link className="brand" href="/" aria-label="RobinCop home"><Image className="brand-logo" src="/robincop-logo.png" width={30} height={30} alt="" priority /><span><strong>RobinCop</strong><small>Copy-trade wallets on Robinhood Chain</small></span></Link>
      <div className="header-actions"><span className="chain-pill"><i /> Robinhood</span><a className="copy-cta" href="https://t.me/RobinCop_AI_Bot?start=ref_WMNE5NPY" target="_blank" rel="noreferrer">RobinCop Bot</a></div>
    </header>

    <Suspense fallback={<LeaderboardLoading />}><LeaderboardContent /></Suspense>

  </main>;
}
