// fpv3d — make text safe to put inside HTML. Names come from files and from the internet (OpenStreetMap building
// names, no-fly zone names, serial-port names): inside innerHTML they must stay text, never become tags or scripts.
export const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
