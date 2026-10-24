/* sw-mobile.js — MeansCanvas Mobile Service Worker (Lightweight PWA shell) */
const CACHE_NAME = 'meanscanvas-mobile-v1';
const PRECACHE_URLS = [
    '/static/mobile.html',
    '/static/vendor/css/tailwind.css',
    '/static/vendor/js/lucide.js',
    '/static/js/utils/escape.js',
    '/static/css/theme.css',
    '/static/images/apple-touch-icon.png',
    '/static/images/favicon.svg'
];

self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME).then(cache => {
            return cache.addAll(PRECACHE_URLS).catch(err => {
                console.warn('[SW] Precache partial error, continuing:', err);
            });
        }).then(() => self.skipWaiting())
    );
});

self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(keys => {
            return Promise.all(
                keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k))
            );
        }).then(() => self.clients.claim())
    );
});

self.addEventListener('fetch', event => {
    const url = new URL(event.request.url);
    // 忽略 API 请求、WebSocket、跨域请求，只针对静态资源
    if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/') || event.request.method !== 'GET') {
        return;
    }

    event.respondWith(
        fetch(event.request).then(response => {
            // 如果在线且请求成功，选择性刷新缓存
            if (response && response.status === 200 && response.type === 'basic') {
                const responseClone = response.clone();
                caches.open(CACHE_NAME).then(cache => {
                    cache.put(event.request, responseClone);
                });
            }
            return response;
        }).catch(() => {
            // 离线时尝试从缓存返回
            return caches.match(event.request).then(cached => {
                if (cached) return cached;
                if (event.request.mode === 'navigate') {
                    return caches.match('/mobile');
                }
                return new Response('Offline', { status: 503, statusText: 'Offline' });
            });
        })
    );
});
