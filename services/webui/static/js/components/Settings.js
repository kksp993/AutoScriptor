const SETTINGS_SERVER_PACKAGES = [
  { label: '4399官服', value: 'org.yjmobile.zmxy' },
  { label: '9游服务器', value: 'com.zmxyol.union.uc' },
  { label: '当乐服务器', value: 'com.zmxyol.union.dn' },
  { label: 'Vivo服务器', value: 'com.sy4399.zmxyol.vivo' },
];

const SETTINGS_POST_EXECUTION_OPTIONS = [
  { label: '什么都不做', value: 'none' },
  { label: '关闭模拟器', value: 'close_mumu' },
  { label: '仅关闭游戏', value: 'close_game_only' },
  { label: '回到主界面', value: 'goto_main' },
];

const SettingsPanel = {
  name: 'SettingsPanel',
  props: {
    filteredConfig: { type: Object, required: true },
    executionBusy: { type: Boolean, default: false },
  },
  emits: ['save-settings'],
  data() {
    return {
      MUMU_ADB_BASE_PORT: 16384,
      MUMU_ADB_PORT_STEP: 32,
      serverPackages: SETTINGS_SERVER_PACKAGES,
      postExecutionOptions: SETTINGS_POST_EXECUTION_OPTIONS,
    };
  },
  computed: {
    appConfig() {
      return this.filteredConfig.app || {};
    },
    ocrConfig() {
      return this.filteredConfig.ocr || {};
    },
    emulatorConfig() {
      return this.filteredConfig.emulator || {};
    },
    schedulerConfig() {
      return this.filteredConfig.scheduler || {};
    },
    hasOcrScale() {
      return Object.prototype.hasOwnProperty.call(this.ocrConfig, 'scale');
    },
  },
  methods: {
    syncAdbPortFromIndex(index) {
      const n = Number(index);
      if (!Number.isFinite(n) || n < 0) return;
      const port = this.MUMU_ADB_BASE_PORT + n * this.MUMU_ADB_PORT_STEP;
      const addr = String(this.emulatorConfig.adb_addr || '').trim();
      if (!addr || addr.startsWith('YOUR_')) {
        this.emulatorConfig.adb_addr = `127.0.0.1:${port}`;
        return;
      }
      const colon = addr.lastIndexOf(':');
      this.emulatorConfig.adb_addr = colon >= 0 ? `${addr.slice(0, colon + 1)}${port}` : `127.0.0.1:${port}`;
    },
    serverOptionsFor(currentValue) {
      if (currentValue && !this.serverPackages.some((o) => o.value === currentValue)) {
        return [...this.serverPackages, { label: `其他 (${currentValue})`, value: currentValue }];
      }
      return this.serverPackages;
    },
    saveAllSettings() {
      if (this.executionBusy) {
        ElementPlus.ElMessage.warning('执行中不能保存设置，请先终止当前任务');
        return;
      }
      this.$emit('save-settings');
    },
  },
  template: `
<section class="settings-page h-full overflow-y-auto">
  <div class="settings-hero">
    <div>
      <h2 class="settings-title">运行配置</h2>
    </div>
    <el-button type="primary" size="large" @click="saveAllSettings" :disabled="executionBusy">
      <i class="fa fa-save mr-1"></i>保存设置
    </el-button>
  </div>

  <el-alert v-if="executionBusy" type="warning" :closable="false" show-icon class="settings-busy-alert"
    title="任务执行中不能保存设置"
    description="请先停止当前任务，再保存运行配置。"></el-alert>

  <el-form :model="filteredConfig" :disabled="executionBusy" label-position="top" class="settings-form">
    <div class="settings-grid settings-grid--two">
      <article class="settings-card">
        <div class="settings-card-head">
          <div>
            <h3><i class="fa fa-play-circle"></i>运行方式</h3>
          </div>
        </div>

        <div class="settings-field-row">
          <div class="settings-field-text">
            <div class="settings-field-title">模拟器后台运行</div>
          </div>
          <el-switch v-model="appConfig.run_in_background" />
        </div>

        <div class="settings-field-row">
          <div class="settings-field-text">
            <div class="settings-field-title">失败后重启模拟器</div>
          </div>
          <el-switch v-model="appConfig.restart_on_error" />
        </div>

        <div class="settings-field-grid">
          <el-form-item label="最大重试次数">
            <el-input-number v-model="appConfig.max_retry" :min="0" :max="10" controls-position="right" />
          </el-form-item>
          <el-form-item label="执行结束后">
            <el-select v-model="emulatorConfig.post_execution" style="width:100%">
              <el-option v-for="opt in postExecutionOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
          </el-form-item>
        <el-form-item label="MuMu 多开编号">
          <el-input-number v-model="emulatorConfig.index" :min="0" :max="99" controls-position="right" @change="syncAdbPortFromIndex" />
        </el-form-item>
        
        <el-form-item label="ADB 连接地址">
          <el-input v-model="emulatorConfig.adb_addr" placeholder="例如 127.0.0.1:16416" :disabled="true" style="background:#f5f5f5;color:#888;" />
        </el-form-item>
        </div>
        <el-form-item label="CPU 核心限制">
          <el-input-number v-model="appConfig.cpu_cores" :min="0" :max="64" controls-position="right" />
        </el-form-item>
      </article>

      <article class="settings-card">
        <div class="settings-card-head">
          <div>
            <h3><i class="fa fa-desktop"></i>模拟器连接</h3>
          </div>
        </div>

        <div class="settings-field-grid">
          <el-form-item label="游戏服务器">
            <el-select v-model="appConfig.app_to_start" placeholder="请选择服务器" style="width:100%">
              <el-option v-for="opt in serverOptionsFor(appConfig.app_to_start)" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
          </el-form-item>

        </div>


        <el-form-item label="MuMu 安装目录">
          <el-input v-model="emulatorConfig.mumu_folder" placeholder="例如 C:\\Program Files\\Netease\\MuMu" />
          <div class="settings-help">截图探测会用到 MuMu 安装目录下的 NemuIpc 组件。</div>
        </el-form-item>

        <el-form-item label="MuMuManager 路径">
          <el-input v-model="emulatorConfig.emu_path" placeholder="例如 ...\\nx_main\\MuMuManager.exe" />
          <div class="settings-help">只负责启动、关闭、窗口等官方管理动作；日常点击输入不会依赖它。</div>
        </el-form-item>

        <el-form-item label="ADB 程序路径">
          <el-input v-model="emulatorConfig.adb_path" placeholder="例如 ...\\nx_main\\adb.exe" />
          <div class="settings-help">这是最关键的控制通道，路径错误会直接导致无法点击、无法检测 App。</div>
        </el-form-item>
      </article>
    </div>
  </el-form>

  <diagnostics-panel embedded></diagnostics-panel>

  <div class="settings-footer-save">
    <el-button type="primary" size="large" @click="saveAllSettings" :disabled="executionBusy">
      <i class="fa fa-save mr-1"></i>保存设置
    </el-button>
  </div>
</section>`,
};
