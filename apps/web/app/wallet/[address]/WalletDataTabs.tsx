'use client';

import { useEffect, useMemo, useRef, useState } from 'react';

type OptionalNumber = number | null;
type SortDirection = 'asc' | 'desc';
type SortState<K extends string> = { key: K; direction: SortDirection };
type SortValue = string | number | boolean | null;
type PositionSortKey = 'token' | 'lastActivityMs' | 'invested' | 'marketValue' | 'markPrice' | 'actualPnl' | 'copyPnl';
type HistorySortKey = 'token' | 'lastActivityMs' | 'holdingSeconds' | 'closed' | 'invested' | 'actualPnl' | 'copyPnl' | 'copyGap';
type TradeSortKey = 'token' | 'timestampMs' | 'side' | 'quantity' | 'targetPrice' | 'copyPrice' | 'notional';

export type PositionRow = {
  symbol: string;
  address: string;
  lastActivityMs: OptionalNumber;
  invested: OptionalNumber;
  marketValue: OptionalNumber;
  markPrice: OptionalNumber;
  actualPnl: OptionalNumber;
  copyPnl: OptionalNumber;
  actualProfitRate: OptionalNumber;
  copyProfitRate: OptionalNumber;
};
export type HistoryRow = {
  symbol: string;
  address: string;
  invested: OptionalNumber;
  actualPnl: OptionalNumber;
  copyPnl: OptionalNumber;
  actualProfitRate: OptionalNumber;
  copyProfitRate: OptionalNumber;
  closed: boolean;
  lastActivityMs: OptionalNumber;
  holdingSeconds: OptionalNumber;
};
export type TradeRow = {
  timestampMs: OptionalNumber;
  symbol: string;
  address: string;
  side: string;
  quantity: OptionalNumber;
  targetPrice: OptionalNumber;
  copyPrice: OptionalNumber;
  notional: OptionalNumber;
  isSummary: boolean;
};
type DrawerTrade = {
  timestampMs: OptionalNumber;
  side: string;
  quantity: OptionalNumber;
  targetPrice: OptionalNumber;
  copyPrice: OptionalNumber;
  notional: OptionalNumber;
  realizedPnl: OptionalNumber;
  txHash: string;
};
type DrawerToken = {
  symbol: string;
  address: string;
  status: string;
  holdingSeconds: OptionalNumber;
  invested: OptionalNumber;
  actualPnl: OptionalNumber;
  copyPnl: OptionalNumber;
  actualProfitRate: OptionalNumber;
  copyProfitRate: OptionalNumber;
  lastActivityMs: OptionalNumber;
};
const ROW_BATCH = 50;

const money = (value: OptionalNumber, signed = true) => {
  if (value === null) return '—';
  const sign = signed ? (value >= 0 ? '+' : '-') : '';
  return `${sign}$${Math.abs(value).toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
};
const pnlWithRate = (pnl: OptionalNumber, rate: OptionalNumber) => {
  if (pnl === null) return '—';
  if (rate === null) return `${money(pnl)} —`;
  const sign = rate > 0 ? '+' : rate < 0 ? '-' : '';
  return `${money(pnl)} ${sign}${Math.abs(rate).toFixed(2)}%`;
};
const number = (value: OptionalNumber) => value === null ? '—' : value.toLocaleString('en-US', { maximumFractionDigits: 4 });
const price = (value: OptionalNumber) => value === null
  ? '—'
  : `$${value.toLocaleString('en-US', { maximumSignificantDigits: 4 })}`;
const time = (timestampMs: OptionalNumber) => {
  if (!timestampMs || timestampMs <= 0) return '—';
  const date = new Date(timestampMs);
  return Number.isNaN(date.getTime()) ? '—' : date.toISOString().replace('T', ' ').slice(0, 19);
};
const holdingTime = (seconds: OptionalNumber) => {
  if (seconds === null) return '—';
  const total = Math.max(0, Math.round(seconds));
  if (total < 60) return `${total}s`;
  if (total < 3600) return `${Math.floor(total / 60)}m ${total % 60}s`;
  if (total < 86400) return `${Math.floor(total / 3600)}h ${Math.floor((total % 3600) / 60)}m`;
  return `${Math.floor(total / 86400)}d ${Math.floor((total % 86400) / 3600)}h`;
};
const finite = (value: unknown): OptionalNumber => {
  if (value === null || value === undefined || value === '') return null;
  const parsed = typeof value === 'number' ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};
const unitPrice = (reported: OptionalNumber, notional: OptionalNumber, quantity: OptionalNumber): OptionalNumber => {
  if (reported !== null && reported > 0) return reported;
  if (notional === null || quantity === null || quantity === 0) return reported;
  return Math.abs(notional / quantity);
};
const timestamp = (value: unknown): OptionalNumber => {
  const parsed = finite(value);
  if (parsed === null || parsed <= 0) return null;
  return parsed < 10_000_000_000 ? parsed * 1000 : parsed;
};
const shortHash = (value: string) => value.length > 15 ? `${value.slice(0, 8)}…${value.slice(-6)}` : value;
const tone = (value: OptionalNumber) => value === null || value === 0 ? '' : value > 0 ? 'positive' : 'negative';
const tokenValue = (row: { symbol: string; address: string }) => `${row.symbol} ${row.address}`.toLocaleLowerCase();
const positionDrawerToken = (row: PositionRow): DrawerToken => ({
  symbol: row.symbol,
  address: row.address,
  status: 'Open',
  holdingSeconds: null,
  invested: row.invested,
  actualPnl: row.actualPnl,
  copyPnl: row.copyPnl,
  actualProfitRate: row.actualProfitRate,
  copyProfitRate: row.copyProfitRate,
  lastActivityMs: row.lastActivityMs,
});
const historyDrawerToken = (row: HistoryRow): DrawerToken => ({
  symbol: row.symbol,
  address: row.address,
  status: row.closed ? 'Closed' : 'Open',
  holdingSeconds: row.holdingSeconds,
  invested: row.invested,
  actualPnl: row.actualPnl,
  copyPnl: row.copyPnl,
  actualProfitRate: row.actualProfitRate,
  copyProfitRate: row.copyProfitRate,
  lastActivityMs: row.lastActivityMs,
});
const tradeDrawerToken = (row: TradeRow): DrawerToken => ({
  symbol: row.symbol,
  address: row.address,
  status: row.isSummary ? (row.side === 'open' ? 'Open' : 'Closed') : (row.side ? row.side.toUpperCase() : '—'),
  holdingSeconds: null,
  invested: row.notional,
  actualPnl: null,
  copyPnl: null,
  actualProfitRate: null,
  copyProfitRate: null,
  lastActivityMs: row.timestampMs,
});

function nextSort<K extends string>(current: SortState<K>, key: K, preferred: SortDirection): SortState<K> {
  return current.key === key
    ? { key, direction: current.direction === 'asc' ? 'desc' : 'asc' }
    : { key, direction: preferred };
}

function compareValues(left: SortValue, right: SortValue, direction: SortDirection) {
  if (left === null && right === null) return 0;
  if (left === null) return 1;
  if (right === null) return -1;
  let result: number;
  if (typeof left === 'string' || typeof right === 'string') {
    result = String(left).localeCompare(String(right), undefined, { numeric: true, sensitivity: 'base' });
  } else {
    result = Number(left) - Number(right);
  }
  return direction === 'asc' ? result : -result;
}

function sortedRows<T, K extends string>(
  rows: T[],
  state: SortState<K>,
  value: (row: T, key: K) => SortValue,
) {
  return [...rows].sort((left, right) => compareValues(value(left, state.key), value(right, state.key), state.direction));
}

function SortableHeader<K extends string>({
  label,
  column,
  state,
  preferred = 'asc',
  onSort,
}: {
  label: string;
  column: K;
  state: SortState<K>;
  preferred?: SortDirection;
  onSort: (column: K, preferred: SortDirection) => void;
}) {
  const active = state.key === column;
  return (
    <th aria-sort={active ? (state.direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button
        type="button"
        className={active ? 'sort-button active' : 'sort-button'}
        onClick={() => onSort(column, preferred)}
        aria-label={`${label}, ${active ? (state.direction === 'asc' ? 'sorted ascending; activate to sort descending' : 'sorted descending; activate to sort ascending') : 'activate to sort'}`}
      >
        <span>{label}</span>
        <i aria-hidden="true">{active ? (state.direction === 'asc' ? '↑' : '↓') : '↕'}</i>
      </button>
    </th>
  );
}

export default function WalletDataTabs({
  walletAddress,
  positions,
  history,
  trades,
  totalHistory,
}: {
  walletAddress: string;
  positions: PositionRow[];
  history: HistoryRow[];
  trades: TradeRow[];
  totalHistory: OptionalNumber;
}) {
  const [tab, setTab] = useState<'positions' | 'history' | 'trades'>('history');
  const [positionSort, setPositionSort] = useState<SortState<PositionSortKey>>({ key: 'actualPnl', direction: 'desc' });
  const [historySort, setHistorySort] = useState<SortState<HistorySortKey>>({ key: 'lastActivityMs', direction: 'desc' });
  const [tradeSort, setTradeSort] = useState<SortState<TradeSortKey>>({ key: 'timestampMs', direction: 'desc' });
  const [positionLimit, setPositionLimit] = useState(ROW_BATCH);
  const [historyLimit, setHistoryLimit] = useState(ROW_BATCH);
  const [tradeLimit, setTradeLimit] = useState(ROW_BATCH);
  const [selectedToken, setSelectedToken] = useState<DrawerToken | null>(null);
  const [drawerTrades, setDrawerTrades] = useState<DrawerTrade[]>([]);
  const [drawerTotal, setDrawerTotal] = useState(0);
  const [drawerLoading, setDrawerLoading] = useState(false);
  const [drawerError, setDrawerError] = useState('');
  const tradeRequest = useRef<AbortController | null>(null);
  const summaryMode = trades.length > 0 && trades.every((row) => row.isSummary);
  const positionCount = positions.length;
  const historyCount = totalHistory === null ? history.length : Math.round(totalHistory);

  const sortedPositions = useMemo(() => sortedRows(positions, positionSort, (row, key) => {
    if (key === 'token') return tokenValue(row);
    return row[key];
  }), [positionSort, positions]);

  const sortedHistory = useMemo(() => sortedRows(history, historySort, (row, key) => {
    if (key === 'token') return tokenValue(row);
    if (key === 'copyGap') return row.copyPnl === null || row.actualPnl === null ? null : row.copyPnl - row.actualPnl;
    return row[key];
  }), [history, historySort]);

  const sortedTrades = useMemo(() => sortedRows(trades, tradeSort, (row, key) => {
    if (key === 'token') return tokenValue(row);
    return row[key];
  }), [tradeSort, trades]);
  const visiblePositions = sortedPositions.slice(0, positionLimit);
  const visibleHistory = sortedHistory.slice(0, historyLimit);
  const visibleTrades = sortedTrades.slice(0, tradeLimit);

  const updatePositionSort = (column: PositionSortKey, preferred: SortDirection) => setPositionSort((current) => nextSort(current, column, preferred));
  const updateHistorySort = (column: HistorySortKey, preferred: SortDirection) => setHistorySort((current) => nextSort(current, column, preferred));
  const updateTradeSort = (column: TradeSortKey, preferred: SortDirection) => setTradeSort((current) => nextSort(current, column, preferred));

  const closeDrawer = () => {
    tradeRequest.current?.abort();
    tradeRequest.current = null;
    setSelectedToken(null);
  };

  const openToken = async (row: DrawerToken) => {
    tradeRequest.current?.abort();
    const controller = new AbortController();
    tradeRequest.current = controller;
    setSelectedToken(row);
    setDrawerTrades([]);
    setDrawerTotal(0);
    setDrawerError('');
    setDrawerLoading(true);

    if (!row.address) {
      setDrawerError('This token has no contract address, so its trades cannot be loaded.');
      setDrawerLoading(false);
      return;
    }

    try {
      const url = `https://robincop.com/robincop-api/api/v1/wallets/${encodeURIComponent(walletAddress)}/tokens/${encodeURIComponent(row.address)}/trades?limit=1000`;
      const response = await fetch(url, { headers: { Accept: 'application/json' }, signal: controller.signal });
      if (!response.ok) throw new Error(`Trade history request failed (${response.status}).`);
      const payload = await response.json() as { items?: unknown[]; total?: unknown };
      const items = Array.isArray(payload.items) ? payload.items : [];
      const normalized = items.flatMap((item): DrawerTrade[] => {
        if (!item || typeof item !== 'object') return [];
        const trade = item as Record<string, unknown>;
        const quantity = finite(trade.executed_token_amount ?? trade.requested_token_amount);
        const targetNotional = finite(trade.target_notional_usd);
        const copyNotional = finite(trade.copy_notional_usd);
        return [{
          timestampMs: timestamp(trade.timestamp_ms ?? trade.timestamp),
          side: String(trade.side || '').toLocaleLowerCase(),
          quantity,
          targetPrice: unitPrice(finite(trade.target_price_usd), targetNotional, quantity),
          copyPrice: unitPrice(finite(trade.copy_price_usd), copyNotional, quantity),
          notional: targetNotional ?? copyNotional,
          realizedPnl: finite(trade.target_realized_pnl_usd ?? trade.copy_realized_pnl_usd),
          txHash: String(trade.tx_hash || ''),
        }];
      });
      if (!controller.signal.aborted) {
        setDrawerTrades(normalized);
        setDrawerTotal(Math.max(normalized.length, Math.round(finite(payload.total) ?? normalized.length)));
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        setDrawerError(error instanceof Error ? error.message : 'Trade history could not be loaded.');
      }
    } finally {
      if (!controller.signal.aborted) setDrawerLoading(false);
    }
  };

  useEffect(() => {
    if (!selectedToken) return;
    const previousOverflow = document.body.style.overflow;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeDrawer();
    };
    document.body.style.overflow = 'hidden';
    window.addEventListener('keydown', onKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', onKeyDown);
    };
  }, [selectedToken]);

  useEffect(() => () => tradeRequest.current?.abort(), []);

  return (
    <>
    <section className="detail-panel">
      <div className="panel-head portfolio-tabs-head">
        <div className="panel-tabs" role="tablist" aria-label="Portfolio data">
          <button role="tab" aria-selected={tab === 'positions'} className={tab === 'positions' ? 'active' : ''} onClick={() => setTab('positions')}>Open positions <b>{positionCount}</b></button>
          <button role="tab" aria-selected={tab === 'history'} className={tab === 'history' ? 'active' : ''} onClick={() => setTab('history')}>Token history <b>{historyCount}</b></button>
          <button role="tab" aria-selected={tab === 'trades'} className={tab === 'trades' ? 'active' : ''} onClick={() => setTab('trades')}>Recent trades <b>{trades.length}</b></button>
        </div>
      </div>
      <div className="detail-table-wrap">
        {tab === 'positions' && <table className="detail-table token-data-table"><thead><tr>
          <SortableHeader label="Token" column="token" state={positionSort} onSort={updatePositionSort} />
          <SortableHeader label="Last trade (UTC)" column="lastActivityMs" state={positionSort} preferred="desc" onSort={updatePositionSort} />
          <SortableHeader label="Cost basis" column="invested" state={positionSort} preferred="desc" onSort={updatePositionSort} />
          <SortableHeader label="Market value" column="marketValue" state={positionSort} preferred="desc" onSort={updatePositionSort} />
          <SortableHeader label="Mark price" column="markPrice" state={positionSort} preferred="desc" onSort={updatePositionSort} />
          <SortableHeader label="Actual PnL" column="actualPnl" state={positionSort} preferred="desc" onSort={updatePositionSort} />
          <SortableHeader label="Copy PnL" column="copyPnl" state={positionSort} preferred="desc" onSort={updatePositionSort} />
        </tr></thead><tbody>
          {visiblePositions.length ? visiblePositions.map((row) => <tr
            className={row.address ? 'token-detail-row' : 'token-detail-row disabled'}
            key={row.address}
            role={row.address ? 'button' : undefined}
            tabIndex={row.address ? 0 : -1}
            aria-label={row.address ? `View ${row.symbol || 'token'} trade details` : undefined}
            onClick={() => row.address && void openToken(positionDrawerToken(row))}
            onKeyDown={(event) => {
              if (row.address && (event.key === 'Enter' || event.key === ' ')) {
                event.preventDefault();
                void openToken(positionDrawerToken(row));
              }
            }}
          ><td className="token-cell"><strong title={row.symbol || 'Unknown'}>{row.symbol || 'Unknown'}</strong></td><td>{time(row.lastActivityMs)}</td><td>{money(row.invested, false)}</td><td>{money(row.marketValue, false)}</td><td>{row.markPrice === null ? '—' : `$${number(row.markPrice)}`}</td><td className={tone(row.actualPnl)}>{pnlWithRate(row.actualPnl, row.actualProfitRate)}</td><td className={tone(row.copyPnl)}>{pnlWithRate(row.copyPnl, row.copyProfitRate)}</td></tr>) : <tr><td colSpan={7} className="empty-state">No open positions in the analyzed trade window.</td></tr>}
        </tbody></table>}
        {tab === 'history' && <table className="detail-table token-data-table"><thead><tr>
          <SortableHeader label="Token" column="token" state={historySort} onSort={updateHistorySort} />
          <SortableHeader label="Last trade (UTC)" column="lastActivityMs" state={historySort} preferred="desc" onSort={updateHistorySort} />
          <SortableHeader label="Holding time" column="holdingSeconds" state={historySort} preferred="desc" onSort={updateHistorySort} />
          <SortableHeader label="Status" column="closed" state={historySort} onSort={updateHistorySort} />
          <SortableHeader label="Invested" column="invested" state={historySort} preferred="desc" onSort={updateHistorySort} />
          <SortableHeader label="Actual PnL" column="actualPnl" state={historySort} preferred="desc" onSort={updateHistorySort} />
          <SortableHeader label="Copy PnL" column="copyPnl" state={historySort} preferred="desc" onSort={updateHistorySort} />
          <SortableHeader label="Copy gap" column="copyGap" state={historySort} preferred="desc" onSort={updateHistorySort} />
        </tr></thead><tbody>
          {visibleHistory.length ? visibleHistory.map((row) => {
            const gap = row.copyPnl === null || row.actualPnl === null ? null : row.copyPnl - row.actualPnl;
            return <tr
              className={row.address ? 'token-detail-row' : 'token-detail-row disabled'}
              key={row.address}
              role={row.address ? 'button' : undefined}
              tabIndex={row.address ? 0 : -1}
              aria-label={row.address ? `View ${row.symbol || 'token'} trade details` : undefined}
              onClick={() => row.address && void openToken(historyDrawerToken(row))}
              onKeyDown={(event) => {
                if (row.address && (event.key === 'Enter' || event.key === ' ')) {
                  event.preventDefault();
                  void openToken(historyDrawerToken(row));
                }
              }}
            ><td className="token-cell"><strong title={row.symbol || 'Unknown'}>{row.symbol || 'Unknown'}</strong></td><td>{time(row.lastActivityMs)}</td><td>{holdingTime(row.holdingSeconds)}</td><td>{row.closed ? 'Closed' : 'Open'}</td><td>{money(row.invested, false)}</td><td className={tone(row.actualPnl)}>{pnlWithRate(row.actualPnl, row.actualProfitRate)}</td><td className={tone(row.copyPnl)}>{pnlWithRate(row.copyPnl, row.copyProfitRate)}</td><td className={tone(gap)}>{money(gap)}</td></tr>;
          }) : <tr><td colSpan={8} className="empty-state">No token history is available for this analysis.</td></tr>}
        </tbody></table>}
        {tab === 'trades' && (summaryMode
          ? <table className="detail-table token-data-table"><thead><tr>
            <SortableHeader label="Token" column="token" state={tradeSort} onSort={updateTradeSort} />
            <SortableHeader label="Last activity (UTC)" column="timestampMs" state={tradeSort} preferred="desc" onSort={updateTradeSort} />
            <SortableHeader label="Status" column="side" state={tradeSort} onSort={updateTradeSort} />
            <SortableHeader label="Closed quantity" column="quantity" state={tradeSort} preferred="desc" onSort={updateTradeSort} />
            <SortableHeader label="Avg buy" column="targetPrice" state={tradeSort} preferred="desc" onSort={updateTradeSort} />
            <SortableHeader label="Avg sell" column="copyPrice" state={tradeSort} preferred="desc" onSort={updateTradeSort} />
            <SortableHeader label="Invested" column="notional" state={tradeSort} preferred="desc" onSort={updateTradeSort} />
          </tr></thead><tbody>
            {visibleTrades.map((row, index) => <tr
              className={row.address ? 'token-detail-row' : 'token-detail-row disabled'}
              key={`${row.timestampMs}-${row.address}-${index}`}
              role={row.address ? 'button' : undefined}
              tabIndex={row.address ? 0 : -1}
              aria-label={row.address ? `View ${row.symbol || 'token'} trade details` : undefined}
              onClick={() => row.address && void openToken(tradeDrawerToken(row))}
              onKeyDown={(event) => {
                if (row.address && (event.key === 'Enter' || event.key === ' ')) {
                  event.preventDefault();
                  void openToken(tradeDrawerToken(row));
                }
              }}
            ><td className="token-cell"><strong title={row.symbol || 'Unknown'}>{row.symbol || 'Unknown'}</strong></td><td>{time(row.timestampMs)}</td><td className={row.side === 'open' ? 'positive' : ''}>{row.side === 'open' ? 'Open' : 'Closed'}</td><td>{number(row.quantity)}</td><td>{price(row.targetPrice)}</td><td>{price(row.copyPrice)}</td><td>{money(row.notional, false)}</td></tr>)}
          </tbody></table>
          : <table className="detail-table token-data-table"><thead><tr>
            <SortableHeader label="Token" column="token" state={tradeSort} onSort={updateTradeSort} />
            <SortableHeader label="Time (UTC)" column="timestampMs" state={tradeSort} preferred="desc" onSort={updateTradeSort} />
            <SortableHeader label="Side" column="side" state={tradeSort} onSort={updateTradeSort} />
            <SortableHeader label="Quantity" column="quantity" state={tradeSort} preferred="desc" onSort={updateTradeSort} />
            <SortableHeader label="Target price" column="targetPrice" state={tradeSort} preferred="desc" onSort={updateTradeSort} />
            <SortableHeader label="Copy price" column="copyPrice" state={tradeSort} preferred="desc" onSort={updateTradeSort} />
            <SortableHeader label="Notional" column="notional" state={tradeSort} preferred="desc" onSort={updateTradeSort} />
          </tr></thead><tbody>
            {visibleTrades.length ? visibleTrades.map((row, index) => <tr
              className={row.address ? 'token-detail-row' : 'token-detail-row disabled'}
              key={`${row.timestampMs}-${row.address}-${index}`}
              role={row.address ? 'button' : undefined}
              tabIndex={row.address ? 0 : -1}
              aria-label={row.address ? `View ${row.symbol || 'token'} trade details` : undefined}
              onClick={() => row.address && void openToken(tradeDrawerToken(row))}
              onKeyDown={(event) => {
                if (row.address && (event.key === 'Enter' || event.key === ' ')) {
                  event.preventDefault();
                  void openToken(tradeDrawerToken(row));
                }
              }}
            ><td className="token-cell"><strong title={row.symbol || 'Unknown'}>{row.symbol || 'Unknown'}</strong></td><td>{time(row.timestampMs)}</td><td className={row.side === 'buy' ? 'positive' : row.side === 'sell' ? 'negative' : ''}>{row.side.toUpperCase()}</td><td>{number(row.quantity)}</td><td>{price(row.targetPrice)}</td><td>{price(row.copyPrice)}</td><td>{money(row.notional, false)}</td></tr>) : <tr><td colSpan={7} className="empty-state">No recent activity is available for this analysis.</td></tr>}
          </tbody></table>)}
        {tab === 'positions' && visiblePositions.length < sortedPositions.length && <div className="detail-load-more-wrap"><button className="load-more-button" type="button" onClick={() => setPositionLimit((current) => current + ROW_BATCH)}>Show more positions <span>{visiblePositions.length}/{sortedPositions.length}</span></button></div>}
        {tab === 'history' && visibleHistory.length < sortedHistory.length && <div className="detail-load-more-wrap"><button className="load-more-button" type="button" onClick={() => setHistoryLimit((current) => current + ROW_BATCH)}>Show more tokens <span>{visibleHistory.length}/{sortedHistory.length}</span></button></div>}
        {tab === 'trades' && visibleTrades.length < sortedTrades.length && <div className="detail-load-more-wrap"><button className="load-more-button" type="button" onClick={() => setTradeLimit((current) => current + ROW_BATCH)}>Show more trades <span>{visibleTrades.length}/{sortedTrades.length}</span></button></div>}
      </div>
    </section>
    {selectedToken && <div className="trade-drawer-layer">
      <button className="trade-drawer-backdrop" type="button" aria-label="Close trade details" onClick={closeDrawer} />
      <aside className="trade-drawer" role="dialog" aria-modal="true" aria-labelledby="trade-drawer-title">
        <header className="trade-drawer-head">
          <div>
            <p className="eyebrow">TOKEN TRADE DETAILS</p>
            <h2 id="trade-drawer-title">{selectedToken.symbol || 'Unknown token'}</h2>
            <small>{selectedToken.address}</small>
          </div>
          <button type="button" className="trade-drawer-close" onClick={closeDrawer} aria-label="Close trade details">×</button>
        </header>
        <section className="trade-drawer-summary" aria-label="Token summary">
          <div><span>Status</span><strong>{selectedToken.status}</strong></div>
          <div><span>Holding time</span><strong>{holdingTime(selectedToken.holdingSeconds)}</strong></div>
          <div><span>Invested</span><strong>{money(selectedToken.invested, false)}</strong></div>
          <div><span>Actual PnL</span><strong className={tone(selectedToken.actualPnl)}>{pnlWithRate(selectedToken.actualPnl, selectedToken.actualProfitRate)}</strong></div>
          <div><span>Copy PnL</span><strong className={tone(selectedToken.copyPnl)}>{pnlWithRate(selectedToken.copyPnl, selectedToken.copyProfitRate)}</strong></div>
          <div><span>Last trade</span><strong>{time(selectedToken.lastActivityMs)}</strong></div>
        </section>
        <div className="trade-drawer-body">
          {drawerLoading && <div className="drawer-message">Loading trade history…</div>}
          {!drawerLoading && drawerError && <div className="drawer-message error">{drawerError}</div>}
          {!drawerLoading && !drawerError && <>
            <div className="trade-drawer-count"><strong>{drawerTotal.toLocaleString('en-US')}</strong> trades · newest first</div>
            <div className="trade-drawer-table-wrap">
              <table className="trade-drawer-table">
                <thead><tr><th>Time (UTC)</th><th>Side</th><th>Quantity</th><th>Target price</th><th>Copy price</th><th>Notional</th><th>Realized PnL</th><th>Transaction</th></tr></thead>
                <tbody>
                  {drawerTrades.length ? drawerTrades.map((trade, index) => <tr key={`${trade.timestampMs}-${trade.txHash}-${index}`}>
                    <td>{time(trade.timestampMs)}</td>
                    <td><span className={`trade-side ${trade.side}`}>{trade.side ? trade.side.toUpperCase() : '—'}</span></td>
                    <td>{number(trade.quantity)}</td>
                    <td>{price(trade.targetPrice)}</td>
                    <td>{price(trade.copyPrice)}</td>
                    <td>{money(trade.notional, false)}</td>
                    <td className={tone(trade.realizedPnl)}>{money(trade.realizedPnl)}</td>
                    <td>{trade.txHash ? <span className="transaction-hash" title={trade.txHash}>{shortHash(trade.txHash)}</span> : '—'}</td>
                  </tr>) : <tr><td colSpan={8} className="drawer-empty">No trades were found for this token.</td></tr>}
                </tbody>
              </table>
            </div>
          </>}
        </div>
      </aside>
    </div>}
    </>
  );
}
