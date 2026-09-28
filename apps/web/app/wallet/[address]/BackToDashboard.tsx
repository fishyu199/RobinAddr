'use client';

export default function BackToDashboard() {
  const handleBack = () => {
    let hasDashboardHistory = false;

    try {
      const referrer = document.referrer ? new URL(document.referrer) : null;
      hasDashboardHistory = referrer?.origin === window.location.origin;
    } catch {
      hasDashboardHistory = false;
    }

    if (hasDashboardHistory && window.history.length > 1) {
      window.history.back();
      return;
    }

    window.location.assign(new URL('/#leaderboard', window.location.origin).toString());
  };

  return (
    <button type="button" className="back-link" onClick={handleBack} aria-label="Back to wallet list">
      ← Back to wallets
    </button>
  );
}
