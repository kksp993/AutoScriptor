(function (global) {
  function apiPath(url) {
    const s = String(url || '');
    if (s.startsWith('/api/')) return s;
    if (s.startsWith('/')) return '/api' + s;
    return '/api/' + s;
  }

  async function request(method, url, body) {
    const upper = String(method || 'GET').toUpperCase();
    const options = {
      method: upper,
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
    };
    if (upper !== 'GET') {
      options.body = JSON.stringify({ ...(body || {}), _timestamp: Date.now() / 1000 });
    }
    const res = await fetch(apiPath(url), options);
    let data = {};
    if (res.status !== 204) {
      data = await res.json().catch(() => ({}));
    }
    return { ok: res.ok, status: res.status, data, res };
  }

  function errorMessage(data, fallback) {
    if (data && (data.message || data.error)) return data.message || data.error;
    return fallback || '操作失败';
  }

  global.WebUIApi = {
    request,
    get: async (url) => (await request('GET', url)).data,
    post: async (url, body) => (await request('POST', url, body)).data,
    errorMessage,
  };
})(window);
