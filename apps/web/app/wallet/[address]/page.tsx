import type { Metadata } from 'next';
import Image from 'next/image';
import Link from 'next/link';
import { notFound } from 'next/navigation';
import { Suspense } from 'react';
import { getWallet, startWalletAnalysis } from '../../../lib/robincop-api';
import BackToDashboard from './BackToDashboard';
import WalletAnalysisPending from './WalletAnalysisPending';
import WalletDetailView from './WalletDetailView';

export const revalidate = 30;

export async function generateMetadata({ params }: { params: Promise<{ address: string }> }): Promise<Metadata> {
  const { address } = await params;
  const title = `${address.slice(0, 6)}...${address.slice(-5)}`;
  return {
    title: `${title} — RobinCop Wallet Analysis`,
    description: `Copy-trading backtest and wallet metrics for ${address} on Robinhood Chain.`,
    icons: {
      icon: [
        { url: '/favicon.ico?v=20260923b', type: 'image/x-icon', sizes: '32x32' },
        { url: '/favicon.png?v=20260923b', type: 'image/png', sizes: '128x128' },
      ],
      shortcut: '/favicon.ico?v=20260923b',
      apple: '/robincop-logo.png?v=20260923b',
    },
    openGraph: { images: [] },
    twitter: { images: [] },
  };
}

export default async function WalletDetail({ params }: { params: Promise<{ address: string }> }) {
  const { address } = await params;
  return (
    <main className="detail-shell">
      <header className="detail-nav"><Link href="/" className="brand"><Image className="brand-logo" src="/robincop-logo.png" width={36} height={36} alt="" /><span><strong>RobinCop</strong><small>Copy-trade wallets on Robinhood Chain</small></span></Link><BackToDashboard /></header>
      <Suspense fallback={<WalletDetailLoading address={address} />}>
        <WalletDetailContent address={address} />
      </Suspense>
    </main>
  );
}

function WalletDetailLoading({ address }: { address: string }) {
  return <div className="detail-loading" role="status" aria-live="polite">
    <section className="wallet-hero detail-loading-hero">
      <div><h1>{`${address.slice(0, 6)}...${address.slice(-5)}`}</h1><div className="full-address">{address}</div></div>
      <div className="detail-score detail-score-loading"><span>ROBIN SCORE</span><strong>—</strong><small>LOADING</small></div>
    </section>
    <section className="detail-loading-grid" aria-hidden="true">{Array.from({ length: 6 }, (_, index) => <i key={index} />)}</section>
    <section className="detail-panel detail-loading-panel"><span className="detail-loading-spinner" />Loading wallet analysis…</section>
  </div>;
}

async function WalletDetailContent({ address }: { address: string }) {
  if (!/^0x[a-fA-F0-9]{40}$/.test(address)) notFound();
  const wallet = await getWallet(address);
  if (!wallet) {
    const analysis = await startWalletAnalysis(address);
    return <WalletAnalysisPending address={address.toLowerCase()} initialStatus={analysis} />;
  }

  return <WalletDetailView address={address} wallet={wallet} />;
}
