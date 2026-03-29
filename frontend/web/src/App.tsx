import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type { InfrastructureNode } from './data/infrastructure';
import { useNeoSocket } from './hooks/useNeoSocket';
import { CityMap } from './components/CityMap';
import { Sidebar } from './components/Sidebar';
import { FaultBanner } from './components/FaultBanner';
import { MayorChat } from './components/MayorChat';
import { fmtSimHour, todIcon } from './utils/pwm';
import type { TierKey } from './types/NeoState';
import './App.css';

const DEFAULT_PANEL = {
  width: Math.round(window.innerWidth * 0.26),
  height: Math.round(window.innerHeight * 0.62),
  right: Math.round(window.innerWidth * 0.016),
  bottom: Math.round(window.innerHeight * 0.1),
};

const DEFAULT_CHAT_PANEL = {
  width: 450,
  height: 320,
  left: 24,
  bottom: 108,
};

function clampPanelRect(rect: typeof DEFAULT_PANEL) {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const minW = Math.round(vw * 0.18);
  const maxW = Math.round(vw * 0.5);
  const topSafe = Math.round(vh * 0.1);
  const sidePad = Math.round(vw * 0.01);
  const width = Math.max(minW, Math.min(maxW, rect.width));
  const height = Math.max(Math.round(vh * 0.4), Math.min(vh - topSafe - sidePad, rect.height));
  const right = Math.max(sidePad, Math.min(vw - Math.round(vw * 0.15), rect.right));
  const maxBottom = Math.max(Math.round(vh * 0.06), vh - height - topSafe);
  const bottom = Math.max(Math.round(vh * 0.06), Math.min(maxBottom, rect.bottom));
  return { width, height, right, bottom };
}

function clampChatPanelRect(rect: typeof DEFAULT_CHAT_PANEL) {
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const topSafeArea = 96;
  const sidePadding = 16;
  const width = Math.max(320, Math.min(600, rect.width));
  const height = Math.max(240, Math.min(viewportHeight - topSafeArea - sidePadding, rect.height));
  const left = Math.max(sidePadding, Math.min(viewportWidth - 340, rect.left));
  const maxBottom = Math.max(92, viewportHeight - height - topSafeArea);
  const bottom = Math.max(92, Math.min(maxBottom, rect.bottom));

  return { width, height, left, bottom };
}

export default function App() {
  const { state, status } = useNeoSocket();
  const [selectedZone, setSelectedZone] = useState<TierKey | null>(null);
  const [selectedNode, setSelectedNode] = useState<InfrastructureNode | null>(null);
  const [panelOpen, setPanelOpen] = useState(false);
  const [panelRect, setPanelRect] = useState(DEFAULT_PANEL);
  const [dragging, setDragging] = useState(false);
  const [chatPanelOpen, setChatPanelOpen] = useState(false);
  const [chatPanelRect, setChatPanelRect] = useState(DEFAULT_CHAT_PANEL);
  const [chatDragging, setChatDragging] = useState(false);
  const dragRef = useRef<{ pointerId: number; startX: number; startY: number; startRight: number; startBottom: number } | null>(null);
  const chatDragRef = useRef<{ pointerId: number; startX: number; startY: number; startLeft: number; startBottom: number } | null>(null);
  const panelScrollRef = useRef<HTMLDivElement>(null);

  const simLabel = `${todIcon(state.sim_hour)} ${fmtSimHour(state.sim_hour)}`;
  const panelScale = useMemo(() => {
    const widthScale = panelRect.width / DEFAULT_PANEL.width;
    const heightScale = (panelRect.height - 74) / (DEFAULT_PANEL.height - 74);
    return Math.max(0.82, Math.min(1.18, Math.min(widthScale, heightScale)));
  }, [panelRect.height, panelRect.width]);

  const handleClearSelection = useCallback(() => {
    setSelectedZone(null);
    setSelectedNode(null);
  }, []);

  const handleNodeSelect = useCallback((node: InfrastructureNode | null) => {
    setSelectedNode(node);
    setSelectedZone(node?.tier ?? null);
    if (node) {
      setPanelOpen(true);
    }
  }, []);

  useEffect(() => {
    if (panelOpen && panelScrollRef.current) {
      panelScrollRef.current.scrollTop = 0;
    }
  }, [panelOpen]);

  useEffect(() => {
    function onMove(event: PointerEvent) {
      if (dragRef.current && dragRef.current.pointerId === event.pointerId) {
        const dx = dragRef.current.startX - event.clientX;
        const dy = dragRef.current.startY - event.clientY;
        setPanelRect((prev) => clampPanelRect({
          ...prev,
          right: dragRef.current!.startRight + dx,
          bottom: dragRef.current!.startBottom + dy,
        }));
      }

      if (chatDragRef.current && chatDragRef.current.pointerId === event.pointerId) {
        const dx = event.clientX - chatDragRef.current.startX;
        const dy = chatDragRef.current.startY - event.clientY;
        setChatPanelRect((prev) => clampChatPanelRect({
          ...prev,
          left: chatDragRef.current!.startLeft + dx,
          bottom: chatDragRef.current!.startBottom + dy,
        }));
      }
    }

    function onUp(event: PointerEvent) {
      if (dragRef.current?.pointerId === event.pointerId) {
        dragRef.current = null;
        setDragging(false);
      }

      if (chatDragRef.current?.pointerId === event.pointerId) {
        chatDragRef.current = null;
        setChatDragging(false);
      }
    }

    function onResize() {
      setPanelRect((prev) => clampPanelRect(prev));
      setChatPanelRect((prev) => clampChatPanelRect(prev));
    }

    window.addEventListener('pointermove', onMove);
    window.addEventListener('pointerup', onUp);
    window.addEventListener('resize', onResize);
    return () => {
      window.removeEventListener('pointermove', onMove);
      window.removeEventListener('pointerup', onUp);
      window.removeEventListener('resize', onResize);
    };
  }, []);

  function startPanelDrag(event: React.PointerEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest('button')) {
      return;
    }

    dragRef.current = {
      pointerId: event.pointerId,
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

  function startChatPanelDrag(event: React.PointerEvent<HTMLDivElement>) {
    if ((event.target as HTMLElement).closest('button')) {
      return;
    }

    chatDragRef.current = {
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startLeft: chatPanelRect.left,
      startBottom: chatPanelRect.bottom,
    };
    setChatDragging(true);
  }

  function handleChatResize(event: React.MouseEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();

    const startX = event.clientX;
    const startY = event.clientY;
    const startWidth = chatPanelRect.width;
    const startHeight = chatPanelRect.height;

    function onMove(moveEvent: MouseEvent) {
      setChatPanelRect((prev) => clampChatPanelRect({
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
          <CityMap
            state={state}
            selectedZone={selectedZone}
            selectedNodeId={selectedNode?.id ?? null}
            onSelectZone={setSelectedZone}
            onSelectNode={handleNodeSelect}
          />
        </div>

        <aside
          className={`floating-panel ${panelOpen ? 'open' : ''} ${dragging ? 'dragging' : ''}`}
          style={{ width: panelRect.width, height: panelRect.height, right: panelRect.right, bottom: panelRect.bottom }}
        >
          <div className="floating-panel-header" onPointerDown={startPanelDrag}>
            <div>
              <p className="eyebrow">Info Card</p>
              <h1>Operations Overlay</h1>
            </div>
            <div className="floating-panel-actions">
              <button
                type="button"
                className="ghost-button"
                onClick={() => {
                  handleClearSelection();
                }}
              >
                Reset focus
              </button>
              <button type="button" className="ghost-button" onClick={() => setPanelOpen(false)}>
                Close
              </button>
            </div>
          </div>
          <div className="floating-panel-scroll" ref={panelScrollRef}>
            <div className="floating-panel-scale" style={{ transform: `scale(${panelScale})`, width: `${100 / panelScale}%` }}>
              <Sidebar
                state={state}
                selectedZone={selectedZone}
                selectedNode={selectedNode}
                onClearSelection={handleClearSelection}
              />
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

        <aside
          className={`floating-panel mayor-chat-panel ${chatPanelOpen ? 'open' : ''} ${chatDragging ? 'dragging' : ''}`}
          style={{ width: chatPanelRect.width, height: chatPanelRect.height, left: chatPanelRect.left, bottom: chatPanelRect.bottom }}
        >
          <div className="floating-panel-header" onPointerDown={startChatPanelDrag}>
            <div>
              <p className="eyebrow">Mayor Interface</p>
              <h1>Power Directive Chat</h1>
            </div>
            <div className="floating-panel-actions">
              <button type="button" className="ghost-button" onClick={() => setChatPanelOpen(false)}>
                Close
              </button>
            </div>
          </div>
          <div className="floating-panel-scroll mayor-chat-scroll">
            <MayorChat state={state} onDirective={() => {}} />
          </div>
          <div className="floating-resize-handle" onMouseDown={handleChatResize} />
        </aside>

        <button
          className={`fab fab-chat ${chatPanelOpen ? 'fab-active' : ''}`}
          onClick={() => setChatPanelOpen((value) => !value)}
          title={chatPanelOpen ? 'Hide mayor chat' : 'Show mayor chat'}
          aria-label={chatPanelOpen ? 'Hide mayor chat' : 'Show mayor chat'}
        >
          <span className="fab-chat-icon">Chat</span>
        </button>
      </div>
    </div>
  );
}
