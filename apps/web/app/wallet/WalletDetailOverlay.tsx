'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import type { WalletDetail } from '../../lib/robincop-api';
import WalletDetailView from './[address]/WalletDetailView';

type WalletPreview = {
  address: string;
  name: string;
  score: number;
};

type TelegramBackButton = {
  show: () => TelegramBackButton;
  hide: () => TelegramBackButton;
  onClick: (callback: () => void) => TelegramBackButton;
  offClick: (callback: () => void) => TelegramBackButton;
};

const publicApiUrl = (process.env.NEXT_PUBLIC_API_URL || '/robincop-api').replace(/\/$/, '');

export default function WalletDetailOverlay({ preview, onDismiss }: {
  preview: WalletPreview;
  onDismiss: () => void;
}) {
  const [wallet, setWallet] = useState<WalletDetail | null>(null);
  const [isLoadingDetails, setIsLoadingDetails] = useState(true);
  const [error, setError] = useState('');
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const requestVersionRef = useRef(0);

  const close = useCallback(() => {
    if (document.documentElement.dataset.tokenDrawerOpen === 'true') {
      window.dispatchEvent(new Event('robincop:close-token-drawer'));
      return;
    }
    if (window.history.state?.robincopWalletOverlay) {
      window.history.back();
      return;
    }
    onDismiss();
  }, [onDismiss]);

  const loadWallet = useCallback(async () => {
    const version = ++requestVersionRef.current;
    setError('');
    setIsLoadingDetails(true);
    try {
      const summaryResponse = await fetch(
        `${publicApiUrl}/api/v1/wallets/${encodeURIComponent(preview.address)}?compact=true&summary_only=true`,
        { headers: { Accept: 'application/json' } },
      );
      if (!summaryResponse.ok) throw new Error(`Wallet request failed (${summaryResponse.status})`);
      const summary = await summaryResponse.json() as WalletDetail;
      if (requestVersionRef.current !== version) return;
      setWallet({ ...summary, data_source: 'live' });

      const detailsResponse = await fetch(
        `${publicApiUrl}/api/v1/wallets/${encodeURIComponent(preview.address)}?compact=true`,
        { headers: { Accept: 'application/json' } },
      );
      if (!detailsResponse.ok) throw new Error(`Wallet details failed (${detailsResponse.status})`);
      const details = await detailsResponse.json() as WalletDetail;
      if (requestVersionRef.current !== version) return;
      setWallet({ ...details, data_source: 'live' });
      setIsLoadingDetails(false);
    } catch {
      if (requestVersionRef.current !== version) return;
      setError('Wallet details could not be loaded.');
      setIsLoadingDetails(false);
    }
  }, [preview.address]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    closeButtonRef.current?.focus();
    void loadWallet();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      close();
    };
    const handlePopState = () => {
      if (document.documentElement.dataset.tokenDrawerOpen === 'true') {
        window.dispatchEvent(new Event('robincop:close-token-drawer'));
        return;
      }
      onDismiss();
    };
    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('popstate', handlePopState);

    const backButton = (window.Telegram?.WebApp?.BackButton as TelegramBackButton | undefined);
    backButton?.onClick(close);
    backButton?.show();

    return () => {
      requestVersionRef.current += 1;
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('popstate', handlePopState);
      backButton?.offClick(close);
      backButton?.hide();
    };
  }, [close, loadWallet, onDismiss]);

  return (
    <div className="wallet-detail-overlay" role="dialog" aria-modal="true" aria-label={`Wallet details for ${preview.name}`}>
      <header className="wallet-detail-overlay-nav">
        <button ref={closeButtonRef} type="button" className="wallet-detail-overlay-back" onClick={close}>
          <span aria-hidden="true">←</span> Back to wallets
        </button>
        <span className="wallet-detail-overlay-address">{preview.address.slice(0, 7)}…{preview.address.slice(-5)}</span>
      </header>
      <div className="wallet-detail-overlay-scroll">
        <main className="detail-shell wallet-detail-overlay-content">
          {wallet ? <WalletDetailView address={preview.address} wallet={wallet} /> : (
            <div className="detail-loading" role="status" aria-live="polite">
              <section className="wallet-hero detail-loading-hero">
                <div><h1>{preview.name}</h1><div className="full-address">{preview.address}</div></div>
                <div className="detail-score"><span>ROBIN SCORE</span><strong>{preview.score}</strong><small>LOADING</small></div>
              </section>
              <section className="detail-loading-grid" aria-hidden="true">{Array.from({ length: 6 }, (_, index) => <i key={index} />)}</section>
              <section className="detail-panel detail-loading-panel"><span className="detail-loading-spinner" />Loading wallet analysis…</section>
            </div>
          )}
          {wallet && isLoadingDetails && <div className="wallet-detail-overlay-progress" role="status"><span className="detail-loading-spinner" />Loading positions and trade history…</div>}
          {error && <div className="wallet-detail-overlay-error" role="alert"><span>{error}</span><button type="button" onClick={() => void loadWallet()}>Retry</button><a href={`/wallet/${preview.address}`}>Open full page</a></div>}
        </main>
      </div>
    </div>
  );
}
