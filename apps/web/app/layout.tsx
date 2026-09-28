import type { Metadata, Viewport } from 'next';
import { Geist, Geist_Mono } from 'next/font/google';
import Script from 'next/script';
import TelegramMiniApp from './TelegramMiniApp';
import './globals.css';

const siteUrl = process.env.NEXT_PUBLIC_SITE_URL || 'https://robincop-intelligence.bigfishgooo.chatgpt.site';

const geistSans = Geist({
  variable: '--font-geist-sans',
  subsets: ['latin'],
});

const geistMono = Geist_Mono({
  variable: '--font-geist-mono',
  subsets: ['latin'],
});

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: 'RobinCop — Robinhood Copy Intelligence',
  description: 'Verified Robinhood Chain smart-money wallets, replayed with realistic copy-trading slippage.',
  icons: {
    icon: [
      { url: '/favicon.ico?v=20260923b', type: 'image/x-icon', sizes: '32x32' },
      { url: '/favicon.png?v=20260923b', type: 'image/png', sizes: '128x128' },
    ],
    shortcut: '/favicon.ico?v=20260923b',
    apple: '/robincop-logo.png?v=20260923b',
  },
  openGraph: {
    title: 'RobinCop — Robinhood Copy Intelligence',
    description: 'Verified Robinhood Chain smart-money wallets, replayed with realistic copy-trading slippage.',
    type: 'website',
    url: '/',
    images: [{ url: '/og.png', width: 1200, height: 630, alt: 'RobinCop leaderboard preview' }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'RobinCop — Robinhood Copy Intelligence',
    description: 'Find Robinhood Chain smart-money wallets that remain profitable after copy-trading slippage.',
    images: ['/og.png'],
  },
};

export const viewport: Viewport = {
  width: 'device-width',
  initialScale: 1,
  viewportFit: 'cover',
  themeColor: '#000000',
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <head>
        <Script src="https://telegram.org/js/telegram-web-app.js?63" strategy="beforeInteractive" />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        <TelegramMiniApp />
        {children}
      </body>
    </html>
  );
}
