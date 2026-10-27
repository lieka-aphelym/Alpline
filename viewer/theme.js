// fpv3d lite: dark / light theme. Loaded as a plain script in <head> so the page never flashes the
// wrong colours; adds the [dark] [light] switch next to the title and remembers the choice.
(function () {
  var KEY = 'fpv3d:theme', root = document.documentElement;
  function get() { try { return localStorage.getItem(KEY) || 'dark'; } catch (e) { return 'dark'; } }
  function set(t) {
    root.dataset.theme = t;
    try { localStorage.setItem(KEY, t); } catch (e) { /* private mode */ }
    document.querySelectorAll('.themeSw button').forEach(function (b) { b.classList.toggle('on', b.dataset.t === t); });
    window.dispatchEvent(new CustomEvent('fpv3d:theme', { detail: t }));
  }
  root.dataset.theme = get();
  document.addEventListener('DOMContentLoaded', function () {
    var h1 = document.querySelector('#panel header h1, header h1');
    if (!h1) return;
    var sw = document.createElement('span');
    sw.className = 'themeSw'; sw.title = 'Dark for indoors, light for sunlight at the field';
    ['dark', 'light'].forEach(function (t) {
      var b = document.createElement('button');
      b.type = 'button'; b.dataset.t = t; b.textContent = t;
      b.addEventListener('click', function () { set(t); });
      sw.appendChild(b);
    });
    h1.insertAdjacentElement('afterend', sw);
    set(get());
  });
})();
