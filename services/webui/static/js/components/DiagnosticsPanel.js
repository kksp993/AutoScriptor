const DIAGNOSTIC_LABELS = {
  manager: 'MuMuManager',
  adb: 'ADB',
  adb_device: 'ADB 设备',
  app: 'App',
  nemu_ipc: 'NemuIpc 截图',
  ocr: 'OCR',
  ui_map: 'UI Map',
};

const DiagnosticsPanel = {
  name: 'DiagnosticsPanel',
  data() {
    return {
      loading: false,
      diagnostics: null,
      lastError: '',
    };
  },
  computed: {
    checkEntries() {
      const checks = (this.diagnostics && this.diagnostics.checks) || {};
      return Object.entries(DIAGNOSTIC_LABELS).map(([key, label]) => ({
        key,
        label,
        check: checks[key] || { status: 'skipped', message: '未返回状态' },
      }));
    },
    overall() {
      return (this.diagnostics && this.diagnostics.overall) || { status: 'skipped', message: '尚未诊断' };
    },
    generatedAt() {
      const ts = this.diagnostics && this.diagnostics.generated_at;
      return ts ? new Date(ts * 1000).toLocaleString() : '尚未刷新';
    },
  },
  mounted() {
    this.refresh(false);
  },
  methods: {
    async refresh(includeScreenshot) {
      this.loading = true;
      this.lastError = '';
      try {
        const suffix = includeScreenshot ? '?screenshot=true' : '';
        const result = await window.WebUIApi.request('GET', '/device/diagnostics' + suffix);
        const payload = result.data || {};
        if (!result.ok || payload.ok === false) {
          this.lastError = window.WebUIApi.errorMessage(payload, '启动诊断失败');
          return;
        }
        this.diagnostics = payload.diagnostics || null;
      } catch (e) {
        this.lastError = '启动诊断失败: ' + e;
      } finally {
        this.loading = false;
      }
    },
    statusType(status) {
      return {
        ok: 'success',
        warn: 'warning',
        error: 'danger',
        skipped: 'info',
      }[status] || 'info';
    },
    statusText(status) {
      return {
        ok: '正常',
        warn: '注意',
        error: '异常',
        skipped: '未检查',
      }[status] || status || '未知';
    },
    detailPairs(check) {
      return Object.entries(check || {})
        .filter(([key, value]) => !['status', 'message'].includes(key) && value !== '' && value !== null && value !== undefined)
        .map(([key, value]) => ({
          key,
          value: Array.isArray(value) ? value.join(' x ') : String(value),
        }));
    },
  },
  template: `
<section class="flex-1 min-h-0 overflow-auto">
  <div class="max-w-6xl mx-auto space-y-4">
    <div class="bg-white rounded-2xl shadow-sm border border-slate-100 p-5 flex flex-col md:flex-row md:items-center md:justify-between gap-4">
      <div>
        <div class="text-xl font-semibold text-slate-800 flex items-center gap-2">
          <i class="fa fa-stethoscope text-green-600"></i>
          启动诊断
        </div>
        <p class="text-sm text-slate-500 mt-1">
          分层检查 MuMuManager、ADB、App、NemuIpc、OCR 与 UI Map。默认不做截图探测，避免无谓打扰模拟器。
        </p>
      </div>
      <div class="flex items-center gap-2">
        <el-button :loading="loading" @click="refresh(false)">
          <i class="fa fa-refresh mr-1"></i>刷新
        </el-button>
        <el-button type="primary" :loading="loading" @click="refresh(true)">
          <i class="fa fa-camera mr-1"></i>截图探测
        </el-button>
      </div>
    </div>

    <el-alert v-if="lastError" type="error" :closable="false" :title="lastError"></el-alert>

    <div class="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
      <div class="flex flex-col md:flex-row md:items-center md:justify-between gap-3">
        <div>
          <div class="text-sm text-slate-500">整体状态</div>
          <div class="text-lg font-semibold text-slate-800">{{ overall.message }}</div>
        </div>
        <div class="flex flex-wrap items-center gap-2 text-sm text-slate-500">
          <el-tag :type="statusType(overall.status)" size="large">{{ statusText(overall.status) }}</el-tag>
          <span>实例: {{ diagnostics && diagnostics.emulator_index || '-' }}</span>
          <span>ADB: {{ diagnostics && diagnostics.adb_addr || '-' }}</span>
          <span>刷新: {{ generatedAt }}</span>
        </div>
      </div>
    </div>

    <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
      <div v-for="item in checkEntries" :key="item.key"
           class="bg-white rounded-2xl shadow-sm border border-slate-100 p-5">
        <div class="flex items-start justify-between gap-3">
          <div>
            <div class="font-semibold text-slate-800">{{ item.label }}</div>
            <div class="text-sm text-slate-500 mt-1 leading-relaxed">{{ item.check.message }}</div>
          </div>
          <el-tag :type="statusType(item.check.status)">{{ statusText(item.check.status) }}</el-tag>
        </div>
        <div v-if="detailPairs(item.check).length" class="mt-4 space-y-1.5 text-xs text-slate-500">
          <div v-for="row in detailPairs(item.check)" :key="row.key" class="flex gap-2">
            <span class="w-24 flex-shrink-0 text-slate-400">{{ row.key }}</span>
            <span class="break-all">{{ row.value }}</span>
          </div>
        </div>
      </div>
    </div>
  </div>
</section>`,
};
