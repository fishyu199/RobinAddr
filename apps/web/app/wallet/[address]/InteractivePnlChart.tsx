'use client';

import { useMemo, useState, type KeyboardEvent, type PointerEvent } from 'react';

export type PnlPoint = {
  timestampMs: number;
  targetPnl: number;
  copyPnl: number;
};

const WIDTH = 900;
const HEIGHT = 240;
const X_PADDING = 12;
const Y_PADDING = 14;

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value));
}

function money(value: number) {
  const sign = value >= 0 ? '+' : '-';
  return `${sign}$${Math.abs(value).toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
}

function utcTime(timestampMs: number) {
  return `${new Date(timestampMs).toISOString().replace('T', ' ').slice(0, 19)} UTC`;
}

export default function InteractivePnlChart({ points }: { points: PnlPoint[] }) {
  const [activeIndex, setActiveIndex] = useState<number | null>(null);
  const chart = useMemo(() => {
    const firstTime = points[0]?.timestampMs ?? 0;
    const lastTime = points.at(-1)?.timestampMs ?? firstTime + 1;
    const timeRange = lastTime - firstTime || 1;
    const allValues = points.flatMap((point) => [point.targetPnl, point.copyPnl]);
    const rawMin = Math.min(0, ...allValues);
    const rawMax = Math.max(0, ...allValues);
    const spread = rawMax - rawMin || Math.max(Math.abs(rawMax), 1);
    const min = rawMin - spread * 0.06;
    const max = rawMax + spread * 0.06;
    const valueRange = max - min || 1;
    const x = (timestampMs: number) => X_PADDING + ((timestampMs - firstTime) / timeRange) * (WIDTH - X_PADDING * 2);
    const y = (value: number) => Y_PADDING + ((max - value) / valueRange) * (HEIGHT - Y_PADDING * 2);
    const coordinates = points.map((point) => ({
      ...point,
      x: x(point.timestampMs),
      targetY: y(point.targetPnl),
      copyY: y(point.copyPnl),
    }));
    return {
      coordinates,
      targetPath: coordinates.map((point) => `${point.x},${point.targetY}`).join(' '),
      copyPath: coordinates.map((point) => `${point.x},${point.copyY}`).join(' '),
      zeroY: rawMin < 0 && rawMax > 0 ? y(0) : null,
      firstTime,
      lastTime,
    };
  }, [points]);

  const selectFromPointer = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const pointerX = clamp(event.clientX - rect.left, 0, rect.width);
    const viewX = (pointerX / Math.max(rect.width, 1)) * WIDTH;
    let closest = 0;
    let distance = Number.POSITIVE_INFINITY;
    chart.coordinates.forEach((point, index) => {
      const nextDistance = Math.abs(point.x - viewX);
      if (nextDistance < distance) {
        closest = index;
        distance = nextDistance;
      }
    });
    setActiveIndex(closest);
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    setActiveIndex((current) => {
      const start = current ?? points.length - 1;
      return clamp(start + (event.key === 'ArrowRight' ? 1 : -1), 0, points.length - 1);
    });
  };

  const active = activeIndex === null ? null : chart.coordinates[activeIndex];

  return (
    <div
      className="interactive-chart"
      tabIndex={0}
      role="img"
      aria-label="Interactive cumulative PnL chart. Move the pointer, drag a finger, or use the left and right arrow keys to inspect values."
      onPointerDown={selectFromPointer}
      onPointerMove={selectFromPointer}
      onPointerLeave={(event) => { if (event.pointerType === 'mouse') setActiveIndex(null); }}
      onKeyDown={handleKeyDown}
    >
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none" aria-hidden="true">
        {chart.zeroY !== null && <line className="pnl-zero-line" x1={X_PADDING} x2={WIDTH - X_PADDING} y1={chart.zeroY} y2={chart.zeroY} />}
        <polyline className="pnl-line target" points={chart.targetPath} fill="none" vectorEffect="non-scaling-stroke" />
        <polyline className="pnl-line copy" points={chart.copyPath} fill="none" vectorEffect="non-scaling-stroke" />
        {active && <>
          <line className="pnl-crosshair" x1={active.x} x2={active.x} y1={Y_PADDING} y2={HEIGHT - Y_PADDING} />
          <circle className="pnl-point target" cx={active.x} cy={active.targetY} r="4" vectorEffect="non-scaling-stroke" />
          <circle className="pnl-point copy" cx={active.x} cy={active.copyY} r="4" vectorEffect="non-scaling-stroke" />
        </>}
      </svg>
      {active && <div className={`pnl-tooltip${active.x > WIDTH * 0.72 ? ' align-right' : ''}`} style={{ left: `${(active.x / WIDTH) * 100}%` }}>
        <time>{utcTime(active.timestampMs)}</time>
        <span><i className="target-dot" />Target <strong className={active.targetPnl >= 0 ? 'positive' : 'negative'}>{money(active.targetPnl)}</strong></span>
        <span><i className="copy-dot" />Copy <strong className={active.copyPnl >= 0 ? 'positive' : 'negative'}>{money(active.copyPnl)}</strong></span>
      </div>}
      <div className="pnl-axis-labels"><time>{utcTime(chart.firstTime).slice(0, 10)}</time><span>Hover or drag to inspect</span><time>{utcTime(chart.lastTime).slice(0, 10)}</time></div>
    </div>
  );
}
