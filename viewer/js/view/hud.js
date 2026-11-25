import { esc } from '../core/esc.js';
// fpv3d viewer: the info box over the 3D view during a replay: status, distance / height / speed, one signal line
// per radio link (margin bar + link quality from the log), the drone zone and the details under [more].
// clean names for common telemetry columns (EdgeTX, simulator)
export const TEL_NAMES = { '1RSS_dB': 'RSSI ant. 1|dBm', '2RSS_dB': 'RSSI ant. 2|dBm', 'RQly_%': 'Control LQ|%', 'RSNR_dB': 'SNR|dB',
  'TPWR_mW': 'TX power|mW', 'RxBt_V': 'Battery|V', 'GSpd_kmh': 'GPS speed|km/h', 'Sats': 'Satellites|', 'Curr_A': 'Current|A',
  'Capa_mAh': 'Used|mAh', 'speed_m_s': null };
export function telName(k) {
  if (k in TEL_NAMES) return TEL_NAMES[k];
  const m = /^(RSSI|LQ|SNR_margin)_sim_(.+?)(_dBm|_dB)?$/.exec(k);
  if (m) return null;                        // simulator values are shown in the signal block
  return k.replace(/_/g, ' ');
}

export function createHud({ S, $, fmtDist }) {
  function lqFor(tr, i, linkName) {           // link quality from the log for this link, if any
    const key = `LQ_sim_${linkName.replace(/[^A-Za-z0-9]+/g, '_')}`.replace(/_+$/, '');
    const ctrl = (S.meta.links.find((l) => l.name === linkName)?.freq_mhz ?? 0) < 3000;   // ELRS LQ = control link only
    const v = tr.telemetry[key]?.[i] ?? (ctrl ? tr.telemetry['RQly_%']?.[i] : null);
    return v == null ? null : Math.round(v);
  }
  let hudMore = false;
  try { hudMore = localStorage.getItem('fpv3d:hudMore') === '1'; } catch { /* private mode */ }

  function renderHud(st) {
    const tr = S.track, i = S.idx;
    const tile = (v, k) => `<div class="tile"><b>${v}</b><span>${k}</span></div>`;
    const speed = tr.speed ? `${tr.speed[i].toFixed(0)}<small> km/h</small>` : '–';
    // signal: one line per radio link, margin bar + LQ from the log
    const sig = Object.entries(tr.margin).map(([name, arr]) => {
      const m = arr[i], lq = lqFor(tr, i, name);
      const col = m == null ? '#8b96a8' : m < 0 ? '#ff2d55' : m < 10 ? '#ffb000' : '#3ddc84';
      const w = m == null ? 0 : Math.max(3, Math.min(100, (m / 40) * 100));
      return `<div class="sig"><div class="h"><span>${esc(name)}</span><span><b style="color:${col}">${m == null ? '–' : `${m.toFixed(0)} dB`}</b>`
        + `${lq != null ? `<span class="muted"> · LQ ${lq}</span>` : ''}</span></div><i class="bar"><i style="width:${w}%;background:${col}"></i></i></div>`;
    }).join('');
    // drone zone: only when inside one
    let zone = '';
    if (S.zones && tr.zoneSev && tr.zoneIdx[i] >= 0) {
      const zs = S.zones.zones[tr.zoneIdx[i]];
      zone = `<div class="zone" style="border-color:${zs.info.color};color:${zs.info.color}">${zs.info.label} · <span>${esc(zs.name)}</span></div>`;
    }
    // details (collapsed by default)
    const more = [];
    more.push(['Altitude', `${tr.z[i]?.toFixed(0)} m`]);
    if (tr.vx) {
      more.push(['Vertical speed', `${tr.vz[i] >= 0 ? '+' : ''}${tr.vz[i].toFixed(1)} m/s`]);
      more.push(['Acceleration', `${tr.accG[i].toFixed(2)} g`]);
    }
    more.push(['Line of sight', tr.clearance[i] < 0 ? `blocked by ${(-tr.clearance[i]).toFixed(0)} m` : `clear by ${Math.min(tr.clearance[i], 9999).toFixed(0)} m`]);
    for (const [k, v] of Object.entries(tr.telemetry)) {
      const n = telName(k);
      if (!n || v[i] == null) continue;
      const [label, unit = ''] = n.split('|');
      more.push([label, `${Math.round(v[i] * 10) / 10}${unit ? ` ${unit}` : ''}`]);
    }
    const t = Math.max(0, (tr.t?.[i] ?? 0) - (tr.t?.[0] ?? 0)), clock = `${Math.floor(t / 60)}:${String(Math.floor(t % 60)).padStart(2, '0')}`;
    $('hud').innerHTML = `<div class="fhead"><span class="lbl">Flight · ${clock}</span>`
      + `<span class="status" style="color:${st.css}"><i style="background:${st.css}"></i>${st.label}</span></div>
      <div class="tiles">${tile(fmtDist(tr.dist[i]), 'distance')}${tile(`${tr.agl[i]?.toFixed(0)}<small> m</small>`, 'height')}${tile(speed, 'speed')}</div>
      ${zone}<div class="sigs">${sig}</div>
      <button class="more" id="hudMoreBtn" aria-expanded="${hudMore}">${hudMore ? 'Fewer details' : 'More details'}</button>
      ${hudMore ? `<table>${more.map(([a, b]) => `<tr><td class="muted">${a}</td><td>${b}</td></tr>`).join('')}</table>` : ''}`;
    $('hudMoreBtn').onclick = () => {
      hudMore = !hudMore;
      try { localStorage.setItem('fpv3d:hudMore', hudMore ? '1' : '0'); } catch { /* private mode */ }
      renderHud(st);
    };
  }

  return { render: renderHud };
}
