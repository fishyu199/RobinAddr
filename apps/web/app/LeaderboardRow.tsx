'use client';

import type { KeyboardEvent, ReactNode } from 'react';
import { useRouter } from 'next/navigation';

type LeaderboardRowProps = {
  children: ReactNode;
  href: string;
  label: string;
};

function shouldUseCurrentTab() {
  return window.matchMedia('(max-width: 760px)').matches
    || window.matchMedia('(hover: none) and (pointer: coarse)').matches;
}

export default function LeaderboardRow({ children, href, label }: LeaderboardRowProps) {
  const router = useRouter();
  const openDetail = () => {
    if (shouldUseCurrentTab()) {
      router.push(href);
      return;
    }

    window.open(href, '_blank', 'noopener,noreferrer');
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTableRowElement>) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    openDetail();
  };

  return <tr className="clickable-row" role="link" tabIndex={0} aria-label={label} onClick={openDetail} onKeyDown={handleKeyDown}>{children}</tr>;
}
