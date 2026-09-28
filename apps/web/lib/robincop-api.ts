import walletSnapshots from '../data/wallet-snapshots.json';

export type DailyPnl = { date: string; pnl: number };

export type WalletListItem = {
  address: string;
  name: string | null;
  display_name: string;
  labels: string[];
  score: number;
  actual_pnl: number;
  copy_pnl: number;
  win_rate: number;
  copy_loss_rate: number | null;
  pnl_ratio: number;
  trading_days: number;
  recent_20: Record<string, number | string | null>;
  tokens_traded: number;
  trading_volume: number;
  avg_invest: number;
  target_daily_pnl_14d: DailyPnl[];
  copy_daily_pnl_14d: DailyPnl[];
  median_holding_time_seconds?: number | null;
  median_holding_time_ms?: number | null;
  median_hold_time_seconds?: number | null;
  metrics?: Record<string, unknown>;
  analyzed_at?: string;
  data_source?: 'live' | 'snapshot';
};

export type WalletDetail = WalletListItem & { metrics: Record<string, unknown> };

export type WalletCategoryCounts = {
  all: number;
  'smart-money': number;
  'kol-vc': number;
  fresh: number;
  sniper: number;
};

export type WalletListResponse = {
  items: WalletListItem[];
  total: number;
  category_counts?: WalletCategoryCounts;
};

export type WalletAnalysisStatus = {
  address: string;
  status: 'queued' | 'running' | 'completed' | 'failed' | 'paused';
  run_id: string | null;
  message?: string | null;
};

const apiUrl =
  process.env.API_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  'https://robincop.com/robincop-api';
const snapshots = walletSnapshots as unknown as WalletDetail[];
const configuredTimeout = Number(process.env.API_TIMEOUT_MS || 8000);
const apiTimeoutMs = Number.isFinite(configuredTimeout)
  ? Math.max(1000, Math.min(30_000, configuredTimeout))
  : 8000;

async function apiFetch<T>(path: string, fresh = false, init: RequestInit = {}): Promise<T | null> {
  if (!apiUrl) return null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), apiTimeoutMs);
  try {
    const response = await fetch(`${apiUrl.replace(/\/$/, '')}${path}`, {
      ...init,
      headers: { Accept: 'application/json', ...init.headers },
      signal: controller.signal,
      ...(fresh ? { cache: 'no-store' as const } : { next: { revalidate: 300 } }),
    });
    if (!response.ok) return null;
    return await response.json() as T;
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

export async function getWallets(): Promise<WalletListResponse | null> {
  const response = await apiFetch<WalletListResponse>(
    '/api/v1/wallets?limit=200',
    true,
  );
  if (response) {
    return {
      ...response,
      items: response.items.map((wallet) => ({ ...wallet, data_source: 'live' })),
    };
  }
  return { items: snapshots, total: snapshots.length };
}

export async function getWallet(address: string): Promise<WalletDetail | null> {
  const wallet = await apiFetch<WalletDetail>(
    `/api/v1/wallets/${encodeURIComponent(address)}?compact=true`,
    true,
  );
  if (wallet) return { ...wallet, data_source: 'live' };
  return snapshots.find((item) => item.address.toLowerCase() === address.toLowerCase()) ?? null;
}

export async function startWalletAnalysis(address: string): Promise<WalletAnalysisStatus | null> {
  return apiFetch<WalletAnalysisStatus>(
    `/api/v1/wallets/${encodeURIComponent(address)}/analysis`,
    true,
    { method: 'POST' },
  );
}
