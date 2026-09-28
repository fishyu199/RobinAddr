'use client';

import { useEffect, useState, type ReactNode } from 'react';
import Image from 'next/image';
import Link from 'next/link';

type DiscoverySettings = {
  period: string;
  limit: number;
  sort_by: string;
  interval_minutes: number;
  max_new_analyses_per_run: number;
  analysis_concurrency: number;
  score_threshold: number;
  reanalysis_interval_days: number;
  direction: string;
  auto_analyze: boolean;
  filters: { min_realized_profit?: number; min_total_cost?: number };
};

type Status = {
  discovery_enabled: boolean;
  analysis_enabled: boolean;
  candidate_count: number;
  unqualified_count: number;
  all_candidate_count: number;
  published_count: number;
  queued_count: number;
  running_count: number;
  stale_task_count: number;
  last_collection_at?: string | null;
  last_successful_collection_at?: string | null;
  last_successful_analysis_at?: string | null;
  scheduler_heartbeat_at?: string | null;
  scheduler_heartbeat?: { recovered_total?: number; note?: string };
  continuous_analysis?: boolean;
  gmgn_cooldown_seconds?: number;
  gmgn_cooldown_until?: string | null;
  next_collection_at?: string | null;
  latest_analysis_batch?: AnalysisBatch | null;
  discovery_settings: DiscoverySettings;
};

type Run = {
  id: string;
  address: string;
  status: string;
  trigger: string;
  score: number | null;
  published: boolean;
  input_trade_count?: number;
  created_at: string;
  error?: string;
};

type Candidate = {
  address: string;
  name?: string;
  labels: string[];
  source_rank?: number;
  discovery_metrics: Record<string, unknown>;
  status: string;
  last_score?: number;
  last_seen_at?: string;
  last_analyzed_at?: string;
  next_eligible_at?: string;
  last_error?: string;
};

type PublishedWallet = {
  address: string;
  display_name: string;
  labels: string[];
  score: number;
  actual_pnl: number;
  copy_pnl: number;
  win_rate: number;
  tokens_traded: number;
  analyzed_at?: string;
};

type Batch = {
  id: string;
  status: string;
  requested_count: number;
  received_count: number;
  new_count: number;
  duplicate_count: number;
  queued_count: number;
  started_at: string;
  error?: string;
  config: Record<string, unknown>;
};

type AnalysisBatch = {
  id: string;
  kind: string;
  status: string;
  requested_count: number;
  total_count: number;
  completed_count: number;
  failed_count: number;
  skipped_count: number;
  processed_count: number;
  progress_percent: number;
  current_address?: string | null;
  created_at: string;
  started_at?: string | null;
  completed_at?: string | null;
};

export type AdminSection = 'overview' | 'collection' | 'wallets' | 'tasks' | 'settings';
type WalletTab = 'pending' | 'unqualified' | 'published';

type SortDirection = 'asc' | 'desc';
type TableQuery = { page: number; sortBy: string; direction: SortDirection };
type PageResult<T> = { items: T[]; total: number; limit: number; offset: number };

const PAGE_SIZE = 20;

function tablePath(path: string, query: TableQuery, extra: Record<string, string> = {}) {
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String((query.page - 1) * PAGE_SIZE),
    sort_by: query.sortBy,
    direction: query.direction,
    ...extra,
  });
  return `${path}?${params.toString()}`;
}

function nextSort(query: TableQuery, sortBy: string): TableQuery {
  if (query.sortBy === sortBy) {
    return { ...query, page: 1, direction: query.direction === 'asc' ? 'desc' : 'asc' };
  }
  return { page: 1, sortBy, direction: 'desc' };
}

function SortHeader({ children, sortBy, query, onSort }: { children: ReactNode; sortBy: string; query: TableQuery; onSort: (sortBy: string) => void }) {
  const active = query.sortBy === sortBy;
  return (
    <th aria-sort={active ? (query.direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
      <button className={`admin-sort-button ${active ? 'active' : ''}`} onClick={() => onSort(sortBy)}>
        <span>{children}</span><i>{active ? (query.direction === 'asc' ? '↑' : '↓') : '↕'}</i>
      </button>
    </th>
  );
}

function Pagination({ page, total, onPage }: { page: number; total: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const start = total === 0 ? 0 : (page - 1) * PAGE_SIZE + 1;
  const end = Math.min(page * PAGE_SIZE, total);
  return (
    <div className="admin-pagination">
      <span>显示 {start}–{end}，共 {total} 条</span>
      <div><button disabled={page <= 1} onClick={() => onPage(page - 1)}>上一页</button><strong>{page} / {pages}</strong><button disabled={page >= pages} onClick={() => onPage(page + 1)}>下一页</button></div>
    </div>
  );
}

const apiUrl = (process.env.NEXT_PUBLIC_API_URL || '/robincop-api').replace(/\/$/, '');
// Production authentication is enforced by the admin reverse proxy. The proxy
// replaces this marker with the server-side API key, so no secret is bundled
// into browser JavaScript.
const adminKey = 'proxy-authenticated';
const defaultSettings: DiscoverySettings = {
  period: '7d',
  limit: 200,
  sort_by: 'realized_profit',
  interval_minutes: 30,
  max_new_analyses_per_run: 20,
  analysis_concurrency: 1,
  score_threshold: 30,
  reanalysis_interval_days: 7,
  direction: 'desc',
  auto_analyze: true,
  filters: { min_realized_profit: 0, min_total_cost: 1000 },
};

function shortAddress(address: string) {
  return `${address.slice(0, 8)}...${address.slice(-5)}`;
}

function number(value: unknown) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function money(value: unknown) {
  if (value == null || value === '') return '—';
  const parsed = number(value);
  return `${parsed >= 0 ? '+' : '-'}$${Math.abs(parsed).toLocaleString(undefined, { maximumFractionDigits: 2 })}`;
}

function statusTone(value: string) {
  if (['completed', 'qualified'].includes(value)) return 'success';
  if (['queued', 'pending', 'running', 'analyzing'].includes(value)) return 'running';
  return 'rejected';
}

function dateTime(value?: string | null) {
  return value ? new Date(value).toLocaleString() : '—';
}

const adminSectionPaths: Record<AdminSection, string> = {
  overview: '/admin',
  collection: '/admin/collection',
  wallets: '/admin/wallets',
  tasks: '/admin/tasks',
  settings: '/admin/settings',
};

function sectionFromPath(pathname: string): AdminSection {
  const match = (Object.entries(adminSectionPaths) as [AdminSection, string][])
    .find(([, path]) => pathname === path);
  return match?.[0] || 'overview';
}

export function AdminDashboard({ section = 'overview' }: { section?: AdminSection }) {
  const [activeSection, setActiveSection] = useState<AdminSection>(section);
  const [connected, setConnected] = useState(false);
  const [status, setStatus] = useState<Status | null>(null);
  const [runs, setRuns] = useState<Run[]>([]);
  const [runTotal, setRunTotal] = useState(0);
  const [runQuery, setRunQuery] = useState<TableQuery>({ page: 1, sortBy: 'created_at', direction: 'desc' });
  const [candidates, setCandidates] = useState<Candidate[]>([]);
  const [candidateTotal, setCandidateTotal] = useState(0);
  const [candidateQuery, setCandidateQuery] = useState<TableQuery>({ page: 1, sortBy: 'source_rank', direction: 'asc' });
  const [unqualified, setUnqualified] = useState<Candidate[]>([]);
  const [unqualifiedTotal, setUnqualifiedTotal] = useState(0);
  const [unqualifiedQuery, setUnqualifiedQuery] = useState<TableQuery>({ page: 1, sortBy: 'last_score', direction: 'desc' });
  const [publishedWallets, setPublishedWallets] = useState<PublishedWallet[]>([]);
  const [publishedTotal, setPublishedTotal] = useState(0);
  const [publishedQuery, setPublishedQuery] = useState<TableQuery>({ page: 1, sortBy: 'score', direction: 'desc' });
  const [batches, setBatches] = useState<Batch[]>([]);
  const [batchTotal, setBatchTotal] = useState(0);
  const [batchQuery, setBatchQuery] = useState<TableQuery>({ page: 1, sortBy: 'started_at', direction: 'desc' });
  const [analysisBatches, setAnalysisBatches] = useState<AnalysisBatch[]>([]);
  const [analysisBatchTotal, setAnalysisBatchTotal] = useState(0);
  const [analysisBatchQuery, setAnalysisBatchQuery] = useState<TableQuery>({ page: 1, sortBy: 'created_at', direction: 'desc' });
  const [walletTab, setWalletTab] = useState<WalletTab>('pending');
  const [wallet, setWallet] = useState('');
  const [message, setMessage] = useState('正在连接管理系统…');
  const [busy, setBusy] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [collectionSubmitting, setCollectionSubmitting] = useState(false);
  const [recomputeSubmitting, setRecomputeSubmitting] = useState(false);
  const [settings, setSettings] = useState<DiscoverySettings>(defaultSettings);

  function switchSection(next: AdminSection) {
    if (next === activeSection) return;
    setActiveSection(next);
    window.history.pushState({ adminSection: next }, '', adminSectionPaths[next]);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  async function request(path: string, init?: RequestInit, key = adminKey) {
    let response: Response;
    try {
      response = await fetch(`${apiUrl}${path}`, {
        ...init,
        headers: {
          'Content-Type': 'application/json',
          'X-Admin-Key': key,
          ...(init?.headers || {}),
        },
      });
    } catch {
      throw new Error('暂时无法连接后台，请点击刷新数据重试。');
    }
    if (!response.ok) {
      if (response.status === 401) throw new Error('后台鉴权配置不一致，请检查服务器配置。');
      throw new Error((await response.json().catch(() => null))?.detail || `请求失败（${response.status}）`);
    }
    return response.json();
  }

  async function loadDashboard(key = adminKey, showBusy = true, announce = true, syncSettings = showBusy) {
    if (!key) {
      setMessage('请先输入管理密钥。');
      return;
    }
    if (showBusy) setBusy(true);
    try {
      const [nextStatus, nextRuns, nextCandidates, nextUnqualified, nextPublished, nextBatches, nextAnalysisBatches] = await Promise.all([
        request('/api/v1/admin/status', undefined, key),
        request(tablePath('/api/v1/admin/runs', runQuery), undefined, key),
        request(tablePath('/api/v1/admin/candidates', candidateQuery, { pool: 'pending' }), undefined, key),
        request(tablePath('/api/v1/admin/candidates', unqualifiedQuery, { pool: 'unqualified' }), undefined, key),
        request(tablePath('/api/v1/admin/published-wallets', publishedQuery), undefined, key),
        request(tablePath('/api/v1/admin/discovery-batches', batchQuery), undefined, key),
        request(tablePath('/api/v1/admin/analysis-batches', analysisBatchQuery), undefined, key),
      ]);
      setStatus(nextStatus);
      setRuns((nextRuns as PageResult<Run>).items);
      setRunTotal((nextRuns as PageResult<Run>).total);
      setCandidates((nextCandidates as PageResult<Candidate>).items);
      setCandidateTotal((nextCandidates as PageResult<Candidate>).total);
      setUnqualified((nextUnqualified as PageResult<Candidate>).items);
      setUnqualifiedTotal((nextUnqualified as PageResult<Candidate>).total);
      setPublishedWallets((nextPublished as PageResult<PublishedWallet>).items);
      setPublishedTotal((nextPublished as PageResult<PublishedWallet>).total);
      setBatches((nextBatches as PageResult<Batch>).items);
      setBatchTotal((nextBatches as PageResult<Batch>).total);
      setAnalysisBatches((nextAnalysisBatches as PageResult<AnalysisBatch>).items);
      setAnalysisBatchTotal((nextAnalysisBatches as PageResult<AnalysisBatch>).total);
      if (syncSettings) {
        setSettings({
          ...defaultSettings,
          ...nextStatus.discovery_settings,
          filters: {
            ...defaultSettings.filters,
            ...(nextStatus.discovery_settings?.filters || {}),
          },
        });
      }
      setConnected(true);
      if (announce) setMessage('系统已连接，数据会自动刷新。');
    } catch (error) {
      setConnected(false);
      setMessage(error instanceof Error ? error.message : '连接失败');
    } finally {
      if (showBusy) setBusy(false);
    }
  }

  async function refresh() {
    await loadDashboard(adminKey, true, true);
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadDashboard(adminKey);
    }, 0);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const handlePopState = () => setActiveSection(sectionFromPath(window.location.pathname));
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  useEffect(() => {
    if (!connected) return;
    const timer = window.setInterval(() => {
      void loadDashboard(adminKey, false, false);
    }, 15000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connected, candidateQuery, unqualifiedQuery, publishedQuery, batchQuery, analysisBatchQuery, runQuery]);

  async function updateTable<T>(path: string, query: TableQuery, setItems: (items: T[]) => void, setTotal: (total: number) => void) {
    if (!connected) return;
    try {
      const result = await request(tablePath(path, query)) as PageResult<T>;
      setItems(result.items);
      setTotal(result.total);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '列表加载失败');
    }
  }

  function changeCandidateQuery(next: TableQuery) {
    setCandidateQuery(next);
    if (!connected) return;
    void request(tablePath('/api/v1/admin/candidates', next, { pool: 'pending' }))
      .then((result: PageResult<Candidate>) => { setCandidates(result.items); setCandidateTotal(result.total); })
      .catch((error) => setMessage(error instanceof Error ? error.message : '候选池加载失败'));
  }

  function changeUnqualifiedQuery(next: TableQuery) {
    setUnqualifiedQuery(next);
    if (!connected) return;
    void request(tablePath('/api/v1/admin/candidates', next, { pool: 'unqualified' }))
      .then((result: PageResult<Candidate>) => { setUnqualified(result.items); setUnqualifiedTotal(result.total); })
      .catch((error) => setMessage(error instanceof Error ? error.message : '不合格池加载失败'));
  }

  function changePublishedQuery(next: TableQuery) {
    setPublishedQuery(next);
    void updateTable<PublishedWallet>('/api/v1/admin/published-wallets', next, setPublishedWallets, setPublishedTotal);
  }

  function changeBatchQuery(next: TableQuery) {
    setBatchQuery(next);
    void updateTable<Batch>('/api/v1/admin/discovery-batches', next, setBatches, setBatchTotal);
  }

  function changeRunQuery(next: TableQuery) {
    setRunQuery(next);
    void updateTable<Run>('/api/v1/admin/runs', next, setRuns, setRunTotal);
  }

  function changeAnalysisBatchQuery(next: TableQuery) {
    setAnalysisBatchQuery(next);
    void updateTable<AnalysisBatch>('/api/v1/admin/analysis-batches', next, setAnalysisBatches, setAnalysisBatchTotal);
  }

  async function action(path: string, body?: object, method = 'POST', success = '任务已提交。') {
    if (!connected) {
      setMessage('请先连接管理后台。');
      return;
    }
    setBusy(true);
    try {
      await request(path, { method, body: body ? JSON.stringify(body) : undefined });
      await loadDashboard(adminKey, false, false);
      setMessage(success);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '操作失败');
    } finally {
      setBusy(false);
    }
  }

  async function toggle(name: 'discovery' | 'analysis', enabled: boolean) {
    await action(
      `/api/v1/admin/control/${name}`,
      { enabled },
      'PUT',
      enabled ? '任务已启动。' : '任务已暂停。',
    );
  }

  async function saveDiscoverySettings(runAfter = false) {
    if (!connected) return;
    setSettingsBusy(true);
    if (runAfter) setCollectionSubmitting(true);
    try {
      await request('/api/v1/admin/discovery-settings', {
        method: 'PUT',
        body: JSON.stringify(settings),
      });
      if (runAfter) {
        await request('/api/v1/admin/discovery/run', { method: 'POST' });
      }
      await loadDashboard(adminKey, false, false);
      setMessage(runAfter ? '设置已保存，手动采集任务已启动。' : '采集设置已保存。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '操作失败');
    } finally {
      setSettingsBusy(false);
      if (runAfter) setCollectionSubmitting(false);
    }
  }

  async function saveCollectionInterval() {
    if (!connected) return;
    if (!Number.isInteger(settings.interval_minutes) || settings.interval_minutes < 5 || settings.interval_minutes > 43200) {
      setMessage('自动采集间隔必须是 5–43200 之间的整数分钟。');
      return;
    }
    setSettingsBusy(true);
    try {
      await request('/api/v1/admin/discovery-settings', {
        method: 'PUT',
        body: JSON.stringify(settings),
      });
      await loadDashboard(adminKey, false, false, false);
      setMessage(`自动采集间隔已改为每 ${settings.interval_minutes} 分钟。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '采集间隔保存失败');
    } finally {
      setSettingsBusy(false);
    }
  }

  async function collectNow() {
    if (!connected) return;
    setCollectionSubmitting(true);
    try {
      await request('/api/v1/admin/discovery/run', { method: 'POST' });
      await loadDashboard(adminKey, false, false);
      setMessage('手动采集任务已加入队列。');
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '采集任务提交失败');
    } finally {
      setCollectionSubmitting(false);
    }
  }

  async function analyzeAllCandidates() {
    if (!connected) return;
    setBusy(true);
    try {
      const result = await request('/api/v1/admin/analyze-candidates', { method: 'POST' });
      await loadDashboard(adminKey, false, false);
      setMessage(`已建立未评分候选的逐个计算批次：共 ${result.total} 个，待逐个处理 ${result.queued} 个，已有任务跳过 ${result.skipped} 个。前一个完成后才会启动下一个。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '批量计算提交失败');
    } finally {
      setBusy(false);
    }
  }

  async function recomputePublished() {
    if (!connected) return;
    setRecomputeSubmitting(true);
    try {
      const result = await request('/api/v1/admin/recompute-all', { method: 'POST' });
      await loadDashboard(adminKey, false, false);
      setMessage(`正式地址库重算已启动：共 ${result.total} 个，已加入队列 ${result.queued} 个，已有任务跳过 ${result.skipped} 个。`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : '正式地址库重算启动失败');
    } finally {
      setRecomputeSubmitting(false);
    }
  }

  const discovery = status?.discovery_enabled ?? true;
  const analysis = status?.analysis_enabled ?? true;
  const latestBatch = batches[0];
  const latestAnalysisBatch = status?.latest_analysis_batch || analysisBatches[0];
  const latestConfig = latestBatch?.config || {};
  const pageInfo: Record<AdminSection, { title: string; description: string }> = {
    overview: { title: '系统概览', description: '查看采集、分析和正式地址库的整体运行状态。' },
    collection: { title: '地址采集', description: '配置并运行 GMGN Smart Money 交易流采集，查看每次采集结果。' },
    wallets: { title: '地址库', description: '按待计算、不合格和正式地址三个阶段管理钱包。' },
    tasks: { title: '分析任务', description: '查看逐个计算批次、单地址任务和失败原因。' },
    settings: { title: '系统设置', description: '管理地址计算并发、入库分数和正式地址重算周期。' },
  };
  const pipeline = [
    { step: '01', title: 'Smart Money 采集', value: String(latestConfig.feed_trade_count ?? '—'), note: 'GMGN Robinhood Smart Money 交易流' },
    { step: '02', title: '提取钱包', value: String(latestConfig.feed_unique_wallets ?? '—'), note: '本轮不同钱包' },
    { step: '03', title: '发现总池', value: String(latestConfig.candidate_pool_size ?? status?.all_candidate_count ?? '—'), note: '去重保存的全部地址' },
    { step: '04', title: 'PnL 排名', value: String(latestBatch?.received_count ?? '—'), note: `${settings.period.toUpperCase()} · ${settings.sort_by}` },
    { step: '05', title: '地址计算', value: String((status?.queued_count ?? 0) + (status?.running_count ?? 0)), note: `并发上限 ${settings.analysis_concurrency}` },
    { step: '06', title: '评分入库', value: String(status?.published_count ?? '—'), note: `Robin Score > ${settings.score_threshold}` },
  ];

  return (
    <main className="admin-shell">
      <aside className="admin-sidebar">
        <Link className="brand admin-brand" href="/">
          <Image className="brand-logo" src="/robincop-logo.png" width={36} height={36} alt="" />
          <span><strong>RobinCop</strong><small>管理后台</small></span>
        </Link>
        <nav>
          <button className={activeSection === 'overview' ? 'active' : ''} onClick={() => switchSection('overview')}>系统概览</button>
          <button className={activeSection === 'collection' ? 'active' : ''} onClick={() => switchSection('collection')}>地址采集</button>
          <button className={activeSection === 'wallets' ? 'active' : ''} onClick={() => switchSection('wallets')}>地址库</button>
          <button className={activeSection === 'tasks' ? 'active' : ''} onClick={() => switchSection('tasks')}>分析任务</button>
          <button className={activeSection === 'settings' ? 'active' : ''} onClick={() => switchSection('settings')}>系统设置</button>
        </nav>
        <div className="admin-user">
          <span>管理员</span>
          <small>{connected ? '系统已连接' : '等待连接'}</small>
        </div>
      </aside>

      <section className="admin-content">
        <nav className="admin-mobile-nav" aria-label="管理后台栏目">
          <button className={activeSection === 'overview' ? 'active' : ''} onClick={() => switchSection('overview')}>概览</button>
          <button className={activeSection === 'collection' ? 'active' : ''} onClick={() => switchSection('collection')}>地址采集</button>
          <button className={activeSection === 'wallets' ? 'active' : ''} onClick={() => switchSection('wallets')}>地址库</button>
          <button className={activeSection === 'tasks' ? 'active' : ''} onClick={() => switchSection('tasks')}>分析任务</button>
          <button className={activeSection === 'settings' ? 'active' : ''} onClick={() => switchSection('settings')}>系统设置</button>
        </nav>
        <header className="admin-head">
          <div>
            <p className="eyebrow">ROBINHOOD COPY INTELLIGENCE</p>
            <h1>{pageInfo[activeSection].title}</h1>
            <p>{pageInfo[activeSection].description}</p>
          </div>
          {activeSection === 'collection' && <button
            className="primary-btn"
            disabled={collectionSubmitting || !connected}
            onClick={collectNow}
          >
            {collectionSubmitting ? '正在提交…' : '立即采集一次'}
          </button>}
        </header>

        <section className={`admin-login ${connected ? 'connected' : ''}`}>
          <span className="connection-indicator" />
          <span>{message}</span>
          <button className="secondary-btn" disabled={busy} onClick={refresh}>刷新数据</button>
        </section>

        <section className="admin-page-actions" hidden={activeSection !== 'collection'}>
          <div>
            <span className={`status-dot ${discovery ? '' : 'paused'}`} />
            <strong>定时采集{discovery ? '已开启' : '已暂停'}</strong>
            <small>当前每 {settings.interval_minutes} 分钟运行一次；手动采集始终可用。</small>
          </div>
          <button disabled={!connected || busy} className={discovery ? 'switch on' : 'switch'} onClick={() => toggle('discovery', !discovery)} aria-label="切换定时采集"><span /></button>
        </section>

        <div className="admin-tabs" hidden={activeSection !== 'wallets'}>
          <button className={walletTab === 'pending' ? 'active' : ''} onClick={() => setWalletTab('pending')}>待计算 <b>{candidateTotal}</b></button>
          <button className={walletTab === 'unqualified' ? 'active' : ''} onClick={() => setWalletTab('unqualified')}>不合格 <b>{unqualifiedTotal}</b></button>
          <button className={walletTab === 'published' ? 'active' : ''} onClick={() => setWalletTab('published')}>正式地址库 <b>{publishedTotal}</b></button>
        </div>

        <div className="control-grid" hidden={activeSection !== 'overview'}>
          <article className="control-card">
            <div>
              <label className="control-interval">
                <span className={`status-dot ${discovery ? '' : 'paused'}`} />
                <strong>每</strong>
                <input type="number" min="5" max="43200" step="1" aria-label="自动采集间隔分钟数" value={settings.interval_minutes} onChange={(event) => setSettings({ ...settings, interval_minutes: Number(event.target.value) })} />
                <strong>分钟自动采集</strong>
              </label>
              <p>只控制定时采集；关闭后仍可点击“立即采集一次”手动运行。</p>
            </div>
            <div className="control-card-actions">
              <button className="secondary-btn compact-btn" disabled={!connected || settingsBusy} onClick={saveCollectionInterval}>{settingsBusy ? '保存中…' : '保存间隔'}</button>
              <button
                disabled={!connected || busy}
                className={discovery ? 'switch on' : 'switch'}
                onClick={() => toggle('discovery', !discovery)}
                aria-label="切换定时采集"
              ><span /></button>
            </div>
          </article>
          <article className="control-card">
            <div>
              <span className={`status-dot ${analysis ? '' : 'paused'}`} />
              <strong>地址分析队列</strong>
              <p>当前并发 {settings.analysis_concurrency}；评分大于 {settings.score_threshold} 才发布，正式地址每 {settings.reanalysis_interval_days} 天重算。</p>
            </div>
            <button
              disabled={!connected || busy}
              className={analysis ? 'switch on' : 'switch'}
              onClick={() => toggle('analysis', !analysis)}
              aria-label="切换地址计算"
            ><span /></button>
          </article>
        </div>

        <div className="admin-stats" hidden={activeSection !== 'overview'}>
          {[
            ['候选池', String(status?.candidate_count ?? '—'), '尚未评分'],
            ['不合格池', String(status?.unqualified_count ?? '—'), `评分 ≤ ${settings.score_threshold}`],
            ['正式地址', String(status?.published_count ?? '—'), `评分 > ${settings.score_threshold}`],
            ['排队中', String(status?.queued_count ?? '—'), '分析任务'],
            ['计算中', String(status?.running_count ?? '—'), `并发上限 ${settings.analysis_concurrency}`],
            ['异常任务', String(status?.stale_task_count ?? '—'), status?.scheduler_heartbeat?.note || '每 5 分钟自动检查'],
            ['调度心跳', dateTime(status?.scheduler_heartbeat_at), `累计恢复 ${status?.scheduler_heartbeat?.recovered_total ?? 0} 个`],
            ['最近计算成功', dateTime(status?.last_successful_analysis_at), '地址分析完成时间'],
            ['持续计算', status?.continuous_analysis ? '已开启' : '—', status?.gmgn_cooldown_seconds ? `GMGN 限流，${dateTime(status.gmgn_cooldown_until)} 后继续` : '单任务串行，直到候选池清空'],
            ['上次采集', dateTime(status?.last_collection_at), latestBatch?.status || '尚未运行'],
            ['下次自动采集', discovery ? dateTime(status?.next_collection_at) : '已关闭', `间隔 ${settings.interval_minutes} 分钟`],
          ].map(([label, value, hint]) => (
            <article key={label}><span>{label}</span><strong>{value}</strong><small>{hint}</small></article>
          ))}
        </div>

        <section className="admin-panel pipeline-panel" hidden={activeSection !== 'overview'}>
          <div className="admin-panel-head">
            <div><h2>数据处理流程</h2><p>地址来自 GMGN Robinhood Smart Money 交易流，经去重、筛选、顺序回测后进入对应地址池。</p></div>
            <span className="source-badge">GMGN SMART MONEY</span>
          </div>
          <div className="pipeline-grid">
            {pipeline.map((item, index) => (
              <article className="pipeline-step" key={item.step}>
                <div><span>{item.step}</span>{index < pipeline.length - 1 && <i>→</i>}</div>
                <strong>{item.value}</strong>
                <h3>{item.title}</h3>
                <p>{item.note}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="admin-panel admin-form-panel" hidden={activeSection !== 'collection'}>
          <div className="admin-panel-head">
            <div><h2>01 · Smart Money 交易流采集</h2><p>按设定间隔读取 GMGN Robinhood Smart Money 交易流；允许遗漏窗口之外的钱包。</p></div>
            <span className="source-badge">固定数据源</span>
          </div>
          <div className="admin-settings-grid collection-settings-grid">
            <div className="setting-readout"><span>候选地址来源</span><strong>GMGN Robinhood Smart Money 交易流</strong><small>固定，不可切换</small></div>
            <div className="setting-readout"><span>单次活动窗口</span><strong>最多 100 条</strong><small>GMGN 接口限制，无分页</small></div>
            <label>自动采集间隔（分钟）<input type="number" min="5" max="43200" value={settings.interval_minutes} onChange={(event) => setSettings({ ...settings, interval_minutes: Number(event.target.value) })} /></label>
            <div className="setting-readout"><span>自动采集状态</span><strong>{discovery ? '已开启' : '已关闭'}</strong><small>由上方开关控制</small></div>
            <div className="setting-readout"><span>下次自动采集</span><strong>{discovery ? dateTime(status?.next_collection_at) : '—'}</strong><small>手动采集不受开关影响</small></div>
          </div>
        </section>

        <section className="admin-panel admin-form-panel" hidden={activeSection !== 'collection'}>
          <div className="admin-panel-head">
            <div><h2>02 · 候选整理与筛选</h2><p>发现的钱包都会去重保存；下面的条件只决定哪些地址有资格进入计算队列。</p></div>
          </div>
          <div className="admin-settings-grid candidate-settings-grid">
            <label>PnL统计周期<select value={settings.period} onChange={(event) => setSettings({ ...settings, period: event.target.value })}><option value="1d">1D</option><option value="7d">7D</option><option value="30d">30D</option></select></label>
            <label>候选池排名数量<input type="number" min="1" max="2000" value={settings.limit} onChange={(event) => setSettings({ ...settings, limit: Number(event.target.value) })} /></label>
            <label>排序字段<select value={settings.sort_by} onChange={(event) => setSettings({ ...settings, sort_by: event.target.value })}><option value="realized_profit">已实现盈利</option><option value="total_profit">总盈利</option><option value="pnl">已实现收益率</option><option value="total_cost">交易成本</option><option value="buy">买入次数</option><option value="sell">卖出次数</option></select></label>
            <label>排序方向<select value={settings.direction} onChange={(event) => setSettings({ ...settings, direction: event.target.value })}><option value="desc">从高到低</option><option value="asc">从低到高</option></select></label>
            <label>最低已实现盈利（USD）<input type="number" value={settings.filters.min_realized_profit ?? ''} placeholder="0" onChange={(event) => setSettings({ ...settings, filters: { ...settings.filters, min_realized_profit: event.target.value === '' ? undefined : Number(event.target.value) } })} /></label>
            <label>最低交易成本（USD）<input type="number" value={settings.filters.min_total_cost ?? ''} placeholder="1000" onChange={(event) => setSettings({ ...settings, filters: { ...settings.filters, min_total_cost: event.target.value === '' ? undefined : Number(event.target.value) } })} /></label>
          </div>
          <div className="settings-actions">
            <button className="secondary-btn" disabled={settingsBusy || !connected} onClick={() => saveDiscoverySettings(false)}>{settingsBusy ? '保存中…' : '保存采集设置'}</button>
            <button className="primary-btn" disabled={settingsBusy || collectionSubmitting || !connected} onClick={() => saveDiscoverySettings(true)}>{collectionSubmitting ? '正在提交…' : '保存并立即采集'}</button>
          </div>
        </section>

        <section className="admin-panel admin-form-panel" hidden={activeSection !== 'settings'}>
          <div className="admin-panel-head">
            <div><h2>03 · 地址计算策略</h2><p>只计算新增、达到重算时间或手动指定的钱包；同一地址不会重复排队。</p></div>
          </div>
          <div className="admin-settings-grid analysis-settings-grid">
            <label className="admin-check"><input type="checkbox" checked={settings.auto_analyze} onChange={(event) => setSettings({ ...settings, auto_analyze: event.target.checked })} />持续计算候选池（包含定时采集）</label>
            <div className="setting-readout"><span>持续计算模式</span><strong>单任务串行</strong><small>一个完成后自动接下一个；GMGN 限流则等待 1 小时</small></div>
            <label>地址计算并发<input type="number" min="1" max="2" value={settings.analysis_concurrency} onChange={(event) => setSettings({ ...settings, analysis_concurrency: Number(event.target.value) })} /></label>
            <label>正式入库分数（严格大于）<input type="number" min="0" max="100" value={settings.score_threshold} onChange={(event) => setSettings({ ...settings, score_threshold: Number(event.target.value) })} /></label>
            <label>正式地址重算间隔（天）<input type="number" min="1" max="365" value={settings.reanalysis_interval_days} onChange={(event) => setSettings({ ...settings, reanalysis_interval_days: Number(event.target.value) })} /></label>
          </div>
          <div className="settings-actions">
            <div className="analysis-switch-label"><span className={`status-dot ${analysis ? '' : 'paused'}`} /><span>地址分析队列{analysis ? '已开启' : '已暂停'}</span></div>
            <button disabled={!connected || busy} className={analysis ? 'switch on' : 'switch'} onClick={() => toggle('analysis', !analysis)} aria-label="切换地址分析"><span /></button>
            <button className="primary-btn" disabled={settingsBusy || !connected} onClick={() => saveDiscoverySettings(false)}>{settingsBusy ? '保存中…' : '保存计算设置'}</button>
          </div>
        </section>

        <section className="admin-panel" hidden={activeSection !== 'wallets' || walletTab !== 'pending'}>
          <div className="admin-panel-head">
            <div><h2>GMGN 未评分候选池</h2><p>这里只显示尚未产生 Robin Score 的地址；逐个计算时，前一个结束后才启动下一个。</p></div>
            <div className="admin-panel-actions">
              <span>{candidateTotal} 个</span>
              <button className="primary-btn" disabled={busy || !connected || !analysis || candidateTotal === 0} onClick={analyzeAllCandidates}>逐个计算全部</button>
            </div>
          </div>
          <div className="detail-table-wrap">
            <table className="admin-table candidate-table">
              <thead><tr>
                <SortHeader sortBy="source_rank" query={candidateQuery} onSort={(key) => changeCandidateQuery(nextSort(candidateQuery, key))}>排名 / 钱包</SortHeader>
                <SortHeader sortBy="labels" query={candidateQuery} onSort={(key) => changeCandidateQuery(nextSort(candidateQuery, key))}>标签</SortHeader>
                <SortHeader sortBy="realized_profit" query={candidateQuery} onSort={(key) => changeCandidateQuery(nextSort(candidateQuery, key))}>周期盈利</SortHeader>
                <SortHeader sortBy="total_profit" query={candidateQuery} onSort={(key) => changeCandidateQuery(nextSort(candidateQuery, key))}>总盈利</SortHeader>
                <SortHeader sortBy="buy" query={candidateQuery} onSort={(key) => changeCandidateQuery(nextSort(candidateQuery, key))}>买入 / 卖出</SortHeader>
                <SortHeader sortBy="status" query={candidateQuery} onSort={(key) => changeCandidateQuery(nextSort(candidateQuery, key))}>分析状态</SortHeader>
                <SortHeader sortBy="last_seen_at" query={candidateQuery} onSort={(key) => changeCandidateQuery(nextSort(candidateQuery, key))}>最后发现</SortHeader>
                <th>操作</th>
              </tr></thead>
              <tbody>
                {candidates.length ? candidates.map((candidate) => {
                  const metric = candidate.discovery_metrics || {};
                  return (
                    <tr key={candidate.address}>
                      <td><strong>#{candidate.source_rank ?? '—'}</strong><span className="table-wallet">{candidate.name || shortAddress(candidate.address)}</span></td>
                      <td><div className="mini-tags">{candidate.labels.slice(0, 3).map((label) => <span key={label}>{label}</span>)}</div></td>
                      <td className={number(metric.realized_profit) >= 0 ? 'positive' : 'negative'}>{money(metric.realized_profit)}</td>
                      <td className={number(metric.total_profit) >= 0 ? 'positive' : 'negative'}>{money(metric.total_profit)}</td>
                      <td>{metric.buy == null ? '—' : `${metric.buy} / ${metric.sell ?? 0}`}</td>
                      <td><span className={`admin-status ${statusTone(candidate.status)}`}>{candidate.status}</span>{candidate.last_error && <small className="row-error">{candidate.last_error}</small>}</td>
                      <td>{dateTime(candidate.last_seen_at)}</td>
                      <td><button className="table-action" disabled={busy || !connected || !analysis} onClick={() => action('/api/v1/admin/analyze', { address: candidate.address, trigger: 'candidate_manual', force_refresh: false }, 'POST', '该候选地址已加入分析队列。')}>计算</button></td>
                    </tr>
                  );
                }) : <tr><td colSpan={8} className="empty-state">当前没有等待首次评分的候选地址。</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination page={candidateQuery.page} total={candidateTotal} onPage={(page) => changeCandidateQuery({ ...candidateQuery, page })} />
        </section>

        <section className="admin-panel" hidden={activeSection !== 'wallets' || walletTab !== 'unqualified'}>
          <div className="admin-panel-head">
            <div><h2>不合格地址池</h2><p>已完成计算但 Robin Score ≤ {settings.score_threshold}，不会进入前台正式地址列表。</p></div>
            <span>{unqualifiedTotal} 个</span>
          </div>
          <div className="detail-table-wrap">
            <table className="admin-table candidate-table">
              <thead><tr>
                <SortHeader sortBy="source_rank" query={unqualifiedQuery} onSort={(key) => changeUnqualifiedQuery(nextSort(unqualifiedQuery, key))}>排名 / 钱包</SortHeader>
                <SortHeader sortBy="labels" query={unqualifiedQuery} onSort={(key) => changeUnqualifiedQuery(nextSort(unqualifiedQuery, key))}>标签</SortHeader>
                <SortHeader sortBy="realized_profit" query={unqualifiedQuery} onSort={(key) => changeUnqualifiedQuery(nextSort(unqualifiedQuery, key))}>周期盈利</SortHeader>
                <SortHeader sortBy="total_profit" query={unqualifiedQuery} onSort={(key) => changeUnqualifiedQuery(nextSort(unqualifiedQuery, key))}>总盈利</SortHeader>
                <SortHeader sortBy="status" query={unqualifiedQuery} onSort={(key) => changeUnqualifiedQuery(nextSort(unqualifiedQuery, key))}>状态</SortHeader>
                <SortHeader sortBy="last_score" query={unqualifiedQuery} onSort={(key) => changeUnqualifiedQuery(nextSort(unqualifiedQuery, key))}>评分</SortHeader>
                <SortHeader sortBy="last_analyzed_at" query={unqualifiedQuery} onSort={(key) => changeUnqualifiedQuery(nextSort(unqualifiedQuery, key))}>最后计算</SortHeader>
                <th>操作</th>
              </tr></thead>
              <tbody>
                {unqualified.length ? unqualified.map((candidate) => {
                  const metric = candidate.discovery_metrics || {};
                  return (
                    <tr key={candidate.address}>
                      <td><strong>#{candidate.source_rank ?? '—'}</strong><span className="table-wallet">{candidate.name || shortAddress(candidate.address)}</span></td>
                      <td><div className="mini-tags">{candidate.labels.slice(0, 3).map((label) => <span key={label}>{label}</span>)}</div></td>
                      <td className={number(metric.realized_profit) >= 0 ? 'positive' : 'negative'}>{money(metric.realized_profit)}</td>
                      <td className={number(metric.total_profit) >= 0 ? 'positive' : 'negative'}>{money(metric.total_profit)}</td>
                      <td><span className={`admin-status ${statusTone(candidate.status)}`}>{candidate.status}</span></td>
                      <td>{candidate.last_score ?? '—'}</td>
                      <td>{dateTime(candidate.last_analyzed_at)}</td>
                      <td><button className="table-action" disabled={busy || !connected || !analysis} onClick={() => action('/api/v1/admin/analyze', { address: candidate.address, trigger: 'unqualified_manual', force_refresh: false }, 'POST', '该不合格地址已加入重新计算队列。')}>重新计算</button></td>
                    </tr>
                  );
                }) : <tr><td colSpan={8} className="empty-state">当前没有评分未达标的地址。</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination page={unqualifiedQuery.page} total={unqualifiedTotal} onPage={(page) => changeUnqualifiedQuery({ ...unqualifiedQuery, page })} />
        </section>

        <section className="admin-panel" hidden={activeSection !== 'wallets' || walletTab !== 'published'}>
          <div className="admin-panel-head">
            <div><h2>正式地址库</h2><p>Robin Score &gt; {settings.score_threshold} 且当前已发布的聪明钱地址，会同步展示在前台网站。</p></div>
            <div className="admin-panel-actions">
              <button className="primary-btn" disabled={recomputeSubmitting || !connected || !analysis || publishedTotal === 0} onClick={recomputePublished}>{recomputeSubmitting ? '正在启动…' : '立即重算'}</button>
              <span>{publishedTotal} 个</span>
            </div>
          </div>
          <div className="detail-table-wrap">
            <table className="admin-table">
              <thead><tr>
                <SortHeader sortBy="wallet" query={publishedQuery} onSort={(key) => changePublishedQuery(nextSort(publishedQuery, key))}>钱包</SortHeader>
                <SortHeader sortBy="labels" query={publishedQuery} onSort={(key) => changePublishedQuery(nextSort(publishedQuery, key))}>标签</SortHeader>
                <SortHeader sortBy="score" query={publishedQuery} onSort={(key) => changePublishedQuery(nextSort(publishedQuery, key))}>评分</SortHeader>
                <SortHeader sortBy="actual_pnl" query={publishedQuery} onSort={(key) => changePublishedQuery(nextSort(publishedQuery, key))}>实际 PnL</SortHeader>
                <SortHeader sortBy="copy_pnl" query={publishedQuery} onSort={(key) => changePublishedQuery(nextSort(publishedQuery, key))}>跟单 PnL</SortHeader>
                <SortHeader sortBy="win_rate" query={publishedQuery} onSort={(key) => changePublishedQuery(nextSort(publishedQuery, key))}>胜率</SortHeader>
                <SortHeader sortBy="tokens_traded" query={publishedQuery} onSort={(key) => changePublishedQuery(nextSort(publishedQuery, key))}>代币数</SortHeader>
                <SortHeader sortBy="analyzed_at" query={publishedQuery} onSort={(key) => changePublishedQuery(nextSort(publishedQuery, key))}>最后计算</SortHeader>
                <th>操作</th>
              </tr></thead>
              <tbody>
                {publishedWallets.length ? publishedWallets.map((item) => (
                  <tr key={item.address}>
                    <td><span className="table-wallet">{item.display_name || shortAddress(item.address)}</span><small className="table-subline">{shortAddress(item.address)}</small></td>
                    <td><div className="mini-tags">{item.labels.slice(0, 3).map((label) => <span key={label}>{label}</span>)}</div></td>
                    <td><strong>{item.score}</strong></td>
                    <td className={item.actual_pnl >= 0 ? 'positive' : 'negative'}>{money(item.actual_pnl)}</td>
                    <td className={item.copy_pnl >= 0 ? 'positive' : 'negative'}>{money(item.copy_pnl)}</td>
                    <td>{item.win_rate.toFixed(1)}%</td>
                    <td>{item.tokens_traded}</td>
                    <td>{dateTime(item.analyzed_at)}</td>
                    <td><Link className="table-action" href={`/wallet/${item.address}`}>详情</Link></td>
                  </tr>
                )) : <tr><td colSpan={9} className="empty-state">当前没有达到正式入库分数的地址。</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination page={publishedQuery.page} total={publishedTotal} onPage={(page) => changePublishedQuery({ ...publishedQuery, page })} />
        </section>

        <section className="admin-panel" hidden={activeSection !== 'collection'}>
          <div className="admin-panel-head"><div><h2>抓取与排名记录</h2><p>每次任务的活动数量、唯一钱包、候选池、排名数量和失败原因。</p></div><span>{batchTotal} 条</span></div>
          <div className="detail-table-wrap">
            <table className="admin-table">
              <thead><tr>
                <SortHeader sortBy="started_at" query={batchQuery} onSort={(key) => changeBatchQuery(nextSort(batchQuery, key))}>开始时间</SortHeader>
                <SortHeader sortBy="trigger" query={batchQuery} onSort={(key) => changeBatchQuery(nextSort(batchQuery, key))}>触发方式</SortHeader>
                <SortHeader sortBy="status" query={batchQuery} onSort={(key) => changeBatchQuery(nextSort(batchQuery, key))}>状态</SortHeader>
                <SortHeader sortBy="activity" query={batchQuery} onSort={(key) => changeBatchQuery(nextSort(batchQuery, key))}>活动 / 钱包</SortHeader>
                <SortHeader sortBy="candidate_pool" query={batchQuery} onSort={(key) => changeBatchQuery(nextSort(batchQuery, key))}>候选池</SortHeader>
                <SortHeader sortBy="requested_count" query={batchQuery} onSort={(key) => changeBatchQuery(nextSort(batchQuery, key))}>目标 / 排名</SortHeader>
                <SortHeader sortBy="new_count" query={batchQuery} onSort={(key) => changeBatchQuery(nextSort(batchQuery, key))}>新增 / 重复</SortHeader>
                <SortHeader sortBy="eligible_count" query={batchQuery} onSort={(key) => changeBatchQuery(nextSort(batchQuery, key))}>合格 / 入队</SortHeader>
                <SortHeader sortBy="error" query={batchQuery} onSort={(key) => changeBatchQuery(nextSort(batchQuery, key))}>错误</SortHeader>
              </tr></thead>
              <tbody>
                {batches.length ? batches.map((batch) => (
                  <tr key={batch.id}>
                    <td>{new Date(batch.started_at).toLocaleString()}</td>
                    <td>{batch.config.trigger === 'scheduled' ? '定时' : '手动'}</td>
                    <td><span className={`admin-status ${statusTone(batch.status)}`}>{batch.status}</span></td>
                    <td>{String(batch.config.feed_trade_count ?? '—')} / {String(batch.config.feed_unique_wallets ?? '—')}</td>
                    <td>{String(batch.config.candidate_pool_size ?? '—')}</td>
                    <td>{batch.requested_count} / {batch.received_count}</td>
                    <td>{batch.new_count} / {batch.duplicate_count}</td>
                    <td>{String(batch.config.eligible_count ?? '—')} / {batch.queued_count}</td>
                    <td>{batch.error || '—'}</td>
                  </tr>
                )) : <tr><td colSpan={9} className="empty-state">暂无抓取记录。</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination page={batchQuery.page} total={batchTotal} onPage={(page) => changeBatchQuery({ ...batchQuery, page })} />
        </section>

        <section className="analysis-batch-hero" hidden={activeSection !== 'tasks'}>
          <div className="analysis-batch-heading">
            <div>
              <span>当前逐个计算批次</span>
              <strong>{latestAnalysisBatch ? `${latestAnalysisBatch.processed_count} / ${latestAnalysisBatch.total_count}` : '暂无批次'}</strong>
            </div>
            {latestAnalysisBatch && <span className={`admin-status ${statusTone(latestAnalysisBatch.status)}`}>{latestAnalysisBatch.status}</span>}
          </div>
          <div className="analysis-progress"><i style={{ width: `${latestAnalysisBatch?.progress_percent ?? 0}%` }} /></div>
          <div className="analysis-batch-meta">
            <span>成功 <b>{latestAnalysisBatch?.completed_count ?? 0}</b></span>
            <span>失败 <b>{latestAnalysisBatch?.failed_count ?? 0}</b></span>
            <span>跳过 <b>{latestAnalysisBatch?.skipped_count ?? 0}</b></span>
            <span>当前地址 <b>{latestAnalysisBatch?.current_address ? shortAddress(latestAnalysisBatch.current_address) : '—'}</b></span>
          </div>
        </section>

        <section className="admin-panel" hidden={activeSection !== 'tasks'}>
          <div className="admin-panel-head"><div><h2>逐个计算批次</h2><p>“计算全部”创建一个串行批次，每个地址完成后才开始下一个。</p></div><span>{analysisBatchTotal} 条</span></div>
          <div className="detail-table-wrap">
            <table className="admin-table">
              <thead><tr>
                <SortHeader sortBy="created_at" query={analysisBatchQuery} onSort={(key) => changeAnalysisBatchQuery(nextSort(analysisBatchQuery, key))}>创建时间</SortHeader>
                <SortHeader sortBy="status" query={analysisBatchQuery} onSort={(key) => changeAnalysisBatchQuery(nextSort(analysisBatchQuery, key))}>状态</SortHeader>
                <SortHeader sortBy="total_count" query={analysisBatchQuery} onSort={(key) => changeAnalysisBatchQuery(nextSort(analysisBatchQuery, key))}>总数</SortHeader>
                <SortHeader sortBy="completed_count" query={analysisBatchQuery} onSort={(key) => changeAnalysisBatchQuery(nextSort(analysisBatchQuery, key))}>成功</SortHeader>
                <SortHeader sortBy="failed_count" query={analysisBatchQuery} onSort={(key) => changeAnalysisBatchQuery(nextSort(analysisBatchQuery, key))}>失败</SortHeader>
                <th>跳过</th><th>当前地址</th><th>进度</th>
              </tr></thead>
              <tbody>
                {analysisBatches.length ? analysisBatches.map((batch) => (
                  <tr key={batch.id}>
                    <td>{dateTime(batch.created_at)}</td>
                    <td><span className={`admin-status ${statusTone(batch.status)}`}>{batch.status}</span></td>
                    <td>{batch.total_count}</td><td>{batch.completed_count}</td><td>{batch.failed_count}</td><td>{batch.skipped_count}</td>
                    <td>{batch.current_address ? shortAddress(batch.current_address) : '—'}</td><td>{batch.progress_percent.toFixed(1)}%</td>
                  </tr>
                )) : <tr><td colSpan={8} className="empty-state">暂无逐个计算批次。</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination page={analysisBatchQuery.page} total={analysisBatchTotal} onPage={(page) => changeAnalysisBatchQuery({ ...analysisBatchQuery, page })} />
        </section>

        <section className="admin-panel admin-form-panel" hidden={activeSection !== 'tasks'}>
          <div className="admin-panel-head"><div><h2>手动计算地址</h2><p>直接加入计算队列；评分严格大于 {settings.score_threshold} 才会进入正式地址库。</p></div></div>
          <div className="admin-inline-form">
            <input value={wallet} onChange={(event) => setWallet(event.target.value)} placeholder="0x 钱包地址" />
            <button className="primary-btn" disabled={busy || !connected || !analysis || !/^0x[a-fA-F0-9]{40}$/.test(wallet)} onClick={() => action('/api/v1/admin/analyze', { address: wallet, trigger: 'manual', force_refresh: false }, 'POST', '地址已加入分析队列。')}>加入计算队列</button>
            <button className="secondary-btn" disabled={recomputeSubmitting || !connected || !analysis || publishedTotal === 0} onClick={recomputePublished}>{recomputeSubmitting ? '正在启动…' : '重算全部正式地址'}</button>
          </div>
        </section>

        <section className="admin-panel" hidden={activeSection !== 'tasks'}>
          <div className="admin-panel-head"><div><h2>地址分析队列</h2><p>任务提交时立即显示排队状态；失败任务不会覆盖上一次成功结果。</p></div><div className="admin-panel-actions"><span>{runTotal} 条</span><button className="secondary-btn" onClick={refresh}>刷新</button></div></div>
          <div className="detail-table-wrap">
            <table className="admin-table">
              <thead><tr>
                <SortHeader sortBy="created_at" query={runQuery} onSort={(key) => changeRunQuery(nextSort(runQuery, key))}>提交时间</SortHeader>
                <SortHeader sortBy="address" query={runQuery} onSort={(key) => changeRunQuery(nextSort(runQuery, key))}>地址</SortHeader>
                <SortHeader sortBy="trigger" query={runQuery} onSort={(key) => changeRunQuery(nextSort(runQuery, key))}>触发方式</SortHeader>
                <SortHeader sortBy="status" query={runQuery} onSort={(key) => changeRunQuery(nextSort(runQuery, key))}>状态</SortHeader>
                <SortHeader sortBy="input_trade_count" query={runQuery} onSort={(key) => changeRunQuery(nextSort(runQuery, key))}>交易数</SortHeader>
                <SortHeader sortBy="score" query={runQuery} onSort={(key) => changeRunQuery(nextSort(runQuery, key))}>评分</SortHeader>
                <SortHeader sortBy="published" query={runQuery} onSort={(key) => changeRunQuery(nextSort(runQuery, key))}>结果</SortHeader>
              </tr></thead>
              <tbody>
                {runs.length ? runs.map((run) => (
                  <tr key={run.id}>
                    <td>{dateTime(run.created_at)}</td><td>{shortAddress(run.address)}</td><td>{run.trigger}</td>
                    <td><span className={`admin-status ${statusTone(run.status)}`}>{run.status}</span></td>
                    <td>{run.input_trade_count ?? '—'}</td><td>{run.score ?? '—'}</td>
                    <td>{run.error || (run.published ? '已入库' : run.status === 'completed' ? '未达到入库分数' : '—')}</td>
                  </tr>
                )) : <tr><td colSpan={7} className="empty-state">连接后台后显示真实任务记录。</td></tr>}
              </tbody>
            </table>
          </div>
          <Pagination page={runQuery.page} total={runTotal} onPage={(page) => changeRunQuery({ ...runQuery, page })} />
        </section>
      </section>
    </main>
  );
}

export default function AdminPage() {
  return <AdminDashboard section="overview" />;
}
