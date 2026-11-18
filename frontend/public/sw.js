/* Issue Hub service worker
 *
 * 只做两件事，不要过度设计：
 * 1. 缓存静态资源（JS/CSS/图标），二次打开秒开 —— 手机上体验差别很大
 * 2. 提供离线兜底页：断网时至少能看到「离线」而不是浏览器的恐龙页
 *
 * 刻意**不缓存 API 请求**：issue 数据必须实时，缓存了会看到过期状态，
 * 比看不到更糟。
 */
const VERSION = 'ih-v1';
const STATIC_CACHE = `${VERSION}-static`;
const SHELL = ['/', '/issues', '/manifest.webmanifest'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE).then((cache) => cache.addAll(SHELL).catch(() => null))
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => !k.startsWith(VERSION)).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;

  const url = new URL(request.url);

  // API 一律走网络，不缓存（数据必须实时）
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/files/')) return;

  // 静态资源：缓存优先（带 hash 的文件名不会变）
  if (/\.(js|css|png|jpg|jpeg|svg|woff2?|webmanifest)$/.test(url.pathname)) {
    event.respondWith(
      caches.match(request).then((hit) =>
        hit ||
        fetch(request).then((res) => {
          const copy = res.clone();
          caches.open(STATIC_CACHE).then((c) => c.put(request, copy)).catch(() => null);
          return res;
        }).catch(() => hit || Response.error())
      )
    );
    return;
  }

  // 页面导航：网络优先，失败回落到缓存的首页（SPA 路由都能命中 index.html）
  if (request.mode === 'navigate') {
    event.respondWith(
      fetch(request).catch(() =>
        caches.match('/').then((hit) => hit || new Response(
          '<h1>离线</h1><p>当前网络不可用，请连上网络后刷新。</p>',
          { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        ))
      )
    );
  }
});
