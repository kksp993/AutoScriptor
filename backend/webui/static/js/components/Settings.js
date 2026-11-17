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

// deploy.log_level 直接对应 logging 的级别名，后端按该名字取级别限制浏览器日志。
const SETTINGS_LOG_LEVELS = [
  { label: '调试 (debug)', value: 'debug' },
  { label: '常规 (info)', value: 'info' },
  { label: '警告 (warning)', value: 'warning' },
  { label: '错误 (error)', value: 'error' },
];

const SettingsPanel = {
  name: 'SettingsPanel',
  components: { NotificationsPanel },
  props: {
    filteredConfig: { type: Object, required: true },
    executionBusy: { type: Boolean, default: false },
  },
  emits: ['settings-change', 'deploy-saved'],
  data() {
    return {
      MUMU_ADB_BASE_PORT: 16384,
      MUMU_ADB_PORT_STEP: 32,
      serverPackages: SETTINGS_SERVER_PACKAGES,
      postExecutionOptions: SETTINGS_POST_EXECUTION_OPTIONS,
      logLevelOptions: SETTINGS_LOG_LEVELS,
      saveTimer: null,
      lastSyncedSignature: '',
      lastSyncedConfigVersion: null,
      lastQueuedSignature: '',
      pendingInitialSave: false,
      saving: false,
      savedAt: 0,
      discovering: false,
      discoveryMessage: '',
      diagnosticsOpened: false,
      // deploy 段不走自动保存：密码涉及安全，必须显式点保存。
      deployBase: {},
      deployForm: { log_level: 'info', password: '', current_password: '' },
      deployHasPassword: false,
      deployLoaded: false,
      deploySaving: false,
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
    /** 空值表示合法；非空时把原始原因直接显示在字段下方。 */
    adbAddrError() {
      const raw = String(this.emulatorConfig.adb_addr || '').trim();
      if (!raw) return 'ADB 连接地址不能为空';
      if (raw.startsWith('YOUR_')) return '请填写真实地址，例如 127.0.0.1:16416';
      const colon = raw.lastIndexOf(':');
      if (colon <= 0) return '格式应为 主机:端口，例如 127.0.0.1:16416';
      const host = raw.slice(0, colon).trim();
      const portText = raw.slice(colon + 1).trim();
      if (!host) return '主机部分不能为空';
      if (!/^\d+$/.test(portText)) return '端口必须是数字';
      const port = Number(portText);
      if (port < 1 || port > 65535) return '端口范围是 1-65535';
      if (portText.length > 1 && portText.startsWith('0')) return '端口不能以 0 开头';
      return '';
    },
    syncStatusText() {
      if (this.adbAddrError) return 'ADB 连接地址无效，已暂停自动保存';
      if (this.executionBusy) return '执行中暂停自动保存';
      if (this.saving) return '正在同步配置...';
      if (this.savedAt) return '配置已同步到本地文件';
      return '修改后自动保存';
    },
  },
  watch: {
    'emulatorConfig.adb_addr': {
      immediate: true,
      handler() {
        this.ensureDefaultAdbAddr();
      },
    },
    'emulatorConfig.index': {
      immediate: true,
      handler() {
        this.ensureDefaultAdbAddr();
      },
    },
    /**
     * 自动保存：服务端刷新只更新基线，用户改动才排队保存。
     * 用 config_version 区分两种来源，避免保存后刷新把同一份配置再存一次。
     */
    filteredConfig: {
      deep: true,
      immediate: true,
      handler() {
        const version = Number(this.filteredConfig.config_version || 0);
        if (version !== this.lastSyncedConfigVersion) {
          this.lastSyncedConfigVersion = version;
          this.lastSyncedSignature = this.currentSettingsSignature();
          // 服务端仍是占位地址时，本地规范化出来的值也必须真正落盘。
          if (this.pendingInitialSave) {
            this.pendingInitialSave = false;
            this.queueSave();
          }
          return;
        }
        const signature = this.currentSettingsSignature();
        if (signature === this.lastSyncedSignature) return;
        this.queueSave();
      },
    },
  },
  beforeUnmount() {
    if (this.saveTimer) clearTimeout(this.saveTimer);
  },
  mounted() {
    this.loadDeploySettings();
  },
  methods: {
    currentSettingsSignature() {
      return JSON.stringify({
        app: this.appConfig,
        emulator: this.emulatorConfig,
        ocr: this.ocrConfig,
        scheduler: this.schedulerConfig,
      });
    },
    defaultAdbAddrForIndex(index) {
      const n = Number(index);
      const safeIndex = Number.isFinite(n) && n >= 0 ? n : 0;
      const port = this.MUMU_ADB_BASE_PORT + safeIndex * this.MUMU_ADB_PORT_STEP;
      return `127.0.0.1:${port}`;
    },
    ensureDefaultAdbAddr() {
      if (!this.emulatorConfig || typeof this.emulatorConfig !== 'object') return;
      const addr = String(this.emulatorConfig.adb_addr || '').trim();
      if (!addr || addr.startsWith('YOUR_') || addr.endsWith(':0')) {
        this.emulatorConfig.adb_addr = this.defaultAdbAddrForIndex(this.emulatorConfig.index);
        this.pendingInitialSave = true;
      }
    },
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
    queueSave() {
      // 地址非法时不落盘，让用户先改对再同步。
      if (this.executionBusy || this.saving || this.adbAddrError) {
        return;
      }
      if (this.saveTimer) clearTimeout(this.saveTimer);
      this.saveTimer = setTimeout(() => {
        this.saveTimer = null;
        if (this.executionBusy || this.adbAddrError) return;
        // 保存期间的新改动由 onSaved 用签名比较补发，避免并发 POST 覆盖。
        if (this.saving) return;
        this.lastQueuedSignature = this.currentSettingsSignature();
        this.saving = true;
        this.$emit('settings-change', { silent: true, done: this.onSaved });
      }, 500);
    },
    async autoDiscoverMumu() {
      if (this.executionBusy) {
        ElementPlus.ElMessage.warning('执行中不能修改模拟器配置，请先终止当前任务');
        return;
      }
      this.discovering = true;
      this.discoveryMessage = '';
      try {
        const result = await window.WebUIApi.request('GET', '/device/discover?probe_adb=true');
        const payload = result.data || {};
        if (!result.ok || payload.ok === false) {
          ElementPlus.ElMessage.error(window.WebUIApi.errorMessage(payload, '自动定位失败'));
          return;
        }
        const discovery = payload.discovery || {};
        if (discovery.needs_manual_paths) {
          this.discoveryMessage = `未找到完整 MuMu 路径，已扫描 ${discovery.candidate_count || 0} 个候选目录`;
          ElementPlus.ElMessage.warning(this.discoveryMessage);
          return;
        }
        Object.assign(this.emulatorConfig, discovery.emulator || {});
        const apply = await window.WebUIApi.request('POST', '/device/discover/apply', { emulator: this.emulatorConfig });
        const applyPayload = apply.data || {};
        if (!apply.ok || applyPayload.ok === false) {
          ElementPlus.ElMessage.error(window.WebUIApi.errorMessage(applyPayload, '应用自动定位结果失败'));
          return;
        }
        this.discoveryMessage = discovery.adb_device && discovery.adb_device.connected
          ? `已定位 MuMu，并连接 ${discovery.adb_device.serial}`
          : '已定位 MuMu 路径，启动模拟器后可刷新诊断';
        this.savedAt = Date.now();
        ElementPlus.ElMessage.success(this.discoveryMessage);
      } catch (e) {
        ElementPlus.ElMessage.error('自动定位失败: ' + e);
      } finally {
        this.discovering = false;
      }
    },
    async loadDeploySettings() {
      try {
        const result = await window.WebUIApi.request('GET', '/deploy');
        const payload = result.data || {};
        if (!result.ok) {
          ElementPlus.ElMessage.error(window.WebUIApi.errorMessage(payload, '读取 WebUI 访问设置失败'));
          return;
        }
        const deploy = payload.deploy || {};
        // 保留 ssl_key/ssl_cert 等本页不编辑的字段：后端保存时是整段替换。
        this.deployBase = { ...deploy };
        delete this.deployBase.password;
        this.deployForm.log_level = String(deploy.log_level || 'info');
        this.deployHasPassword = !!payload.password_protected;
        this.deployLoaded = true;
      } catch (e) {
        ElementPlus.ElMessage.error('读取 WebUI 访问设置失败: ' + e);
      }
    },
    async saveDeploySettings() {
      return this.submitDeploySettings(false);
    },
    async clearDeployPassword() {
      return this.submitDeploySettings(true);
    },
    /**
     * deploy 段的保存规则（与后端 /api/deploy 一致）：
     * - password 省略 = 清除密码，需要当前密码；
     * - password 为空字符串 = 保持原密码不变；
     * - password 非空 = 设置/修改密码，已有密码时也要当前密码。
     */
    async submitDeploySettings(clearPassword) {
      if (this.executionBusy) {
        ElementPlus.ElMessage.warning('执行中不能修改 WebUI 访问设置，请先终止当前任务');
        return;
      }
      const newPassword = String(this.deployForm.password || '').trim();
      const currentPassword = String(this.deployForm.current_password || '').trim();
      const deploy = { ...this.deployBase, log_level: this.deployForm.log_level };
      if (clearPassword) {
        if (!currentPassword) {
          ElementPlus.ElMessage.warning('清除访问密码需要先填写当前密码');
          return;
        }
      } else {
        deploy.password = newPassword;
      }
      if (this.deployHasPassword) {
        deploy.current_password = currentPassword;
      }
      const enablingProtection = !clearPassword && !!newPassword && !this.deployHasPassword;
      this.deploySaving = true;
      try {
        const result = await window.WebUIApi.request('POST', '/deploy', { deploy });
        const payload = result.data || {};
        if (!result.ok || payload.ok === false) {
          ElementPlus.ElMessage.error(window.WebUIApi.errorMessage(payload, '保存 WebUI 访问设置失败'));
          return;
        }
        this.deployForm.password = '';
        this.deployForm.current_password = '';
        await this.loadDeploySettings();
        this.$emit('deploy-saved');
        if (clearPassword) {
          ElementPlus.ElMessage.success('已清除访问密码');
        } else if (enablingProtection) {
          ElementPlus.ElMessage.success('已启用访问密码，页面会要求重新登录');
        } else {
          ElementPlus.ElMessage.success('WebUI 访问设置已保存');
        }
      } catch (e) {
        ElementPlus.ElMessage.error('保存 WebUI 访问设置失败: ' + e);
      } finally {
        this.deploySaving = false;
      }
    },
    onSaved(ok) {
      this.saving = false;
      if (ok) {
        this.savedAt = Date.now();
        // 请求在途期间的改动没有被提交，这里补发一次让界面与文件收敛。
        if (this.currentSettingsSignature() !== this.lastQueuedSignature) this.queueSave();
      }
    },
  },
  template: `
<section class="settings-page settings-unified h-full overflow-y-auto">
  <div class="settings-hero">
    <div>
      <h2 class="settings-title">设置</h2>
      <p class="settings-help">连接设备、运行任务、接收通知。</p>
    </div>
    <span class="settings-save-status" role="status">{{ syncStatusText }}</span>
  </div>

  <el-alert v-if="executionBusy" type="warning" :closable="false" show-icon class="settings-busy-alert"
    title="任务执行中不能保存设置"
    description="请先停止当前任务，再保存运行配置。"></el-alert>

  <el-form :model="filteredConfig" :disabled="executionBusy" label-position="top" class="settings-form">
    <div class="settings-grid settings-grid--two settings-primary-grid">
      <article class="settings-card settings-primary-card" aria-label="模拟器连接">
        <div class="settings-card-head">
          <h3><i class="fa fa-desktop" aria-hidden="true"></i>模拟器连接</h3>
          <el-button size="small" type="primary" plain :loading="discovering" @click="autoDiscoverMumu">自动定位 MuMu</el-button>
        </div>
        <el-alert v-if="discoveryMessage" type="info" :closable="false" :title="discoveryMessage"></el-alert>
        <div class="settings-field-grid">
          <el-form-item label="游戏服务器">
            <el-select v-model="appConfig.app_to_start" aria-label="游戏服务器" style="width:100%">
              <el-option v-for="opt in serverOptionsFor(appConfig.app_to_start)" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="MuMu 多开编号">
            <el-input-number v-model="emulatorConfig.index" aria-label="MuMu 多开编号" :min="0" :max="99" controls-position="right" @change="syncAdbPortFromIndex" />
          </el-form-item>
        </div>
        <el-form-item label="ADB 连接地址">
          <el-input v-model="emulatorConfig.adb_addr" aria-label="ADB 连接地址" placeholder="127.0.0.1:16416" clearable />
          <div v-if="adbAddrError" class="settings-help settings-help--error">{{ adbAddrError }}</div>
          <div v-else class="settings-help">按多开编号推导，也可手动填写主机:端口。</div>
        </el-form-item>
        <details class="settings-details settings-card-footer">
          <summary>手动配置路径<span>自动定位失败时使用</span></summary>
          <el-form-item label="MuMu 安装目录">
            <el-input v-model="emulatorConfig.mumu_folder" aria-label="MuMu 安装目录" placeholder="MuMu 安装目录" />
          </el-form-item>
          <el-form-item label="MuMuManager 路径">
            <el-input v-model="emulatorConfig.emu_path" aria-label="MuMuManager 路径" placeholder="MuMuManager.exe 完整路径" />
            <div class="settings-help">只负责启动、关闭、窗口等官方管理动作。</div>
          </el-form-item>
          <el-form-item label="ADB 程序路径">
            <el-input v-model="emulatorConfig.adb_path" aria-label="ADB 程序路径" placeholder="adb.exe 完整路径" />
          </el-form-item>
        </details>
      </article>

      <article class="settings-card settings-primary-card" aria-label="任务运行">
        <div class="settings-card-head">
          <h3><i class="fa fa-play-circle" aria-hidden="true"></i>任务运行</h3>
          <span class="settings-section-note">自动保存</span>
        </div>
        <div class="settings-field-grid">
          <el-form-item label="最多尝试次数">
            <el-input-number v-model="appConfig.max_attempts" aria-label="最多尝试次数" :min="1" :max="10" controls-position="right" />
            <div class="settings-help">含首次执行。</div>
          </el-form-item>
          <el-form-item label="执行结束后">
            <el-select v-model="emulatorConfig.post_execution" aria-label="执行结束后" style="width:100%">
              <el-option v-for="opt in postExecutionOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
          </el-form-item>
        </div>
        <div class="settings-field-row">
          <span class="settings-field-title">模拟器后台运行</span>
          <el-switch v-model="appConfig.run_in_background" aria-label="模拟器后台运行" />
        </div>
        <div class="settings-field-row">
          <span class="settings-field-title">失败后自动恢复</span>
          <el-switch v-model="appConfig.restart_on_error" aria-label="失败后自动恢复" />
        </div>
        <details class="settings-details settings-card-footer">
          <summary>识别与性能<span>GPU、CPU 选项</span></summary>
          <div class="settings-field-row">
            <span class="settings-field-title">OCR 使用 GPU</span>
            <el-switch v-model="ocrConfig.use_gpu" aria-label="OCR 使用 GPU" />
          </div>
          <p class="settings-help">先运行 scripts\\install.bat python gpu，保存后重启 AutoScriptor。</p>
          <el-form-item label="CPU 核心限制">
            <el-input-number v-model="appConfig.cpu_cores" aria-label="CPU 核心限制" :min="0" :max="64" controls-position="right" />
          </el-form-item>
          <p class="settings-help">后台运行：任务开始时自动启动模拟器和游戏；它不是“兼容性越高越慢”的开关。</p>
        </details>
      </article>
    </div>
  </el-form>

  <notifications-panel embedded :execution-busy="executionBusy"></notifications-panel>

  <details class="settings-card settings-details settings-access">
    <summary>WebUI 访问与日志<span>{{ deployHasPassword ? '密码保护已开启' : '仅浏览器设置' }}</span></summary>
    <el-button v-if="!deployLoaded" size="small" @click="loadDeploySettings">重新加载访问设置</el-button>
    <el-form :disabled="executionBusy || !deployLoaded" label-position="top">
      <div class="settings-field-grid">
        <el-form-item label="日志级别">
          <el-select v-model="deployForm.log_level" style="width:100%">
            <el-option v-for="opt in logLevelOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
          </el-select>
          <div class="settings-help">只限制浏览器日志面板显示到哪一级，后端日志文件不受影响。</div>
        </el-form-item>

        <el-form-item :label="deployHasPassword ? '新访问密码' : '设置访问密码'">
          <el-input v-model="deployForm.password" type="password" show-password clearable
            :placeholder="deployHasPassword ? '留空则不修改' : '留空则继续不设密码'" />
        </el-form-item>

        <el-form-item v-if="deployHasPassword" label="当前密码">
          <el-input v-model="deployForm.current_password" type="password" show-password clearable
            placeholder="修改或清除密码需要先验证" />
          <div class="settings-help">设置密码后打开 WebUI 需要登录；忘记密码可在 data/config.json 里清空 deploy.password。</div>
        </el-form-item>

      </div>
      <p class="settings-help">访问密码和日志级别需手动保存，不影响运行设置与 QQ 通知。</p>
      <div class="settings-deploy-actions">
        <el-button size="small" :disabled="executionBusy || !deployHasPassword || deploySaving"
          @click="clearDeployPassword">清除密码</el-button>
        <el-button type="primary" :loading="deploySaving" :disabled="executionBusy || !deployLoaded"
          @click="saveDeploySettings">保存访问设置</el-button>
      </div>
    </el-form>
  </details>

  <details class="settings-card settings-details settings-diagnostics" @toggle="diagnosticsOpened = $event.target.open">
    <summary>连接诊断<span>遇到连接问题时展开</span></summary>
    <diagnostics-panel embedded v-if="diagnosticsOpened"></diagnostics-panel>
  </details>
</section>`,
};
