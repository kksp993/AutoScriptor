(function (global) {
  function apiPath(url) {
    const s = String(url || '');
    if (s.startsWith('/api/')) return s;
    if (s.startsWith('/')) return '/api' + s;
    return '/api/' + s;
  }

  function isRawBody(body) {
    return (
      (typeof FormData !== 'undefined' && body instanceof FormData)
      || (typeof Blob !== 'undefined' && body instanceof Blob)
      || body instanceof ArrayBuffer
      || ArrayBuffer.isView(body)
    );
  }

  async function request(method, url, body, options) {
    const upper = String(method || 'GET').toUpperCase();
    const fetchOptions = {
      method: upper,
      credentials: 'same-origin',
      ...(options || {}),
    };
    if (upper !== 'GET' && body !== undefined && body !== null) {
      if (isRawBody(body)) {
        // 文件上传等原始载荷：让浏览器自己定 Content-Type（multipart 边界）。
        fetchOptions.body = body;
      } else {
        fetchOptions.headers = { 'Content-Type': 'application/json', ...(fetchOptions.headers || {}) };
        fetchOptions.body = JSON.stringify({ ...body, _timestamp: Date.now() / 1000 });
      }
    }
    const path = apiPath(url);
    const res = await fetch(path, fetchOptions);
    let data = {};
    if (res.status !== 204) {
      const text = await res.text().catch(() => '');
      if (text) {
        try {
          data = JSON.parse(text);
        } catch (_) {
          data = { rawText: text };
        }
      }
    }
    if (!res.ok && (!data || !Object.keys(data).length)) {
      data = {};
    }
    if (!res.ok && !data.message && !data.error) {
      const prefix = `HTTP ${res.status}${res.statusText ? ': ' + res.statusText : ''}`;
      const raw = data.rawText ? String(data.rawText).replace(/\s+/g, ' ').trim() : '';
      data.message = raw ? `${prefix}; ${path}; ${raw.slice(0, 240)}` : `${prefix}; ${path}`;
    }
    return { ok: res.ok, status: res.status, data, res };
  }

  function errorMessage(data, fallback) {
    if (data && (data.message || data.error)) return data.message || data.error;
    if (data && data.detail) {
      if (typeof data.detail === 'string') return data.detail;
      try { return JSON.stringify(data.detail); } catch { /* ignore */ }
    }
    if (data && data.rawText) return String(data.rawText).slice(0, 240);
    return fallback || '操作失败';
  }

  global.WebUIApi = {
    request,
    get: async (url) => (await request('GET', url)).data,
    post: async (url, body) => (await request('POST', url, body)).data,
    del: async (url, body) => (await request('DELETE', url, body)).data,
    errorMessage,
  };
})(window);
