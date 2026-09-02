const DIAGNOSTIC_LABELS = {
  manager: 'MuMuManager 管理器',
  adb: 'ADB 程序',
  adb_device: 'ADB 设备连接',
  app: '游戏 App',
  nemu_ipc: '截图通道',
  ocr: 'OCR 文字识别',
  ui_map: 'UI 模板库',
};

const DIAGNOSTIC_DETAIL_LABELS = {
  path: '路径',
  exists: '文件存在',
  version: '版本',
  returncode: '返回码',
  detail: '原始输出',
  serial: 'ADB 地址',
  reconnect: '自动连接',
  connected_devices: '已连接设备',
  fallback_serial: '可用 ADB',
  suggested_adb_addr: '建议 ADB 地址',
  configured_index: '配置实例',
  detected_index: '检测实例',
  configured_running: '配置实例运行',
  detected_running: '检测实例运行',
  boot_completed: '启动完成',
  package: '包名',
  running: '运行中',
  elapsed_ms: '耗时',
  shape: '截图尺寸',
  use_gpu: 'GPU',
  configured_use_gpu: '配置使用 GPU',
  engine_use_gpu: '引擎使用 GPU',
  engine_device: '引擎设备',
  restart_required: '需要重启',
  entries: '条目数',
};

const DiagnosticsPanel = {
  name: 'DiagnosticsPanel',
  props: {
    embedded: { type: Boolean, default: false },
  },
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
    deviceOverall() {
      return (this.diagnostics && this.diagnostics.device_overall) || this.overall;
    },
    taskOverall() {
      return (this.diagnostics && this.diagnostics.task_overall) || this.overall;
    },
    generatedAt() {
      const ts = this.diagnostics && this.diagnostics.generated_at;
      return ts ? new Date(ts * 1000).toLocaleString() : '尚未刷新';
    },
    rootClass() {
      return this.embedded ? 'diagnostics-panel diagnostics-panel--embedded' : 'diagnostics-panel diagnostics-panel--standalone';
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
        const params = new URLSearchParams();
        if (includeScreenshot) params.set('screenshot', 'true');
        params.set('require_app', 'false');
        const suffix = '?' + params.toString();
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
    messageFor(item) {
      const check = item.check || {};
      if (item.key === 'manager' && check.status === 'warn') {
        return 'MuMuManager 命令异常；ADB 正常时仍可点击、输入和检测 App，但自动启动、关闭、窗口管理可能受影响。';
      }
      if (item.key === 'manager' && check.status === 'error') {
        return '未找到可用 MuMuManager；手动打开模拟器且 ADB 正常时任务仍可能运行，但无法自动启动/关闭模拟器。';
      }
      if (item.key === 'nemu_ipc' && check.status === 'skipped') {
        return '默认不主动截图。需要确认截图链路时，点击右侧“截图探测”。';
      }
      return check.message || '未返回状态';
    },
    formatValue(value) {
      if (Array.isArray(value)) return value.join(' x ');
      if (typeof value === 'boolean') return value ? '是' : '否';
      if (value && typeof value === 'object') return JSON.stringify(value);
      const text = String(value);
      return text.length > 160 ? text.slice(0, 160) + '...' : text;
    },
    detailPairs(check) {
      return Object.entries(check || {})
        .filter(([key, value]) => !['status', 'message'].includes(key) && value !== '' && value !== null && value !== undefined)
        .map(([key, value]) => ({
          key,
          label: DIAGNOSTIC_DETAIL_LABELS[key] || key,
          raw: Array.isArray(value) ? value.join(' x ') : String(value),
          value: this.formatValue(value),
        }));
    },
  },
  template: `
<section :class="rootClass">
  <div class="diagnostics-head">
    <div>
      <div class="diagnostics-kicker">连接体检</div>
      <h3><i class="fa fa-stethoscope"></i>启动诊断</h3>
      <p>分层检查 MuMuManager、ADB、App、截图、OCR 与 UI 模板。默认轻量检查，不会主动读取模拟器截图。</p>
    </div>
    <div class="diagnostics-actions">
      <el-button :loading="loading" @click="refresh(false)">
        <i class="fa fa-refresh mr-1"></i>刷新
      </el-button>
      <el-button type="primary" :loading="loading" @click="refresh(true)">
        <i class="fa fa-camera mr-1"></i>截图探测
      </el-button>
    </div>
  </div>

  <el-alert v-if="lastError" type="error" :closable="false" :title="lastError" class="diagnostics-alert"></el-alert>

  <div class="diagnostics-summary">
    <div>
      <div class="diagnostics-summary-label">整体状态</div>
      <div class="diagnostics-summary-message">{{ overall.message }}</div>
    </div>
    <div class="diagnostics-summary-meta">
      <el-tag :type="statusType(overall.status)" size="large">{{ statusText(overall.status) }}</el-tag>
      <el-tag :type="statusType(deviceOverall.status)">设备: {{ statusText(deviceOverall.status) }}</el-tag>
      <el-tag :type="statusType(taskOverall.status)">任务: {{ statusText(taskOverall.status) }}</el-tag>
      <span>实例: {{ diagnostics && diagnostics.emulator_index || '-' }}</span>
      <span>ADB: {{ diagnostics && diagnostics.adb_addr || '-' }}</span>
      <span>刷新: {{ generatedAt }}</span>
    </div>
  </div>

  <div class="diagnostics-grid">
    <article v-for="item in checkEntries" :key="item.key" class="diagnostics-card">
      <div class="diagnostics-card-top">
        <div>
          <div class="diagnostics-card-title">{{ item.label }}</div>
          <p>{{ messageFor(item) }}</p>
        </div>
        <el-tag :type="statusType(item.check.status)">{{ statusText(item.check.status) }}</el-tag>
      </div>
      <div v-if="detailPairs(item.check).length" class="diagnostics-detail-list">
        <div v-for="row in detailPairs(item.check)" :key="row.key" class="diagnostics-detail-row">
          <span class="diagnostics-detail-key">{{ row.label }}</span>
          <span class="diagnostics-detail-value" :title="row.raw">{{ row.value }}</span>
        </div>
      </div>
    </article>
  </div>
</section>`,
};
