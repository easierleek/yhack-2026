import { useEffect, useMemo, useRef, useState } from 'react';
import { useNeoSocket } from './hooks/useNeoSocket';
import { CityMap } from './components/CityMap';
import { Sidebar } from './components/Sidebar';
import { FaultBanner } from './components/FaultBanner';
import { fmtSimHour, todIcon } from './utils/pwm';
import type { TierKey } from './types/NeoState';
import './App.css';

const DEFAULT_PANEL = {
  width: 380,
  height: 540,
  right: 24,
  bottom: 108,
};

function clampPanelRect(rect: typeof DEFAULT_PANEL) {
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const width = Math.max(320, Math.min(560, rect.width));
  const height = Math.max(380, Math.min(viewportHeight - 120, rect.height));
  const right = Math.max(16, Math.min(viewportWidth - 220, rect.right));
  const bottom = Math.max(92, Math.min(viewportHeight - 180, rect.bottom));

  return { width, height, right, bottom };
}

export default function App() {
  const { state, status } = useNeoSocket();
  const [selectedZone, setSelectedZone] = useState<TierKey | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelRect, setPanelRect] = useState(DEFAULT_PANEL);
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{ startX: number; startY: number; startRight: number; startBottom: number } | null>(null);

  const simLabel = `${todIcon(state.sim_hour)} ${fmtSimHour(state.sim_hour)}`;
  const panelScale = useMemo(() => {
    const widthScale = panelRect.width / DEFAULT_PANEL.width;
    const heightScale = (panelRect.height - 74) / (DEFAULT_PANEL.height - 74);
    return Math.max(0.82, Math.min(1.18, Math.min(widthScale, heightScale)));
  }, [panelRect.height, panelRect.width]);

  useEffect(() => {
    function onMove(event: MouseEvent) {
      if (!dragRef.current) return;
      const dx = dragRef.current.startX - event.clientX;
      const dy = dragRef.current.startY - event.clientY;
      setPanelRect((prev) => clampPanelRect({
        ...prev,
        right: dragRef.current!.startRight + dx,
        bottom: dragRef.current!.startBottom + dy,
      }));
    }

    function onUp() {
      dragRef.current = null;
      setDragging(false);
    }

    function onResize() {
      setPanelRect((prev) => clampPanelRect(prev));
    }

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      window.removeEventListener('resize', onResize);
    };
  }, []);

  function startPanelDrag(event: React.MouseEvent<HTMLDivElement>) {
    dragRef.current = {
      startX: event.clientX,
      startY: event.clientY,
      startRight: panelRect.right,
      startBottom: panelRect.bottom,
    };
    setDragging(true);
  }

  function handleResize(event: React.MouseEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();

    const startX = event.clientX;
    const startY = event.clientY;
    const startWidth = panelRect.width;
    const startHeight = panelRect.height;

    function onMove(moveEvent: MouseEvent) {
      setPanelRect((prev) => clampPanelRect({
        ...prev,
        width: startWidth + (startX - moveEvent.clientX),
        height: startHeight + (startY - moveEvent.clientY),
      }));
    }

    function onUp() {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    }

    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="header-left">
          <span className="header-logo">NEO</span>
          <span className="header-subtitle">Yale Energy District • New Haven, CT</span>
        </div>
        <div className="header-center">
          {state.active_policy !== 'None' && <span className="header-policy">{state.active_policy}</span>}
        </div>
        <div className="header-right">
          <span className="header-sim-time mono">{simLabel}</span>
          <span className={`header-dot ${status.connected ? 'connected' : 'disconnected'}`} />
          <span className="text-secondary">{status.connected ? 'LIVE' : 'OFFLINE'}</span>
        </div>
      </header>

      <FaultBanner fault={state.fault} tilt={state.tilt} />

      <div className="app-body">
        <div className="map-frame">
          <CityMap state={state} selectedZone={selectedZone} onSelectZone={setSelectedZone} />
        </div>

        <aside
          className={`floating-panel ${panelOpen ? 'open' : ''} ${dragging ? 'dragging' : ''}`}
          style={{ width: panelRect.width, height: panelRect.height, right: panelRect.right, bottom: panelRect.bottom }}
        >
          <div className="floating-panel-header" onMouseDown={startPanelDrag}>
            <div>
              <p className="eyebrow">Info Card</p>
              <h1>Operations Overlay</h1>
            </div>
            <div className="floating-panel-actions">
              <button type="button" className="ghost-button" onClick={() => setSelectedZone(null)}>
                Reset focus
              </button>
              <button type="button" className="ghost-button" onClick={() => setPanelOpen(false)}>
                Close
              </button>
            </div>
          </div>
          <div className="floating-panel-scroll">
            <div className="floating-panel-scale" style={{ transform: `scale(${panelScale})`, width: `${100 / panelScale}%` }}>
              <Sidebar state={state} selectedZone={selectedZone} onClearSelection={() => setSelectedZone(null)} />
            </div>
          </div>
          <div className="floating-resize-handle" onMouseDown={handleResize} />
        </aside>

        <button
          className={`fab ${panelOpen ? 'fab-active' : ''}`}
          onClick={() => setPanelOpen((value) => !value)}
          title={panelOpen ? 'Hide info card' : 'Show info card'}
          aria-label={panelOpen ? 'Hide info card' : 'Show info card'}
        >
          <span className="fab-grid" />
          <span className="fab-grid" />
          <span className="fab-grid" />
          <span className="fab-grid" />
        </button>
      </div>
    </div>
  );
}
