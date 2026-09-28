'use client';

import { useEffect, useState } from 'react';
import { useRouter } from 'next/navigation';
import type { WalletAnalysisStatus } from '../../../lib/robincop-api';

const publicApiUrl = (process.env.NEXT_PUBLIC_API_URL || 'https://robincop.com/robincop-api').replace(/\/$/, '');
const POLL_INTERVAL_MS = 2_000;

type Phase = 'queued' | 'running' | 'failed';

export default function WalletAnalysisPending({
  address,
  initialStatus,
}: {
  address: string;
  initialStatus: WalletAnalysisStatus | null;
}) {
  const router = useRouter();
  const [phase, setPhase] = useState<Phase>(initialStatus?.status === 'running' ? 'running' : 'queued');
  const [message, setMessage] = useState('This wallet is not in the address library yet. Analysis has started automatically.');
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const endpoint = `${publicApiUrl}/api/v1/wallets/${encodeURIComponent(address)}/analysis`;

    const readPayload = async (response: Response): Promise<WalletAnalysisStatus> => {
      const payload = await response.json().catch(() => null) as (WalletAnalysisStatus & { detail?: string }) | null;
      if (!response.ok || !payload) throw new Error(payload?.detail || 'Unable to start wallet analysis.');
      return payload;
    };

    const update = (status: WalletAnalysisStatus) => {
      if (status.status === 'completed') {
        router.refresh();
        return true;
      }
      if (status.status === 'failed' || status.status === 'paused') {
        setPhase('failed');
        setMessage(status.message || (status.status === 'paused'
          ? 'Wallet analysis is currently paused. Please try again later.'
          : 'Wallet analysis failed. Please try again.'));
        return true;
      }
      setPhase(status.status === 'running' ? 'running' : 'queued');
      setMessage(status.status === 'running'
        ? 'Reading this wallet’s activity and calculating its copy-trading results…'
        : 'Analysis is queued and will start automatically.');
      return false;
    };

    const poll = async () => {
      try {
        const status = await readPayload(await fetch(endpoint, {
          headers: { Accept: 'application/json' },
          cache: 'no-store',
          signal: controller.signal,
        }));
        if (!stopped && !update(status)) timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
      } catch (error) {
        if (stopped || controller.signal.aborted) return;
        setPhase('failed');
        setMessage(error instanceof Error ? error.message : 'Unable to check wallet analysis.');
      }
    };

    const start = async () => {
      try {
        const status = await readPayload(await fetch(endpoint, {
          method: 'POST',
          headers: { Accept: 'application/json' },
          cache: 'no-store',
          signal: controller.signal,
        }));
        if (!stopped && !update(status)) timer = setTimeout(() => void poll(), POLL_INTERVAL_MS);
      } catch (error) {
        if (stopped || controller.signal.aborted) return;
        setPhase('failed');
        setMessage(error instanceof Error ? error.message : 'Unable to start wallet analysis.');
      }
    };

    void start();
    return () => {
      stopped = true;
      controller.abort();
      if (timer) clearTimeout(timer);
    };
  }, [address, attempt, router]);

  const title = phase === 'failed' ? 'Analysis unavailable' : phase === 'running' ? 'Analyzing wallet' : 'Preparing analysis';
  return <div className="detail-loading wallet-analysis-pending" role="status" aria-live="polite">
    <section className="wallet-hero detail-loading-hero">
      <div><p className="eyebrow">ON-DEMAND WALLET ANALYSIS</p><h1>{`${address.slice(0, 6)}...${address.slice(-5)}`}</h1><div className="full-address">{address}</div></div>
      <div className="detail-score detail-score-loading"><span>ROBIN SCORE</span><strong>—</strong><small>{phase === 'failed' ? 'UNAVAILABLE' : phase.toUpperCase()}</small></div>
    </section>
    <section className={`detail-panel detail-loading-panel wallet-analysis-message${phase === 'failed' ? ' error' : ''}`}>
      {phase !== 'failed' && <span className="detail-loading-spinner" />}
      <div><strong>{title}</strong><p>{message}</p>{phase === 'failed' && <button type="button" className="load-more-button" onClick={() => { setPhase('queued'); setMessage('Restarting wallet analysis…'); setAttempt((value) => value + 1); }}>Try again</button>}</div>
    </section>
  </div>;
}
