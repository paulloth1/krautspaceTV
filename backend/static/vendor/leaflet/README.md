Leaflet 1.9.4, vendored verbatim from https://unpkg.com/leaflet@1.9.4/dist/
(BSD-2-Clause, see LICENSE).

Vendored rather than loaded from a CDN: the kiosk should not depend on a third
party being reachable to draw a map, and the README's own warning about heavy
third-party JS freezing the Pi 2 applies to CDN scripts too. To update, re-fetch
leaflet.js, leaflet.css and images/ from the same path at the new version.
