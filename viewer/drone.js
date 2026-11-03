// fpv3d: the drone icon (the drone seen from above: X frame, four propellers, corner brackets for the signal, the
// signal arrow with landing legs in the middle) and its animations. The styles are in theme.css (svg.drn).
//
//   const d = mountDrone(element, { size: 56 });
//   d.play('arm' | 'takeoff' | 'power', then)   plays once, then goes back to the loop (or calls `then`)
//   d.loop('ping' | 'props' | 'scan' | 'hover' | null)
//   d.link(lq)        live link quality 0-100 (or null): the ping slows down and turns amber / red as it drops
//   d.off(true)       grey and still (not connected, signal lost, build failed)
//   d.flying(true)    landing legs folded away
const FG = 'var(--t-fg)', ACC = 'var(--t-acc)';
const P = (d, w, col, op, cls, cap = 'square') =>
  `<path class="${cls}" d="${d}" style="stroke:${col};fill:none;--o:${op}" opacity="${op}" stroke-width="${w}" stroke-linecap="${cap}" stroke-linejoin="miter"/>`;
// motors in the Betaflight order: 1 rear-right, 2 front-right, 3 rear-left, 4 front-left (dir = spin direction)
const MOTORS = [['m1', 48, 48, 1], ['m2', 48, 16, -1], ['m3', 16, 48, -1], ['m4', 16, 16, 1]];
const R = 5.4;                                   // propeller half-length

export function droneSVG(cls = '') {
  let g = `<svg class="drn ${cls}" viewBox="0 0 64 64" aria-hidden="true"><g class="dr">`;
  g += P('M14 14 L50 50 M50 14 L14 50', 1.4, FG, 0.5, 'frame', 'butt');
  for (const [name, cx, cy, dir] of MOTORS) {
    const sx = cx < 32 ? 1 : -1, sy = cy < 32 ? 1 : -1;
    let br = '';
    [[7.6, 1], [10, 0.5]].forEach(([o, op], k) => {
      const x0 = cx - sx * o, y0 = cy - sy * o, L = 4.6;
      br += P(`M${x0} ${y0 + sy * L} L${x0} ${y0} L${x0 + sx * L} ${y0}`, 1.4, FG, op, `br br${k}`);
    });
    g += `<g class="arm ${name}" style="--sx:${-sx};--sy:${-sy}"><g class="mot" style="transform-origin:${cx}px ${cy}px;--dir:${dir}">`
      + P(`M${cx - R} ${cy} L${cx + R} ${cy} M${cx} ${cy - R} L${cx} ${cy + R}`, 1.7, FG, 1, 'prop', 'round')
      + `<circle cx="${cx}" cy="${cy}" r="1.3" style="fill:${FG}"/></g><g class="brs">${br}</g></g>`;
  }
  g += '<g class="core">';
  [[17, 1.3, 0.55], [21.4, 1.8, 0.8], [25.8, 2.3, 1]].forEach(([a, w, o], i) => {
    g += P(`M${32 - 6.5} ${a + 6.5} L32 ${a} L${32 + 6.5} ${a + 6.5}`, w, ACC, o, `w w${2 - i}`);
  });
  g += P('M32 26.9 L32 42', 2.3, ACC, 1, 'stem', 'butt')
    + '<path class="spark" d="M32 42 L32 26.9" pathLength="1" style="stroke:var(--spark);fill:none" stroke-width="2.3" stroke-linecap="butt" opacity="0"/>'
    + `<g class="tail">${P('M26 48 L32 42 L38 48', 2.3, ACC, 1, 'legs')}</g>`;
  return g + '</g></g></svg>';
}

const ONCE_MS = { power: 2700, arm: 3400, takeoff: 2300 };
const LOOPS = ['ping', 'props', 'scan', 'hover'];

export function mountDrone(el, { size = 56, cls = '' } = {}) {
  el.insertAdjacentHTML('beforeend', droneSVG(cls));
  const svg = el.lastElementChild;
  svg.style.width = svg.style.height = `${size}px`;
  let loop = null, onceT = 0;
  const queue = [];                                        // a second animation waits for the first (arm, then take-off)
  const apply = () => {
    LOOPS.forEach((l) => svg.classList.remove(`l-${l}`));
    if (loop) svg.classList.add(`l-${loop}`);
  };
  return {
    el: svg,
    loop(name) { loop = name; if (!onceT) apply(); },
    play(name, then) {
      if (onceT) { queue.push([name, then]); return; }
      Object.keys(ONCE_MS).forEach((n) => svg.classList.remove(`a-${n}`));
      LOOPS.forEach((l) => svg.classList.remove(`l-${l}`));
      if (name !== 'takeoff') svg.classList.remove('flying');
      void svg.getBoundingClientRect();                    // restart the animation
      svg.classList.add(`a-${name}`);
      onceT = setTimeout(() => {
        onceT = 0;
        svg.classList.remove(`a-${name}`);
        if (name === 'takeoff') svg.classList.add('flying');
        if (queue.length) { then?.(); const [n, t] = queue.shift(); this.play(n, t); return; }
        apply();
        then?.();
      }, ONCE_MS[name]);
    },
    link(lq) {
      svg.classList.toggle('lq-mid', lq != null && lq < 80 && lq >= 60);
      svg.classList.toggle('lq-low', lq != null && lq < 60);
      svg.style.setProperty('--pd', lq == null || lq >= 80 ? '1.4s' : lq >= 60 ? '2s' : '2.8s');
    },
    off(on) { svg.classList.toggle('off', !!on); if (on) queue.length = 0; },
    flying(on) { svg.classList.toggle('flying', !!on); },
  };
}
