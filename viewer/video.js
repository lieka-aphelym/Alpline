// fpv3d — flight video player synchronised with the log timeline.
//
// Mapping between the two clocks:   t_log = rate * t_video + offset
//  * 1 sync point  -> offset only (rate = 1)
//  * 2+ sync points -> rate and offset (corrects DVR frame-rate drift)
// Sync is remembered per scene / track / video file in the browser (localStorage).

const $ = (id) => document.getElementById(id);
const fmt = (s) => `${s < 0 ? '−' : ''}${Math.floor(Math.abs(s) / 60)}:${(Math.abs(s) % 60).toFixed(1).padStart(4, '0')}`;

export function initVideo(app) {
  // app: { getTime(), setTime(t), duration(), keyPrefix(), onLayout(), setPlayingUi(bool) }
  const box = $('videoBox'), video = $('video'), srtEl = $('srtLine');
  const st = { loaded: false, linked: true, rate: 1, offset: 0, points: [], cues: [], name: '', url: null };

  // ---------------------------------------------------------------- persistence
  const key = () => `fpv3d:sync:${app.keyPrefix()}:${st.name}`;
  function save() {
    try { localStorage.setItem(key(), JSON.stringify({ rate: st.rate, offset: st.offset, points: st.points })); } catch { /* private mode */ }
  }
  function restore() {
    st.rate = 1; st.offset = 0; st.points = [];
    try {
      const v = JSON.parse(localStorage.getItem(key()) || 'null');
      if (v) Object.assign(st, { rate: v.rate ?? 1, offset: v.offset ?? 0, points: v.points ?? [] });
    } catch { /* ignore */ }
  }

  // ---------------------------------------------------------------- mapping
  const logTime = (tv = video.currentTime) => st.rate * tv + st.offset;
  const videoTime = (tl) => (tl - st.offset) / st.rate;

  function fit() {
    const p = st.points;
    if (p.length >= 2) {   // least squares over all points
      const n = p.length, mx = p.reduce((s, q) => s + q.v, 0) / n, my = p.reduce((s, q) => s + q.l, 0) / n;
      let sxy = 0, sxx = 0;
      for (const q of p) { sxy += (q.v - mx) * (q.l - my); sxx += (q.v - mx) ** 2; }
      st.rate = sxx > 1e-6 ? sxy / sxx : 1;
      if (!(st.rate > 0.9 && st.rate < 1.1)) st.rate = 1;   // guard against mis-clicks
      st.offset = my - st.rate * mx;
    } else if (p.length === 1) {
      st.rate = 1; st.offset = p[0].l - p[0].v;
    }
    save(); status();
  }

  // ---------------------------------------------------------------- SRT sidecar (DJI writes one per recording)
  function parseSrt(text) {
    const toS = (h, m, s, ms) => +h * 3600 + +m * 60 + +s + +ms / 1000;
    const re = /(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)\s*\n([\s\S]*?)(?:\n\s*\n|$)/g;
    const cues = []; let m;
    while ((m = re.exec(text.replace(/\r/g, '')))) {
      cues.push({ a: toS(m[1], m[2], m[3], m[4]), b: toS(m[5], m[6], m[7], m[8]), text: m[9].replace(/<[^>]+>/g, '').trim() });
    }
    return cues;
  }
  function cueAt(t) {
    const c = st.cues; let lo = 0, hi = c.length - 1;
    while (lo <= hi) { const mid = (lo + hi) >> 1; if (c[mid].b < t) lo = mid + 1; else if (c[mid].a > t) hi = mid - 1; else return c[mid]; }
    return null;
  }

  // ---------------------------------------------------------------- UI
  function status() {
    const tl = logTime(), dur = app.duration();
    const where = !st.loaded ? '' : tl < 0 ? ' · before log start' : dur && tl > dur ? ' · after log end' : '';
    $('vSync').textContent = st.loaded
      ? `log = video ${st.offset >= 0 ? '+' : '−'} ${Math.abs(st.offset).toFixed(2)} s${st.rate !== 1 ? ` · rate ${st.rate.toFixed(4)}` : ''} · ${st.points.length} sync pt${st.points.length === 1 ? '' : 's'}`
      : 'No video loaded';
    $('vTimes').textContent = st.loaded ? `video ${fmt(video.currentTime)} → log ${fmt(tl)}${where}` : '';
    $('vLink').textContent = st.linked ? '[linked]' : '[unlinked]';
    $('vLink').classList.toggle('warn', !st.linked);
    $('vSyncHere').disabled = st.linked || !st.loaded;
    video.controls = !st.linked;
    if (st.cues.length && $('srtOn').checked) {
      const c = cueAt(video.currentTime); srtEl.textContent = c ? c.text : ''; srtEl.hidden = !c;
    } else srtEl.hidden = true;
  }

  async function loadFiles(files) {
    const vid = [...files].find((f) => f.type.startsWith('video/') || /\.(mp4|mov|mkv|webm)$/i.test(f.name));
    const srt = [...files].find((f) => /\.srt$/i.test(f.name));
    if (vid) {
      if (st.url) URL.revokeObjectURL(st.url);
      st.url = URL.createObjectURL(vid);              // plays straight from disk, any size, seekable
      st.name = vid.name; video.src = st.url; st.loaded = true; st.cues = [];
      $('vName').textContent = vid.name;
      box.classList.remove('hidden'); $('videoTools').classList.remove('hidden');
      restore();
      video.addEventListener('error', () => {
        $('vSync').textContent = 'This browser cannot decode the file (often H.265/HEVC). Convert it: python -m fpv3d video-convert <file>';
      }, { once: true });
      video.addEventListener('loadedmetadata', () => { seekToLog(app.getTime()); status(); }, { once: true });
    }
    if (srt) { st.cues = parseSrt(await srt.text()); $('srtInfo').textContent = `${srt.name}: ${st.cues.length} entries`; }
    status();
  }

  function seekToLog(tl) {
    if (!st.loaded || !st.linked || !isFinite(video.duration)) return;
    const tv = videoTime(tl);
    video.currentTime = Math.min(Math.max(tv, 0), video.duration);
  }

  // header: drag to move (PiP mode)
  (() => {
    const head = $('videoHead'); let d = null;
    head.addEventListener('pointerdown', (e) => {
      if (e.target.closest('button') || document.body.classList.contains('video-main')) return;
      const r = box.getBoundingClientRect(); d = { x: e.clientX - r.left, y: e.clientY - r.top };
      head.setPointerCapture(e.pointerId);
    });
    head.addEventListener('pointermove', (e) => {
      if (!d) return;
      box.style.left = `${Math.max(0, e.clientX - d.x)}px`; box.style.top = `${Math.max(0, e.clientY - d.y)}px`;
      box.style.right = 'auto'; box.style.bottom = 'auto';
    });
    head.addEventListener('pointerup', () => { d = null; });
  })();

  $('vFile').onchange = (e) => loadFiles(e.target.files);
  $('vSwap').onclick = () => { document.body.classList.toggle('video-main'); app.onLayout(); };
  $('vClose').onclick = () => {
    video.pause(); box.classList.add('hidden'); document.body.classList.remove('video-main'); app.onLayout();
  };
  $('vShow').onclick = () => { if (st.loaded) box.classList.remove('hidden'); };
  $('vLink').onclick = () => {
    st.linked = !st.linked;
    if (st.linked) seekToLog(app.getTime());
    status();
  };
  $('vSyncHere').onclick = () => {
    // user has paused the video and the log on the same event (e.g. props start spinning at arm)
    st.points.push({ v: video.currentTime, l: app.getTime() });
    st.linked = true; fit();
  };
  $('vReset').onclick = () => { st.points = []; st.rate = 1; st.offset = 0; save(); seekToLog(app.getTime()); status(); };
  for (const b of document.querySelectorAll('[data-nudge]')) {
    b.onclick = () => { st.offset += +b.dataset.nudge; save(); seekToLog(app.getTime()); status(); };
  }
  $('srtOn').onchange = status;
  video.addEventListener('timeupdate', status);
  video.addEventListener('seeked', status);
  video.addEventListener('ended', () => app.setPlayingUi(false));

  // ---------------------------------------------------------------- public API used by app.js
  return {
    active: () => st.loaded && st.linked && !box.classList.contains('hidden'),
    drivesClock: () => st.loaded && st.linked && !video.paused,
    logTime: () => logTime(),
    seekToLog,
    play() {
      if (videoTime(app.getTime()) >= video.duration - 0.05) return;  // log is past the end of the video
      seekToLog(app.getTime()); video.play().catch(() => {});
    },
    pause() { video.pause(); },
    setRate(r) { video.playbackRate = r; },
    tick() { if (st.loaded) status(); },
    trackChanged() { if (st.loaded) { restore(); seekToLog(app.getTime()); status(); } },
  };
}
