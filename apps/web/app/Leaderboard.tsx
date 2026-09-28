'use client';

import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import { useRouter } from 'next/navigation';
import type { WalletCategoryCounts, WalletListItem } from '../lib/robincop-api';
import CopyAddressButton from './CopyAddressButton';
import LeaderboardRow from './LeaderboardRow';

export type WalletRow = {
  name: string; address: string; tags: string[]; score: number;
  copyDaily: number[]; actualPnl: number; copyPnl: number;
  winRate: number; lossRate: number; pnlRatio: number; days: number;
  recentPnl: number; recentWinRate: number; recentLossRate: number | null;
  tokens: number; pnlVolume: number; avgInvest: number; medianHoldSeconds: number | null;
};

type Category = 'all' | 'smart-money' | 'kol-vc' | 'fresh' | 'sniper';

const categories: Array<{ key: Category; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'smart-money', label: 'Smart Money' },
  { key: 'kol-vc', label: 'KOL/VC' },
  { key: 'fresh', label: 'Fresh' },
  { key: 'sniper', label: 'Sniper' },
];
const ROW_BATCH = 18;
const API_PAGE_SIZE = 200;
const WALLET_ADDRESS_PATTERN = /^0x[a-fA-F0-9]{40}$/;
const publicApiUrl = (process.env.NEXT_PUBLIC_API_URL || '/robincop-api').replace(/\/$/, '');

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

function walletItemToRow(item: WalletListItem): WalletRow {
  return {
    name: item.display_name,
    address: item.address,
    tags: item.labels,
    score: item.score,
    copyDaily: item.copy_daily_pnl_14d.map((day) => day.pnl),
    actualPnl: item.actual_pnl,
    copyPnl: item.copy_pnl,
    winRate: item.win_rate,
    lossRate: item.copy_loss_rate ?? 0,
    pnlRatio: item.pnl_ratio,
    days: item.trading_days,
    recentPnl: Number(item.recent_20.copy_backtest_pnl ?? 0),
    recentWinRate: Number(item.recent_20.win_rate ?? 0),
    recentLossRate: item.recent_20.copy_loss_rate == null ? null : Number(item.recent_20.copy_loss_rate),
    tokens: item.tokens_traded,
    pnlVolume: item.trading_volume > 0 ? (item.copy_pnl / item.trading_volume) * 100 : 0,
    avgInvest: item.avg_invest,
    medianHoldSeconds: medianHoldingSeconds(item),
  };
}

function money(value: number, compact = false) {
  const sign = value >= 0 ? '+' : '-';
  const amount = Math.abs(value);
  if (compact && amount >= 1000) return `${sign}$${(amount / 1000).toFixed(2)}K`;
  return `${sign}$${amount.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
}

function duration(value: number | null) {
  if (value === null) return 'N/A';
  const seconds = Math.max(0, Math.round(value));
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.floor((seconds % 86400) / 3600)}h`;
}

function MiniBars({ values }: { values: number[] }) {
  const max = Math.max(...values.map((value) => Math.abs(value)), 1);
  return <div className="mini-bars" aria-label="14 calendar day PnL chart">{values.map((value, index) => (
    <span className="bar-slot" key={`${index}-${value}`} title={`Day ${index + 1}: ${money(value)}`}><i className={value >= 0 ? 'bar bar-positive' : 'bar bar-negative'} style={{ height: `${Math.max(3, (Math.abs(value) / max) * 19)}px` }} /></span>
  ))}</div>;
}

function matchesCategory(row: WalletRow, category: Category) {
  if (category === 'all') return true;
  const labels = row.tags.map((tag) => tag.toLocaleLowerCase().replaceAll('_', ' ').replaceAll('-', ' '));
  if (category === 'smart-money') return labels.some((tag) => tag.includes('smart money'));
  if (category === 'kol-vc') return labels.some((tag) => /(^|\W)(kol|vc)($|\W)/.test(tag));
  return labels.some((tag) => tag.includes(category));
}

function MobileWalletCard({ row }: { row: WalletRow }) {
  const router = useRouter();
  const href = `/wallet/${row.address}`;
  const openDetail = () => router.push(href);
  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    openDetail();
  };

  return <div className="mobile-wallet-card" role="link" tabIndex={0} aria-label={`Open ${row.name} wallet details`} onClick={openDetail} onKeyDown={handleKeyDown}>
    <div className="mobile-wallet-card-head">
      <span className="wallet-identity">
        <span>
          <span className="wallet-name">{row.name}</span>
          <span className="wallet-address-line"><small>{row.address.slice(0, 7)}…{row.address.slice(-5)}</small><CopyAddressButton address={row.address} /></span>
        </span>
      </span>
      <span className="mobile-wallet-score"><small>Robin score</small><strong>{row.score}</strong></span>
    </div>

    {row.tags.length > 0 && <div className="tag-row">{row.tags.slice(0, 3).map((tag) => <span className="tag" key={tag}>{tag}</span>)}</div>}

    <div className="mobile-wallet-performance">
      <div className="mobile-wallet-primary-pnl"><span>Copy PnL · 14D</span><strong className={row.copyPnl >= 0 ? 'positive' : 'negative'}>{money(row.copyPnl, true)}</strong><small>{row.winRate.toFixed(1)}% win rate</small></div>
      <div className="mobile-wallet-trend"><span>Daily trend</span><MiniBars values={row.copyDaily} /></div>
    </div>

    <div className="mobile-wallet-metrics">
      <div><span>Actual PnL</span><strong className={row.actualPnl >= 0 ? 'positive' : 'negative'}>{money(row.actualPnl, true)}</strong></div>
      <div><span>Median hold</span><strong>{duration(row.medianHoldSeconds)}</strong></div>
      <div><span>Copy loss</span><strong>{row.lossRate.toFixed(1)}%</strong></div>
      <div><span>Tokens</span><strong>{row.tokens}</strong></div>
    </div>

    <div className="mobile-wallet-signals">
      <span>Recent 20 PnL <strong className={row.recentPnl >= 0 ? 'positive' : 'negative'}>{money(row.recentPnl, true)}</strong></span>
      <span>Trading days <strong>{row.days}</strong></span>
      <span>Avg invest <strong>${row.avgInvest.toLocaleString('en-US', { maximumFractionDigits: 0 })}</strong></span>
    </div>

    <div className="mobile-wallet-card-foot">
      <span className="mobile-wallet-view">View wallet analysis <b aria-hidden="true">→</b></span>
      <a className="copy-trade-link" href={`https://t.me/RobinCop_AI_Bot?start=A_ZETLYPGS_${row.address}`} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()} aria-label={`Copy trade wallet ${row.address}`}>Copy trade</a>
    </div>
  </div>;
}

export default function Leaderboard({
  rows,
  total,
  categoryCounts: databaseCategoryCounts,
  isSnapshot,
}: {
  rows: WalletRow[];
  total: number;
  categoryCounts?: WalletCategoryCounts;
  isSnapshot: boolean;
}) {
  const router = useRouter();
  const [loadedRows, setLoadedRows] = useState(rows);
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState<Category>('all');
  const [rowLimit, setRowLimit] = useState(ROW_BATCH);
  const [isLoadingPage, setIsLoadingPage] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const lastNavigatedAddressRef = useRef('');

  const categoryCounts = useMemo(() => {
    const loadedCounts = Object.fromEntries(categories.map(({ key }) => [
      key,
      loadedRows.filter((row) => matchesCategory(row, key)).length,
    ])) as Record<Category, number>;
    if (isSnapshot || !databaseCategoryCounts) return loadedCounts;
    return databaseCategoryCounts;
  }, [databaseCategoryCounts, isSnapshot, loadedRows]);

  const matchingRows = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    return loadedRows.filter((row) => {
      if (!matchesCategory(row, category)) return false;
      if (!needle) return true;
      return `${row.name} ${row.address} ${row.tags.join(' ')}`.toLocaleLowerCase().includes(needle);
    });
  }, [category, loadedRows, query]);
  const visibleRows = matchingRows.slice(0, rowLimit);
  const matchingTotal = query.trim() ? matchingRows.length : categoryCounts[category];
  const hasUnrevealedRows = visibleRows.length < matchingRows.length;
  const hasUnloadedRows = !isSnapshot && loadedRows.length < total;

  const navigateFromSearch = useCallback((event?: FormEvent<HTMLFormElement>) => {
    event?.preventDefault();
    const needle = query.trim();
    const exactRow = loadedRows.find((row) => row.address.toLocaleLowerCase() === needle.toLocaleLowerCase()
      || row.name.toLocaleLowerCase() === needle.toLocaleLowerCase());
    const address = WALLET_ADDRESS_PATTERN.test(needle)
      ? needle.toLocaleLowerCase()
      : exactRow?.address ?? (matchingRows.length === 1 ? matchingRows[0].address : null);
    if (!address) return;
    lastNavigatedAddressRef.current = address.toLocaleLowerCase();
    router.push(`/wallet/${address}`);
  }, [loadedRows, matchingRows, query, router]);

  useEffect(() => {
    const address = query.trim().toLocaleLowerCase();
    if (!WALLET_ADDRESS_PATTERN.test(address) || lastNavigatedAddressRef.current === address) return;
    const timer = setTimeout(() => {
      lastNavigatedAddressRef.current = address;
      router.push(`/wallet/${address}`);
    }, 180);
    return () => clearTimeout(timer);
  }, [query, router]);

  const loadNextPage = useCallback(async () => {
    if (isLoadingPage || !hasUnloadedRows) return;
    setIsLoadingPage(true);
    setLoadFailed(false);
    try {
      const response = await fetch(`${publicApiUrl}/api/v1/wallets?limit=${API_PAGE_SIZE}&offset=${loadedRows.length}`, {
        headers: { Accept: 'application/json' },
      });
      if (!response.ok) throw new Error(`Wallet page request failed (${response.status})`);
      const payload = await response.json() as { items?: WalletListItem[] };
      const nextRows = Array.isArray(payload.items) ? payload.items.map(walletItemToRow) : [];
      setLoadedRows((current) => {
        const known = new Set(current.map((row) => row.address.toLocaleLowerCase()));
        return [...current, ...nextRows.filter((row) => !known.has(row.address.toLocaleLowerCase()))];
      });
      setRowLimit((current) => current + ROW_BATCH);
    } catch {
      setLoadFailed(true);
    } finally {
      setIsLoadingPage(false);
    }
  }, [hasUnloadedRows, isLoadingPage, loadedRows.length]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || (!hasUnrevealedRows && !hasUnloadedRows)) return;
    const observer = new IntersectionObserver((entries) => {
      if (!entries.some((entry) => entry.isIntersecting)) return;
      if (hasUnrevealedRows) {
        setRowLimit((current) => current + ROW_BATCH);
      } else {
        void loadNextPage();
      }
    }, { rootMargin: '320px 0px' });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasUnloadedRows, hasUnrevealedRows, loadNextPage, visibleRows.length]);

  return (
    <section className="leaderboard" id="leaderboard">
      <div className="compact-leader-head"><div className="compact-title"><h1>Smart money wallets worth copying</h1></div><div className="table-actions"><form className="search-box" onSubmit={navigateFromSearch}><button className="search-submit" type="submit" aria-label="Open wallet search result">⌕</button><input type="search" value={query} onChange={(event) => { setQuery(event.target.value); setRowLimit(ROW_BATCH); }} placeholder="Search wallet or name" aria-label="Search wallet or name" /></form></div></div>
      <div className="table-toolbar"><div className="filters" role="group" aria-label="Filter wallets by category">{categories.map(({ key, label }) => <button type="button" className={category === key ? 'filter active' : 'filter'} aria-pressed={category === key} onClick={() => { setCategory(key); setRowLimit(ROW_BATCH); }} key={key}>{label} <b>{categoryCounts[key]}</b></button>)}</div><div className="table-summary"><span>{matchingTotal} wallets</span><span>5K trades</span><span>±2.5% copy model</span><span className="table-updated"><i className="live-dot" /> {isSnapshot ? 'Snapshot' : 'Live'}</span></div></div>
      <div className="table-wrap"><table className="leader-table"><thead><tr><th>Target wallet</th><th className="score-col">Score ↓</th><th><span className="th-title">Copy PnL</span><small>14 calendar days</small></th><th>Actual PnL</th><th>Copy PnL</th><th>Win rate</th><th>Copy loss</th><th>PnL ratio</th><th>Days</th><th><span className="th-title">Median hold</span><small>closed positions</small></th><th>Rec 20 PnL</th><th>Rec 20 WR</th><th>Rec 20 loss</th><th>Tokens</th><th>PnL/Vol</th><th>Avg invest</th></tr></thead>
        <tbody>{visibleRows.length ? visibleRows.map((row) => <LeaderboardRow key={row.address} href={`/wallet/${row.address}`} label={`Open ${row.name} wallet details`}>
          <td className="wallet-cell"><span className="wallet-identity"><span className="wallet-copy-layout"><span className="wallet-copy-info"><span className="wallet-name">{row.name}</span><span className="wallet-address-line"><small>{row.address.slice(0, 7)}…{row.address.slice(-5)}</small><CopyAddressButton address={row.address} /></span></span><a className="copy-trade-link wallet-copy-trade-link" href={`https://t.me/RobinCop_AI_Bot?start=A_ZETLYPGS_${row.address}`} target="_blank" rel="noopener noreferrer" onClick={(event) => event.stopPropagation()} onKeyDown={(event) => event.stopPropagation()} aria-label={`Copy trade wallet ${row.address}`} title="Open this wallet in RobinCop Bot">Copy</a></span></span></td>
          <td><span className="score">{row.score}</span></td><td><MiniBars values={row.copyDaily} /></td><td className={row.actualPnl >= 0 ? 'positive' : 'negative'}>{money(row.actualPnl, true)}</td><td className={`${row.copyPnl >= 0 ? 'positive' : 'negative'} strong`}>{money(row.copyPnl, true)}</td><td className="positive">{row.winRate.toFixed(1)}%</td><td>{row.lossRate.toFixed(1)}%</td><td>{row.pnlRatio.toFixed(2)}</td><td>{row.days}</td><td>{duration(row.medianHoldSeconds)}</td><td className={row.recentPnl >= 0 ? 'positive' : 'negative'}>{money(row.recentPnl, true)}</td><td className="positive">{row.recentWinRate.toFixed(1)}%</td><td>{row.recentLossRate === null ? 'N/A' : `${row.recentLossRate.toFixed(1)}%`}</td><td>{row.tokens}</td><td className="positive">+{row.pnlVolume.toFixed(2)}%</td><td>${row.avgInvest.toFixed(2)}</td>
        </LeaderboardRow>) : <tr><td className="leaderboard-empty" colSpan={16}>No wallets match this search and category.</td></tr>}</tbody></table></div>
      <div className="mobile-wallet-list">{visibleRows.length
        ? visibleRows.map((row) => <MobileWalletCard key={row.address} row={row} />)
        : <div className="mobile-wallet-empty">No wallets match this search and category.</div>}
      </div>
      {(hasUnrevealedRows || hasUnloadedRows) && <div ref={sentinelRef} className="list-infinite-sentinel" role="status" aria-live="polite"><span className={isLoadingPage ? 'detail-loading-spinner' : ''} />{loadFailed ? 'Unable to load more wallets. Scroll away and back to retry.' : isLoadingPage ? 'Loading more wallets…' : 'More wallets load automatically as you scroll'}</div>}
      <footer className="table-footer"><span>{`${matchingRows.length} loaded · ${total} qualified wallets`}</span><span>Sorted by Robin Score · {isSnapshot ? 'Verified snapshot' : 'Live feed'}</span></footer>
    </section>
  );
}
