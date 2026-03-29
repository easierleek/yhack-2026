import { useEffect, useMemo, useRef } from 'react';
import { TIER_DEFS } from '../types/NeoState';
import type { NeoState, TierKey } from '../types/NeoState';
import { tierAvgPwm } from '../utils/pwm';

type LeafletGlobal = {
  map: (element: HTMLElement, options?: Record<string, unknown>) => LeafletMap;
  tileLayer: (url: string, options?: Record<string, unknown>) => LeafletLayer;
  layerGroup: () => LeafletLayerGroup;
  marker: (latLng: [number, number], options?: Record<string, unknown>) => LeafletMarker;
  circleMarker: (latLng: [number, number], options?: Record<string, unknown>) => LeafletMarker;
  divIcon: (options?: Record<string, unknown>) => unknown;
  polyline: (latLngs: [number, number][], options?: Record<string, unknown>) => LeafletLayer;
};

type LeafletMap = {
  setView: (latLng: [number, number], zoom: number) => LeafletMap;
  setMaxBounds: (bounds: [[number, number], [number, number]]) => LeafletMap;
  createPane: (name: string) => HTMLElement;
  getPane: (name: string) => HTMLElement | undefined;
  remove: () => void;
};

type LeafletLayer = {
  addTo: (target: LeafletMap | LeafletLayerGroup) => LeafletLayer;
};

type LeafletLayerGroup = LeafletLayer & {
  clearLayers: () => void;
};

type LeafletMarker = LeafletLayer & {
  bindPopup: (content: string) => LeafletMarker;
  on: (event: string, handler: () => void) => LeafletMarker;
};

const NEW_HAVEN_CENTER: [number, number] = [41.3083, -72.9279];
const NEW_HAVEN_BOUNDS: [[number, number], [number, number]] = [
  [41.258, -73.015],
  [41.365, -72.845],
];

const TIER_STYLE: Record<TierKey, { color: string; border: string; shadow: string }> = {
  T1: { color: '#7ab3ff', border: '#d6eeff', shadow: '#274f7f' },
  T2: { color: '#ff6f7d', border: '#ffd8de', shadow: '#7f2d3b' },
  T3: { color: '#4ec39c', border: '#d6fff1', shadow: '#1d624f' },
  T4: { color: '#f4bc57', border: '#fff1c7', shadow: '#7a5924' },
};

interface ZoneDef {
  tier: TierKey;
  channel: number;
  label: string;
  sublabel: string;
  position: [number, number];
  footprint: 'large' | 'medium' | 'small';
}

const ZONES: ZoneDef[] = [
  { tier: 'T1', channel: 0, label: 'Yale New Haven', sublabel: 'York Street', position: [41.3045436, -72.9357954], footprint: 'large' },
  { tier: 'T1', channel: 1, label: 'St. Raphael', sublabel: 'Chapel Campus', position: [41.3102538, -72.9431532], footprint: 'medium' },

  { tier: 'T2', channel: 2, label: 'English Station', sublabel: 'Power Plant', position: [41.3199, -72.8978], footprint: 'medium' },
  { tier: 'T2', channel: 3, label: 'Harbor Substation', sublabel: 'Utility', position: [41.2876, -72.9038], footprint: 'small' },
  { tier: 'T2', channel: 4, label: 'East Shore Water', sublabel: 'Utility', position: [41.2772, -72.8798], footprint: 'small' },

  { tier: 'T3', channel: 5, label: 'East Rock', sublabel: 'Residential', position: [41.3248, -72.9151], footprint: 'medium' },
  { tier: 'T3', channel: 6, label: 'Fair Haven', sublabel: 'Residential', position: [41.3157, -72.8928], footprint: 'medium' },
  { tier: 'T3', channel: 7, label: 'Westville', sublabel: 'Residential', position: [41.3112, -72.9664], footprint: 'medium' },
  { tier: 'T3', channel: 8, label: 'Beaver Hills', sublabel: 'Residential', position: [41.3198, -72.9514], footprint: 'small' },
  { tier: 'T3', channel: 9, label: 'Wooster Sq', sublabel: 'Residential', position: [41.3079, -72.9124], footprint: 'small' },

  { tier: 'T4', channel: 10, label: 'Broadway', sublabel: 'Commercial', position: [41.3087, -72.9289], footprint: 'small' },
  { tier: 'T4', channel: 11, label: 'Whalley', sublabel: 'Commercial', position: [41.3116, -72.9498], footprint: 'small' },
  { tier: 'T4', channel: 12, label: 'Long Wharf', sublabel: 'Commercial', position: [41.2859, -72.9238], footprint: 'medium' },
  { tier: 'T4', channel: 13, label: 'State Street', sublabel: 'Commercial', position: [41.3144, -72.9093], footprint: 'small' },
  { tier: 'T4', channel: 14, label: 'The Hill', sublabel: 'Commercial', position: [41.2997, -72.9346], footprint: 'medium' },
  { tier: 'T4', channel: 15, label: 'Chapel West', sublabel: 'Commercial', position: [41.3117, -72.9567], footprint: 'small' },
];

const SOURCE_NODES = [
  { label: 'Solar', value: 'solar_ma', position: [41.3345, -72.9788] as [number, number], color: '#ffd46f' },
  { label: 'Grid', value: 'load_ma', position: [41.2748, -72.8768] as [number, number], color: '#98a8ff' },
] as const;

function getLeaflet(): LeafletGlobal | null {
  return (window as Window & { L?: LeafletGlobal }).L ?? null;
}

function footprintClass(footprint: ZoneDef['footprint']) {
  if (footprint === 'large') return 'zone-large';
  if (footprint === 'medium') return 'zone-medium';
  return 'zone-small';
}

function zoneIconHtml(zone: ZoneDef, state: NeoState, isSelected: boolean) {
  const tierStyle = TIER_STYLE[zone.tier];
  const brightness = Math.max(0.42, (state.pwm[zone.channel] ?? 0) / 255);
  const pct = Math.round(((state.pwm[zone.channel] ?? 0) / 255) * 100);
  const showLabel = zone.tier === 'T1' || zone.tier === 'T2';

  return `
    <div
      class="neo-zone ${footprintClass(zone.footprint)} ${isSelected ? 'zone-selected' : ''}"
      style="
        --zone-fill:${tierStyle.color};
        --zone-border:${tierStyle.border};
        --zone-shadow:${tierStyle.shadow};
        --zone-opacity:${brightness};
      "
    >
      <div class="neo-zone-depth"></div>
      <div class="neo-zone-face">
        ${showLabel ? `<div class="neo-zone-title">${zone.label}</div>` : ''}
        ${showLabel ? `<div class="neo-zone-subtitle">${zone.sublabel}</div>` : ''}
        <div class="neo-zone-percent">${pct}%</div>
      </div>
    </div>
  `;
}

interface Props {
  state: NeoState;
  selectedZone: TierKey | null;
  onSelectZone: (key: TierKey | null) => void;
}

export function CityMap({ state, selectedZone, onSelectZone }: Props) {
  const mapRef = useRef<HTMLDivElement>(null);
  const leafletMapRef = useRef<LeafletMap | null>(null);
  const infrastructureLayerRef = useRef<LeafletLayerGroup | null>(null);
  const sourceLayerRef = useRef<LeafletLayerGroup | null>(null);
  const flowLayerRef = useRef<LeafletLayerGroup | null>(null);

  useEffect(() => {
    const leaflet = getLeaflet();
    if (!leaflet || !mapRef.current || leafletMapRef.current) return;

    const map = leaflet.map(mapRef.current, {
      zoomControl: true,
      attributionControl: true,
      dragging: true,
      scrollWheelZoom: true,
      doubleClickZoom: false,
    }).setView(NEW_HAVEN_CENTER, 13);

    map.setMaxBounds(NEW_HAVEN_BOUNDS);

    leaflet
      .tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 18,
        minZoom: 12,
        className: 'neo-tile-layer',
      })
      .addTo(map);

    map.createPane('flows');
    const flowsPane = map.getPane('flows');
    if (flowsPane) flowsPane.style.zIndex = '440';

    infrastructureLayerRef.current = leaflet.layerGroup().addTo(map) as LeafletLayerGroup;
    sourceLayerRef.current = leaflet.layerGroup().addTo(map) as LeafletLayerGroup;
    flowLayerRef.current = leaflet.layerGroup().addTo(map) as LeafletLayerGroup;
    leafletMapRef.current = map;

    return () => {
      flowLayerRef.current = null;
      sourceLayerRef.current = null;
      infrastructureLayerRef.current = null;
      leafletMapRef.current?.remove();
      leafletMapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const leaflet = getLeaflet();
    const infrastructureLayer = infrastructureLayerRef.current;
    const sourceLayer = sourceLayerRef.current;
    const flowLayer = flowLayerRef.current;
    if (!leaflet || !infrastructureLayer || !sourceLayer || !flowLayer) return;

    infrastructureLayer.clearLayers();
    sourceLayer.clearLayers();
    flowLayer.clearLayers();

    ZONES.forEach((zone) => {
      const marker = leaflet.marker(zone.position, {
        icon: leaflet.divIcon({
          className: 'neo-zone-wrapper',
          html: zoneIconHtml(zone, state, selectedZone === zone.tier),
          iconSize: zone.footprint === 'large' ? [124, 124] : zone.footprint === 'medium' ? [110, 110] : [96, 96],
          iconAnchor: zone.footprint === 'large' ? [62, 62] : zone.footprint === 'medium' ? [55, 55] : [48, 48],
        }),
      });

      marker
        .bindPopup(`${zone.label} · ${zone.sublabel}`)
        .on('click', () => onSelectZone(selectedZone === zone.tier ? null : zone.tier))
        .addTo(infrastructureLayer);
    });

    const flowColor = state.relay === 0 ? '#ffd46f' : '#98a8ff';
    const sourcePosition = state.relay === 0 ? SOURCE_NODES[0].position : SOURCE_NODES[1].position;

    Object.entries(
      TIER_DEFS.reduce<Record<TierKey, [number, number]>>((acc, tier) => {
        const tierZones = ZONES.filter((zone) => zone.tier === tier.key);
        const lat = tierZones.reduce((sum, zone) => sum + zone.position[0], 0) / tierZones.length;
        const lng = tierZones.reduce((sum, zone) => sum + zone.position[1], 0) / tierZones.length;
        acc[tier.key] = [lat, lng];
        return acc;
      }, {} as Record<TierKey, [number, number]>),
    ).forEach(([tierKey, latLng]) => {
      const avgPwm = tierAvgPwm(state.pwm, tierKey as TierKey) / 255;
      leaflet.polyline([sourcePosition, latLng], {
        pane: 'flows',
        color: flowColor,
        weight: 3 + avgPwm * 4,
        opacity: 0.16 + avgPwm * 0.34,
        lineCap: 'round',
        dashArray: '10 10',
      }).addTo(flowLayer);
    });

    SOURCE_NODES.forEach((node) => {
      const value = node.value === 'solar_ma' ? state.solar_ma : state.load_ma;
      leaflet
        .circleMarker(node.position, {
          radius: 11,
          color: node.color,
          weight: 2,
          fillColor: '#0b1118',
          fillOpacity: 0.92,
        })
        .bindPopup(`${node.label} · ${Math.round(value)} mA`)
        .addTo(sourceLayer);
    });
  }, [onSelectZone, selectedZone, state]);

  const legend = useMemo(() => (
    TIER_DEFS.map((tier) => {
      const avgPwm = Math.round((tierAvgPwm(state.pwm, tier.key) / 255) * 100);
      return {
        key: tier.key,
        label: tier.label,
        color: TIER_STYLE[tier.key].color,
        opacity: Math.max(0.35, avgPwm / 100),
        pct: avgPwm,
      };
    })
  ), [state.pwm]);

  return (
    <div className="leaflet-map-shell">
      <div ref={mapRef} className="leaflet-map-canvas" />

      <div className="map-static-overlay tier-legend">
        <div className="map-overlay-title">Yale Grid Tiers</div>
        {legend.map((tier) => (
          <div key={tier.key} className="tier-legend-row">
            <span className="tier-swatch" style={{ background: tier.color, opacity: tier.opacity }} />
            <span className="tier-name">{tier.key} · {tier.label}</span>
            <span className="tier-pct mono">{tier.pct}%</span>
          </div>
        ))}
      </div>

      <div className="map-static-overlay map-status">
        <span className="mono">{state.relay === 0 ? 'SOLAR PRIORITY ACTIVE' : 'STATE GRID ASSIST ACTIVE'}</span>
      </div>
    </div>
  );
}
