/* DailyList · service worker
 *
 * Serve a due cose soltanto: rendere l'app installabile su Android e non
 * lasciare lo schermo bianco quando manca il segnale nei corridoi.
 *
 * La regola e' PRIMA LA RETE, la cache solo se la rete non risponde. E'
 * l'opposto di quello che fanno quasi tutti i service worker, ed e' voluto:
 * questa app cambia spesso, e una copia vecchia servita dalla cache
 * significherebbe una ragazza che lavora su stanze di ieri senza accorgersene.
 * Meglio lenta che sbagliata.
 *
 * Non si tocca MAI la cache per:
 *  - scatola.json, che e' il dato del giorno e deve arrivare fresco;
 *  - Firebase, che e' in tempo reale e ha una sua gestione offline.
 */
const CACHE = 'dailylist-v1';
const BASE = new URL('./', self.location).pathname;
const GUSCIO = [BASE, BASE + 'index.html', BASE + 'manifest.webmanifest',
                BASE + 'icon-192.png', BASE + 'icon-512.png'];

self.addEventListener('install', e => {
  // addAll fallisce tutto se un solo file manca: qui si prende quello che c'e'.
  e.waitUntil(caches.open(CACHE)
    .then(c => Promise.all(GUSCIO.map(u => c.add(u).catch(() => null))))
    .then(() => self.skipWaiting()));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(k => Promise.all(k.filter(n => n !== CACHE).map(n => caches.delete(n))))
    .then(() => self.clients.claim()));
});

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin) return;        // Firebase, font, CDN
  if (url.pathname.endsWith('/scatola.json')) return;     // il dato del giorno

  // La PAGINA si chiede sempre al server scavalcando la cache del browser.
  // GitHub Pages manda un max-age sull'HTML: senza questo, chi ha aperto
  // l'app poco fa continuerebbe a vedere la versione precedente anche dopo
  // una pubblicazione. Un elenco stanze vecchio di un'ora non si distingue
  // da uno giusto, e questo e' il modo in cui si sbaglia stanza.
  const pagina = req.mode === 'navigate' || req.destination === 'document';
  const chiamata = pagina
    ? fetch(new Request(req.url, { cache: 'reload', credentials: 'same-origin' }))
    : fetch(req);

  e.respondWith(
    chiamata
      .then(res => {
        if (res && res.ok) {
          const copia = res.clone();
          caches.open(CACHE).then(c => c.put(req, copia)).catch(() => {});
        }
        return res;
      })
      .catch(() => caches.match(req).then(hit => hit || caches.match(BASE + 'index.html')))
  );
});
