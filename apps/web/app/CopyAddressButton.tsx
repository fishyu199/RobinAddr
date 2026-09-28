'use client';

import { useState, type KeyboardEvent, type MouseEvent } from 'react';

async function writeToClipboard(value: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }

  const input = document.createElement('textarea');
  input.value = value;
  input.setAttribute('readonly', '');
  input.style.position = 'fixed';
  input.style.opacity = '0';
  document.body.appendChild(input);
  input.select();
  const copied = document.execCommand('copy');
  input.remove();
  if (!copied) throw new Error('Copy failed');
}

export default function CopyAddressButton({ address }: { address: string }) {
  const [copied, setCopied] = useState(false);

  const handleClick = async (event: MouseEvent<HTMLButtonElement>) => {
    event.stopPropagation();
    try {
      await writeToClipboard(address);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };

  const stopRowKeyboardAction = (event: KeyboardEvent<HTMLButtonElement>) => {
    event.stopPropagation();
  };

  return <button className={`copy-address-button${copied ? ' copied' : ''}`} type="button" onClick={handleClick} onKeyDown={stopRowKeyboardAction} aria-label={copied ? `Address copied: ${address}` : `Copy wallet address ${address}`} aria-live="polite" title={copied ? 'Address copied' : 'Copy address'}><span aria-hidden="true">{copied ? '✓' : '⧉'}</span></button>;
}
