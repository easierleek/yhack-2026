import { useEffect, useRef } from 'react';
import { INFRASTRUCTURE_NODES } from '../data/infrastructure';
import type { InfrastructureNode } from '../data/infrastructure';
import type { NeoState, TierKey } from '../types/NeoState';

type LeafletGlobal = {
  map: (element: HTMLElement, options?: Record<string, unknown>) => LeafletMap;
  tileLayer: (url: string, options?: Record<string, unknown>) => LeafletLayer;
  layerGroup: () => LeafletLayerGroup;
  marker: (latLng: [number, number], options?: Record<string, unknown>) => LeafletMarker;
  divIcon: (options?: Record<string, unknown>) => unknown;
  polyline: (latLngs: [number, number][], options?: Record<string, unknown>) => LeafletLayer;
  canvas: (options?: Record<string, unknown>) => unknown;
  control: {
    zoom: (options?: Record<string, unknown>) => { addTo: (target: LeafletMap) => void };
  };
};

type LeafletMap = {
  setView: (latLng: [number, number], zoom: number) => LeafletMap;
  fitBounds: (bounds: [[number, number], [number, number]], options?: Record<string, unknown>) => LeafletMap;
  setMaxBounds: (bounds: [[number, number], [number, number]]) => LeafletMap;
  setMinZoom: (zoom: number) => LeafletMap;
  setZoom: (zoom: number) => LeafletMap;
  getZoom: () => number;
  getBoundsZoom: (bounds: [[number, number], [number, number]], inside?: boolean, padding?: { x: number; y: number } | [number, number]) => number;
  invalidateSize: () => void;
  remove: () => void;
  removeLayer: (layer: LeafletLayerGroup) => void;
};

type LeafletLayer = {
  addTo: (target: LeafletMap | LeafletLayerGroup) => LeafletLayer;
};

type LeafletLayerGroup = LeafletLayer & {
  clearLayers: () => void;
};

type LeafletMarker = LeafletLayer & {
  on: (event: string, handler: () => void) => LeafletMarker;
  setIcon?: (icon: unknown) => LeafletMarker;
};

type RoadElement =
  | { type: 'node'; id: number; lat: number; lon: number }
  | { type: 'way'; id: number; nodes: number[]; tags?: { highway?: string } };

type RoadPayload = {
  fetchedAt: string;
  data: {
    elements: RoadElement[];
  };
};

const BOUNDS: [[number, number], [number, number]] = [
  [41.226, -73.058],
  [41.45, -72.792],
];

const ROAD_STYLES: Record<string, { color: string; weight: number; opacity: number; z: number }> = {
  motorway: { color: '#E05555', weight: 5.5, opacity: 0.84, z: 9 },
  motorway_link: { color: '#E05555', weight: 4.8, opacity: 0.78, z: 8 },
  trunk: { color: '#E05555', weight: 5.5, opacity: 0.84, z: 9 },
  trunk_link: { color: '#E05555', weight: 4.8, opacity: 0.78, z: 8 },
  primary: { color: '#4A90D9', weight: 4.1, opacity: 0.76, z: 7 },
  primary_link: { color: '#4A90D9', weight: 3.5, opacity: 0.7, z: 6 },
  secondary: { color: '#3AAA6A', weight: 2.9, opacity: 0.62, z: 5 },
  secondary_link: { color: '#3AAA6A', weight: 2.5, opacity: 0.56, z: 4 },
  tertiary: { color: '#C49A3C', weight: 2, opacity: 0.46, z: 3 },
  tertiary_link: { color: '#C49A3C', weight: 1.7, opacity: 0.4, z: 2 },
  residential: { color: '#C49A3C', weight: 1.4, opacity: 0.34, z: 1 },
  service: { color: '#C49A3C', weight: 1.15, opacity: 0.26, z: 0 },
  unclassified: { color: '#C49A3C', weight: 1.25, opacity: 0.3, z: 1 },
};

let roadsCachePromise: Promise<RoadPayload> | null = null;

function lockMapToBounds(map: LeafletMap) {
  const minZoom = map.getBoundsZoom(BOUNDS, true, [0, 0]);
  map.setMinZoom(minZoom);
  if (map.getZoom() < minZoom) {
    map.setZoom(minZoom);
  }
}

function getLeaflet(): LeafletGlobal | null {
  return (window as Window & { L?: LeafletGlobal }).L ?? null;
}

function fetchRoads(): Promise<RoadPayload> {
  if (!roadsCachePromise) {
    roadsCachePromise = fetch('/neo-roads.json').then(async (response) => {
      if (!response.ok) throw new Error(`Road data failed: ${response.status}`);
      return await response.json() as RoadPayload;
    });
  }

  return roadsCachePromise;
}

function nodeCardHtml(node: InfrastructureNode, state: NeoState, selectedNodeId: string | null) {
  const pct = Math.round(((state.pwm[node.channel] ?? 0) / 255) * 100);
  const isOffline = pct <= 5;
  const selectedClass = selectedNodeId === node.id ? 'n-card-selected' : '';

  return `
    <div class="n-card n-${node.tier.toLowerCase()} n-cat-${node.category} ${selectedClass}" data-id="${node.id}">
      <div class="n-head">
        <span class="n-tier">${node.tier}</span>
        <span class="n-pct">${pct}%</span>
      </div>
      <div class="n-name">${node.name}</div>
      <div class="n-sub">${node.sub}</div>
      <div class="n-bar"><div class="n-bar-fill" style="width:${pct}%"></div></div>
      <div class="n-status ${isOffline ? 'n-offline' : 'n-online'}">${isOffline ? '● OFFLINE' : '● ONLINE'}</div>
    </div>
  `;
}

interface Props {
  state: NeoState;
  selectedZone: TierKey | null;
  selectedNodeId: string | null;
  onSelectZone: (key: TierKey | null) => void;
  onSelectNode: (node: InfrastructureNode | null) => void;
}

export function CityMap({ state, selectedNodeId, onSelectZone, onSelectNode }: Props) {
  const mapRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<LeafletMap | null>(null);
  const roadsLayerRef = useRef<LeafletLayerGroup | null>(null);
  const nodeLayerRef = useRef<LeafletLayerGroup | null>(null);
  const markerRefs = useRef<Record<string, LeafletMarker>>({});
  const markerSignatureRef = useRef<Record<string, string>>({});
  const loadingRef = useRef<HTMLDivElement>(null);
  const selectNodeRef = useRef(onSelectNode);
  const selectZoneRef = useRef(onSelectZone);
  const stateRef = useRef(state);
  const selectedNodeIdRef = useRef(selectedNodeId);

  useEffect(() => {
    selectNodeRef.current = onSelectNode;
    selectZoneRef.current = onSelectZone;
  }, [onSelectNode, onSelectZone]);

  useEffect(() => {
    stateRef.current = state;
    selectedNodeIdRef.current = selectedNodeId;
  }, [selectedNodeId, state]);

  useEffect(() => {
    const leaflet = getLeaflet();
    if (!leaflet || !mapRef.current || mapInstanceRef.current) return;

    const map = leaflet.map(mapRef.current, {
      center: [41.311, -72.92],
      zoom: 12,
      maxZoom: 17,
      preferCanvas: true,
      zoomControl: false,
      attributionControl: false,
      maxBounds: BOUNDS,
      maxBoundsViscosity: 1.0,
    }).setView([41.311, -72.92], 12);

    map.setMaxBounds(BOUNDS);
    map.invalidateSize();
    map.fitBounds(BOUNDS, { padding: [0, 0], animate: false });
    lockMapToBounds(map);

    leaflet.tileLayer(
      'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
      { subdomains: 'abcd', maxZoom: 17, attribution: '© CartoDB' },
    ).addTo(map);
    leaflet.control.zoom({ position: 'topleft' }).addTo(map);

    roadsLayerRef.current = leaflet.layerGroup().addTo(map) as LeafletLayerGroup;
    nodeLayerRef.current = leaflet.layerGroup().addTo(map) as LeafletLayerGroup;
    mapInstanceRef.current = map;

    const handleResize = () => {
      map.invalidateSize();
      lockMapToBounds(map);
    };

    window.addEventListener('resize', handleResize);

    return () => {
      window.removeEventListener('resize', handleResize);
      roadsLayerRef.current = null;
      nodeLayerRef.current = null;
      mapInstanceRef.current?.remove();
      mapInstanceRef.current = null;
    };
  }, []);

  useEffect(() => {
    const leaflet = getLeaflet();
    const roadsLayer = roadsLayerRef.current;
    if (!leaflet || !roadsLayer) return;

    let cancelled = false;
    roadsLayer.clearLayers();
    if (loadingRef.current) loadingRef.current.classList.add('visible');

    const renderer = leaflet.canvas({ padding: 0.2 });

    void fetchRoads().then(async (payload) => {
      if (cancelled) return;

      const nodeCoord: Record<number, [number, number]> = {};
      payload.data.elements.forEach((element) => {
        if (element.type === 'node') nodeCoord[element.id] = [element.lat, element.lon];
      });

      const ways = payload.data.elements
        .filter((element): element is Extract<RoadElement, { type: 'way' }> => element.type === 'way' && Boolean(element.tags?.highway && ROAD_STYLES[element.tags.highway]))
        .sort((a, b) => ROAD_STYLES[a.tags!.highway!].z - ROAD_STYLES[b.tags!.highway!].z);

      const chunkSize = 250;
      for (let start = 0; start < ways.length; start += chunkSize) {
        if (cancelled) return;
        const chunk = ways.slice(start, start + chunkSize);
        chunk.forEach((way) => {
          const style = ROAD_STYLES[way.tags!.highway!];
          const coords = way.nodes.map((id) => nodeCoord[id]).filter(Boolean);
          if (coords.length < 2) return;
          leaflet.polyline(coords, {
            color: style.color,
            weight: style.weight,
            lineCap: 'round',
            lineJoin: 'round',
            opacity: style.opacity,
            renderer,
            interactive: false,
            smoothFactor: 1,
          }).addTo(roadsLayer);
        });

        await new Promise((resolve) => requestAnimationFrame(resolve));
      }

      if (!cancelled && loadingRef.current) loadingRef.current.classList.remove('visible');
    }).catch(() => {
      if (!cancelled && loadingRef.current) loadingRef.current.classList.remove('visible');
    });

    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const leaflet = getLeaflet();
    const nodeLayer = nodeLayerRef.current;
    if (!leaflet || !nodeLayer) return;

    INFRASTRUCTURE_NODES.forEach((node) => {
      if (markerRefs.current[node.id]) {
        return;
      }

      const marker = leaflet.marker([node.lat, node.lng], {
        icon: leaflet.divIcon({
          className: '',
          html: nodeCardHtml(node, stateRef.current, selectedNodeIdRef.current),
          iconSize: [152, 86],
          iconAnchor: [76, 43],
        }),
      });

      marker
        .on('click', () => {
          selectNodeRef.current(node);
          selectZoneRef.current(node.tier);
        })
        .addTo(nodeLayer);

      markerRefs.current[node.id] = marker;
      markerSignatureRef.current[node.id] = `${selectedNodeIdRef.current === node.id}:${Math.round(((stateRef.current.pwm[node.channel] ?? 0) / 255) * 100)}`;
    });
    return () => {
      markerRefs.current = {};
      markerSignatureRef.current = {};
      nodeLayer.clearLayers();
    };
  }, []);

  useEffect(() => {
    const leaflet = getLeaflet();
    if (!leaflet) return;

    INFRASTRUCTURE_NODES.forEach((node) => {
      const marker = markerRefs.current[node.id];
      if (!marker?.setIcon) return;
      const nextSignature = `${selectedNodeId === node.id}:${Math.round(((state.pwm[node.channel] ?? 0) / 255) * 100)}`;
      if (markerSignatureRef.current[node.id] === nextSignature) {
        return;
      }

      marker.setIcon(leaflet.divIcon({
        className: '',
        html: nodeCardHtml(node, state, selectedNodeId),
        iconSize: [152, 86],
        iconAnchor: [76, 43],
      }));
      markerSignatureRef.current[node.id] = nextSignature;
    });
  }, [selectedNodeId, state]);

  return (
    <div className="leaflet-map-shell neo-map-shell">
      <div ref={mapRef} className="leaflet-map-canvas neo-map-canvas" />

      <div ref={loadingRef} className="neo-road-loading">
        <div className="neo-road-spinner" />
        <div className="neo-road-loading-text">Loading road overlay...</div>
      </div>

      <div className="map-static-overlay neo-tier-legend">
        <div className="map-overlay-title">Grid Tiers</div>
        <div className="tier-legend-row"><span className="tier-swatch" style={{ background: '#4A90D9', opacity: 1 }} /><span className="tier-name">T1</span><span className="tier-pct">Critical</span></div>
        <div className="tier-legend-row"><span className="tier-swatch" style={{ background: '#E05555', opacity: 1 }} /><span className="tier-name">T2</span><span className="tier-pct">Utility</span></div>
        <div className="tier-legend-row"><span className="tier-swatch" style={{ background: '#3AAA6A', opacity: 1 }} /><span className="tier-name">T3</span><span className="tier-pct">Residential</span></div>
        <div className="tier-legend-row"><span className="tier-swatch" style={{ background: '#C49A3C', opacity: 1 }} /><span className="tier-name">T4</span><span className="tier-pct">Commercial</span></div>
        <div className="neo-legend-divider" />
        <div className="map-overlay-title">Roads</div>
        <div className="neo-road-legend-row"><span className="neo-road-line" style={{ background: '#E05555' }} /><span className="neo-road-label">Motorway / Trunk</span></div>
        <div className="neo-road-legend-row"><span className="neo-road-line" style={{ background: '#4A90D9' }} /><span className="neo-road-label">Primary</span></div>
        <div className="neo-road-legend-row"><span className="neo-road-line" style={{ background: '#3AAA6A' }} /><span className="neo-road-label">Secondary</span></div>
        <div className="neo-road-legend-row"><span className="neo-road-line" style={{ background: '#C49A3C' }} /><span className="neo-road-label">Tertiary</span></div>
      </div>

      <div className="map-static-overlay neo-map-status">
        <span className="mono">{state.relay === 0 ? 'SOLAR PRIORITY ACTIVE' : 'GRID ASSIST ACTIVE'}</span>
      </div>

      <SensorOverlay state={state} />
    </div>
  );
}

function SensorOverlay({ state }: { state: NeoState }) {
  const lightPct = Math.round(state.light / 1023 * 100);
  const isStale = Date.now() - (state as NeoState & { _ts?: number })._ts! > 10000;

  if (isStale) {
    return (
      <div className="neo-sensor-overlay" style={{ color: 'var(--red)' }}>
        SENSOR OFFLINE
      </div>
    );
  }

  return (
    <div className="neo-sensor-overlay">
      <span>☀ {lightPct}%</span>
      <span className="neo-sensor-sep">|</span>
      <span>{state.temp_c.toFixed(1)}°C</span>
      <span className="neo-sensor-sep">|</span>
      <span>{state.pressure_hpa.toFixed(0)} hPa</span>
    </div>
  );
}
