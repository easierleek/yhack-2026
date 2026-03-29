import { useEffect, useRef, useState } from 'react';
import type { NeoState } from '../../types/NeoState';

interface Props { state: NeoState; }

export function ReasoningFeed({ state }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const feed = state.reasoning_feed ?? [];
  const [now, setNow] = useState(() => Date.now() / 1000);

  // Auto-scroll to bottom when new entries arrive
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [feed.length]);

  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => window.clearInterval(timer);
  }, []);

  return (
    <div className="card" style={{
      borderRadius: 0, borderLeft: 'none', borderRight: 'none', borderBottom: 'none',
      flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0,
    }}>
      <div style={{ fontSize: 10, color: 'var(--text-secondary)', fontWeight: 600, marginBottom: 8, letterSpacing: '0.06em', textTransform: 'uppercase', flexShrink: 0 }}>
        K2 AI Reasoning
      </div>

      {/* Current reasoning (prominent) */}
      {state.reasoning && (
        <div style={{
          fontSize: 11, color: 'var(--text-primary)', lineHeight: 1.5,
          background: '#0e1a28', borderRadius: 6, padding: '6px 8px',
          border: '1px solid #2a3d52', marginBottom: 6, flexShrink: 0,
        }}>
          <span style={{ color: 'var(--color-grid)', marginRight: 4, fontSize: 10 }}>▶</span>
          {state.reasoning}
        </div>
      )}

      {/* Feed scroll */}
      <div
        ref={scrollRef}
        style={{
          flex: 1,
          overflowY: 'auto',
          minHeight: 0,
          display: 'flex',
          flexDirection: 'column',
          gap: 3,
        }}
      >
        {feed.length === 0 ? (
          <div style={{ color: 'var(--text-dim)', fontSize: 10, fontStyle: 'italic', padding: '4px 0' }}>
            No AI decisions yet...
          </div>
        ) : (
          [...feed].map(([ts, text], i) => {
            const elapsed = now - ts;
            const ageStr = elapsed < 60
              ? `${Math.round(elapsed)}s`
              : `${Math.floor(elapsed / 60)}m`;
            return (
              <div key={i} style={{ display: 'flex', gap: 6, fontSize: 10, lineHeight: 1.4 }}>
                <span className="mono" style={{ color: 'var(--text-dim)', flexShrink: 0, fontSize: 9 }}>
                  {ageStr}
                </span>
                <span style={{ color: 'var(--text-secondary)' }}>{text}</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
