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
      <div class="settings-kicker">运行配置</div>
      <h2 class="settings-title">把常用开关放在能看懂的地方</h2>
      <p class="settings-subtitle">
        这里主要调整运行、模拟器连接和识别能力。账号、角色、任务队列仍在总览页管理，避免把不同生命周期的东西混在一起。
      </p>
    </div>
    <el-button type="primary" size="large" @click="saveAllSettings" :disabled="executionBusy">
      <i class="fa fa-save mr-1"></i>保存设置
    </el-button>
  </div>

  <el-alert v-if="executionBusy" type="warning" :closable="false" show-icon class="settings-busy-alert"
    title="任务执行中暂时锁定设置"
    description="为了避免执行链读到一半配置又被改写，请先停止当前任务，再保存运行配置。"></el-alert>

  <el-form :model="filteredConfig" :disabled="executionBusy" label-position="top" class="settings-form">
    <div class="settings-grid settings-grid--two">
      <article class="settings-card">
        <div class="settings-card-head">
          <div>
            <h3><i class="fa fa-play-circle"></i>运行方式</h3>
            <p>决定点击运行后，脚本如何启动、重试和收尾。</p>
          </div>
        </div>

        <div class="settings-field-row">
          <div class="settings-field-text">
            <div class="settings-field-title">任务开始时自动启动模拟器和游戏</div>
            <p>开启后会自动确认 MuMu 实例、拉起游戏；关闭后需要你先手动打开。它不是“兼容性越高越慢”的开关。</p>
          </div>
          <el-switch v-model="appConfig.auto_start" />
        </div>

        <div class="settings-field-row">
          <div class="settings-field-text">
            <div class="settings-field-title">模拟器后台运行</div>
            <p>启动后隐藏模拟器窗口，适合挂机；排查点击或截图问题时建议关闭。</p>
          </div>
          <el-switch v-model="appConfig.run_in_background" />
        </div>

        <div class="settings-field-row">
          <div class="settings-field-text">
            <div class="settings-field-title">失败后自动重试</div>
            <p>任务执行失败时按最大重试次数恢复执行。脚本逻辑明显写错时，应该直接停止而不是靠重试硬扛。</p>
          </div>
          <el-switch v-model="appConfig.restart_on_error" />
        </div>

        <div class="settings-field-grid">
          <el-form-item label="最大重试次数">
            <el-input-number v-model="appConfig.max_retry" :min="0" :max="10" controls-position="right" />
            <div class="settings-help">0 表示不自动重试。</div>
          </el-form-item>
          <el-form-item label="执行结束后">
            <el-select v-model="emulatorConfig.post_execution" style="width:100%">
              <el-option v-for="opt in postExecutionOptions" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
            <div class="settings-help">只在本轮任务全部结束后执行，不会影响中途停止。</div>
          </el-form-item>
        </div>
      </article>

      <article class="settings-card">
        <div class="settings-card-head">
          <div>
            <h3><i class="fa fa-desktop"></i>模拟器连接</h3>
            <p>决定脚本连接哪一个 MuMu，以及使用哪个游戏包。</p>
          </div>
        </div>

        <div class="settings-field-grid">
          <el-form-item label="游戏服务器">
            <el-select v-model="appConfig.app_to_start" placeholder="请选择服务器" style="width:100%">
              <el-option v-for="opt in serverOptionsFor(appConfig.app_to_start)" :key="opt.value" :label="opt.label" :value="opt.value" />
            </el-select>
            <div class="settings-help">保存的是 Android 包名，不是账号所在区服。</div>
          </el-form-item>
          <el-form-item label="MuMu 多开编号">
            <el-input-number v-model="emulatorConfig.index" :min="0" :max="99" controls-position="right" @change="syncAdbPortFromIndex" />
            <div class="settings-help">编号变更后会自动推算 ADB 端口。</div>
          </el-form-item>
        </div>

        <el-form-item label="ADB 连接地址">
          <el-input v-model="emulatorConfig.adb_addr" placeholder="例如 127.0.0.1:16416" />
          <div class="settings-help">点击、滑动、输入、App 状态检测优先走 ADB。多开编号 1 通常是 127.0.0.1:16416。</div>
        </el-form-item>

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

    <div class="settings-grid settings-grid--three">
      <article class="settings-card settings-card--compact">
        <h3><i class="fa fa-eye"></i>识别能力</h3>
        <div class="settings-field-row">
          <div class="settings-field-text">
            <div class="settings-field-title">OCR 使用 GPU</div>
            <p>有兼容显卡时可加速文字识别；如果启动慢、报错或识别异常，关闭会更稳。</p>
          </div>
          <el-switch v-model="ocrConfig.use_gpu" />
        </div>
        <el-form-item v-if="hasOcrScale" label="OCR 缩放比例">
          <el-input-number v-model="ocrConfig.scale" :min="0.5" :max="1" :step="0.05" controls-position="right" />
          <div class="settings-help">低比例更快，高比例更清楚。当前脚本失败时会自动回退到 1.0 再试。</div>
        </el-form-item>
      </article>

      <article class="settings-card settings-card--compact">
        <h3><i class="fa fa-bug"></i>排查与性能</h3>
        <div class="settings-field-row">
          <div class="settings-field-text">
            <div class="settings-field-title">调试模式</div>
            <p>保存失败截图和标注素材，适合修脚本；平时可关闭，减少磁盘文件。</p>
          </div>
          <el-switch v-model="appConfig.debug_mode" />
        </div>
        <el-form-item label="CPU 核心限制">
          <el-input-number v-model="appConfig.cpu_cores" :min="0" :max="64" controls-position="right" />
          <div class="settings-help">0 表示不限制。电脑卡顿时可限制脚本使用的核心数。</div>
        </el-form-item>
      </article>

      <article class="settings-card settings-card--compact">
        <h3><i class="fa fa-clock-o"></i>自动调度</h3>
        <div class="settings-field-row">
          <div class="settings-field-text">
            <div class="settings-field-title">前后端启动后自动调度</div>
            <p>开启后程序启动时会自动监听队列中的角色，到时间再执行；手动点击运行仍然随时可用。</p>
          </div>
          <el-switch v-model="schedulerConfig.auto_start" />
        </div>
        <div class="settings-note">
          只有调度队列里的角色会参与自动调度，顺序以总览页队列为准。
        </div>
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
