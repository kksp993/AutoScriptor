/** Read-only Python API handbook. Examples are copied, never executed here. */
const ApiDocsPanel = {
  name: 'ApiDocsPanel',
  template: `
<section class="api-docs" aria-label="Python 脚本 API 文档">
  <header class="api-docs-header">
    <div>
      <div class="api-docs-eyebrow">AUTOSCRIPTOR / PYTHON SCRIPT API</div>
      <h1>API 文档 <span v-if="reference" class="api-docs-version">{{ reference.display_version }}</span></h1>
      <p>查用法、看示例，写出自己的自动化脚本。</p>
    </div>
    <button type="button" class="api-docs-button" :disabled="loading" @click="loadReference">
      <i class="fa fa-refresh" aria-hidden="true"></i> {{ loading ? '正在读取' : '重新读取' }}
    </button>
  </header>
  <div v-if="loading" class="api-docs-state" role="status">正在读取当前安装的 API 文档…</div>
  <div v-else-if="error" class="api-docs-state api-docs-error" role="alert">
    <h2>文档加载失败</h2><p>{{ error }}</p>
    <button type="button" class="api-docs-button" @click="loadReference">重试</button>
  </div>
  <template v-else-if="reference">
    <nav class="api-docs-tabs" aria-label="文档页面">
      <button v-for="section in sections" :key="section.id" type="button"
        :aria-current="activeSection === section.id ? 'page' : undefined"
        :class="{ 'is-active': activeSection === section.id }" @click="showSection(section.id)">{{ section.title }}</button>
      <span>{{ reference.entries.length }} 个接口</span>
    </nav>

    <div v-if="activeSection === 'start'" ref="contentPane" class="api-docs-scroll">
      <div class="api-docs-intro">
        <span class="api-docs-eyebrow">QUICK START</span>
        <h2>{{ reference.quickstart.title }}</h2>
        <p>{{ reference.quickstart.description }}</p>
      </div>
      <div class="api-docs-start-grid">
        <div class="api-docs-step-grid">
          <button v-for="step in reference.quickstart.steps" :key="step.title" type="button" class="api-docs-step" @click="openApi(step.api)">
            <strong>{{ step.title }}</strong><span>{{ step.text }}</span><small>查看 {{ step.api }} →</small>
          </button>
        </div>
        <div class="api-docs-example">
          <div class="api-docs-code-header"><span>Python · 打开邮件</span><button type="button" @click="copyCode(reference.quickstart.code)">复制入门示例</button></div>
          <pre><code>{{ reference.quickstart.code }}</code></pre>
        </div>
      </div>
      <h2>常见问题</h2>
      <div class="api-docs-guidance">
        <article v-for="item in reference.guidance" :key="item.title"><h3>{{ item.title }}</h3><p>{{ item.text }}</p></article>
      </div>
      <details class="api-docs-source">
        <summary>参考文档</summary>
        <div class="api-docs-references"><a v-for="item in reference.references" :key="item.url" :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.title }} ↗</a></div>
      </details>
    </div>

    <div v-else-if="activeSection === 'reference'" class="api-docs-reference">
      <aside class="api-docs-index" aria-label="接口目录">
        <label class="api-docs-search">搜索接口
          <input v-model="query" type="search" placeholder="函数、参数、中文用途…" autocomplete="off">
        </label>
        <label class="api-docs-category">分类
          <select v-model="category" aria-label="分类"><option value="">全部分类</option><option v-for="group in reference.categories" :key="group.id" :value="group.id">{{ group.title }}</option></select>
        </label>
        <span class="api-docs-muted" role="status">{{ filteredEntries.length }} 个匹配</span>
        <nav class="api-docs-functions" aria-label="接口列表">
          <section v-for="group in filteredGroups" :key="group.id">
            <h3>{{ group.title }}</h3>
            <button v-for="entry in group.entries" :key="entry.name" type="button" :class="{ 'is-active': selectedEntry?.name === entry.name }"
              :aria-current="selectedEntry?.name === entry.name ? 'true' : undefined" @click="selectEntry(entry.name)">{{ entry.name }}</button>
          </section>
        </nav>
      </aside>
      <article v-if="selectedEntry" ref="contentPane" class="api-docs-scroll api-docs-detail" :key="selectedEntry.name">
        <div class="api-docs-entry-heading">
          <div><div class="api-docs-eyebrow">{{ selectedCategory.title }}</div><h2 ref="entryHeading" tabindex="-1">{{ selectedEntry.name }}</h2></div>
        </div>
        <p>{{ selectedEntry.summary }}</p>
        <h3>使用示例</h3>
        <div class="api-docs-example">
          <div class="api-docs-code-header"><span>Python</span><button type="button" @click="copyCode(selectedEntry.example)">复制示例</button></div>
          <pre><code>{{ selectedEntry.example }}</code></pre>
        </div>
        <h3>调用格式</h3>
        <pre class="api-docs-signature"><code>{{ selectedEntry.signature }}</code></pre>
        <h3>参数</h3>
        <div v-if="selectedEntry.parameters.length" class="api-docs-parameters" tabindex="0" aria-label="参数列表，可横向滚动">
          <table>
            <thead><tr><th scope="col">名称 / 类型</th><th scope="col">默认值</th><th scope="col">说明</th></tr></thead>
            <tbody><tr v-for="parameter in selectedEntry.parameters" :key="parameter.name">
              <th scope="row"><code>{{ parameter.name }}</code><small>{{ parameter.type }}</small><small v-if="parameter.kind === 'keyword_only'">仅关键字参数</small></th>
              <td><span v-if="parameter.required" class="api-docs-required">必填</span><code v-else>{{ parameter.default ?? '可变参数' }}</code></td>
              <td>{{ parameter.description }}</td>
            </tr></tbody>
          </table>
        </div>
        <p v-else class="api-docs-muted">不需要参数。</p>
        <h3>返回结果</h3><p class="api-docs-return">{{ selectedEntry.returns }}</p>
        <div v-if="selectedEntry.notes" class="api-docs-note"><strong>用法补充</strong><p>{{ selectedEntry.notes }}</p></div>
        <details class="api-docs-source">
          <summary>查看源码位置</summary>
          <p>{{ selectedEntry.source }}</p>
          <p>调用格式与默认值从当前安装的源码读取。</p>
        </details>
      </article>
      <div v-else class="api-docs-state"><h2>没有找到匹配接口</h2><p>尝试函数名、参数名或中文用途，也可以清除筛选。</p><button type="button" class="api-docs-button" @click="clearFilters">清除筛选</button></div>
    </div>

    <div v-else ref="contentPane" class="api-docs-scroll api-docs-versions">
      <span class="api-docs-eyebrow">VERSIONING</span><h2>当前脚本 API {{ reference.display_version }}</h2>
      <p>{{ reference.version_policy }}</p>
      <h3>待发布 / 累计改动</h3>
      <ul v-if="reference.pending_changes.length"><li v-for="change in reference.pending_changes" :key="change">{{ change }}</li></ul>
      <p v-else class="api-docs-muted">暂无待发布改动。</p>
      <article v-for="release in reference.releases" :key="release.version" class="api-docs-release">
        <h3>v{{ release.version }} <small>{{ release.date }}</small></h3><ul><li v-for="change in release.changes" :key="change">{{ change }}</li></ul>
      </article>
      <h3>程序如何读取版本？</h3>
      <div class="api-docs-example"><div class="api-docs-code-header"><span>Python</span><button type="button" @click="copyCode(versionExample)">复制查询代码</button></div><pre><code>{{ versionExample }}</code></pre></div>
      <details class="api-docs-source">
        <summary>通过 HTTP 查询版本和文档</summary>
        <p><code>GET /api/script-api/version</code> 返回版本、更新规则和变更记录。</p>
        <p><code>GET /api/script-api/reference</code> 返回完整接口文档。</p>
        <p>在当前 WebUI 地址后加上上述路径。启用访问密码时，通过 auth_token Cookie 或 X-Auth-Token 登录；未登录返回 401。</p>
        <pre class="api-docs-signature"><code>{{ versionResponseExample }}</code></pre>
      </details>
    </div>
  </template>
  <p v-if="copyMessage" class="api-docs-copy-status" role="status">{{ copyMessage }}</p>
  <textarea v-if="manualCopyText" class="api-docs-manual-copy" readonly aria-label="手动复制代码" :value="manualCopyText" @focus="$event.target.select()"></textarea>
</section>`,
  setup() {
    const { ref, computed, onMounted, onBeforeUnmount, nextTick } = Vue;
    const reference = ref(null);
    const loading = ref(false);
    const error = ref('');
    const activeSection = ref('start');
    const query = ref('');
    const category = ref('');
    const selectedName = ref('click');
    const contentPane = ref(null);
    const entryHeading = ref(null);
    const copyMessage = ref('');
    const manualCopyText = ref('');
    let requestController = null;
    let disposed = false;
    let copyGeneration = 0;
    const sections = [
      { id: 'start', title: '快速入门' },
      { id: 'reference', title: '接口参考' },
      { id: 'versions', title: '版本记录' },
    ];
    const versionExample = 'from AutoScriptor import API_VERSION, get_api_version\n\nprint(get_api_version())\nprint(API_VERSION)';
    const versionResponseExample = computed(() => JSON.stringify({
      ok: true, scope: reference.value?.scope, version: reference.value?.version,
      display_version: reference.value?.display_version,
    }, null, 2));
    const filteredEntries = computed(() => {
      const terms = query.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      return (reference.value?.entries || []).filter(entry => {
        if (category.value && entry.category !== category.value) return false;
        const searchable = [entry.name, entry.summary, entry.signature, entry.returns, entry.notes,
          ...entry.parameters.map(parameter => parameter.description)].join(' ').toLowerCase();
        return terms.every(term => searchable.includes(term));
      });
    });
    const filteredGroups = computed(() => (reference.value?.categories || []).map(group => ({
      ...group, entries: filteredEntries.value.filter(entry => entry.category === group.id),
    })).filter(group => group.entries.length));
    const selectedEntry = computed(() => filteredEntries.value.find(entry => entry.name === selectedName.value)
      || filteredEntries.value[0] || null);
    const selectedCategory = computed(() => reference.value?.categories.find(group => group.id === selectedEntry.value?.category) || {});

    function isReferencePayload(payload) {
      return payload?.ok === true && payload.scope === 'python-script-api'
        && typeof payload.version === 'string' && /^\d+\.\d+\.\d+$/.test(payload.version)
        && payload.display_version === 'v' + payload.version
        && Array.isArray(payload.categories) && payload.categories.length > 0
        && Array.isArray(payload.entries) && payload.entries.length > 0
        && payload.entries.every(entry => typeof entry.name === 'string' && typeof entry.signature === 'string' && Array.isArray(entry.parameters))
        && Array.isArray(payload.quickstart?.steps) && typeof payload.quickstart.code === 'string'
        && Array.isArray(payload.guidance) && Array.isArray(payload.references)
        && Array.isArray(payload.releases) && Array.isArray(payload.pending_changes);
    }

    async function loadReference() {
      if (disposed) return;
      requestController?.abort();
      const controller = new AbortController();
      requestController = controller;
      loading.value = true;
      error.value = '';
      reference.value = null;
      clearCopyStatus();
      try {
        const response = await window.WebUIApi.request('GET', '/script-api/reference', undefined, {
          signal: controller.signal, cache: 'no-store',
        });
        if (disposed || requestController !== controller) return;
        if (!response.ok || response.data?.ok === false) {
          const message = response.status === 401 ? '请先登录 WebUI，然后重试。' : '读取 API 文档失败';
          throw new Error(response.status === 401 ? message : window.WebUIApi.errorMessage(response.data, message));
        }
        if (!isReferencePayload(response.data)) throw new Error('文档数据不完整，请更新并重启后端后重试。');
        reference.value = response.data;
      } catch (failure) {
        if (!disposed && requestController === controller && !controller.signal.aborted) error.value = failure.message || String(failure);
      } finally {
        if (!disposed && requestController === controller) loading.value = false;
      }
    }

    function clearCopyStatus() {
      copyGeneration += 1;
      copyMessage.value = '';
      manualCopyText.value = '';
    }

    function showSection(section) {
      activeSection.value = section;
      clearCopyStatus();
      nextTick(() => { if (contentPane.value) contentPane.value.scrollTop = 0; });
    }

    function clearFilters() {
      query.value = '';
      category.value = '';
    }

    function selectEntry(name) {
      selectedName.value = name;
      clearCopyStatus();
      nextTick(() => {
        if (contentPane.value) contentPane.value.scrollTop = 0;
        entryHeading.value?.focus({ preventScroll: true });
      });
    }

    function openApi(name) {
      clearFilters();
      activeSection.value = 'reference';
      selectEntry(name);
    }

    async function copyCode(code) {
      clearCopyStatus();
      const generation = copyGeneration;
      try {
        if (!navigator.clipboard?.writeText) throw new Error('Clipboard unavailable');
        await navigator.clipboard.writeText(code);
        if (!disposed && generation === copyGeneration) copyMessage.value = '代码已复制';
      } catch (_) {
        if (!disposed && generation === copyGeneration) {
          copyMessage.value = '剪贴板不可用，请在下方文本框中手动复制。';
          manualCopyText.value = code;
        }
      }
    }

    onMounted(loadReference);
    onBeforeUnmount(() => {
      disposed = true;
      copyGeneration += 1;
      requestController?.abort();
    });
    return {
      reference, loading, error, activeSection, query, category, contentPane, entryHeading,
      copyMessage, manualCopyText, sections, versionExample, versionResponseExample,
      filteredEntries, filteredGroups, selectedEntry, selectedCategory,
      loadReference, showSection, clearFilters, selectEntry, openApi, copyCode,
    };
  },
};
