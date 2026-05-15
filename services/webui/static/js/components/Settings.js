const SettingsPanel = {
  name: 'SettingsPanel',
  props: {
    filteredConfig: { type: Object, required: true },
    executionBusy: { type: Boolean, default: false },
  },
  emits: ['save-settings'],
  data() {
    return {
      hiddenSections: ['game', 'status', 'encryption', 'profiles', 'current_account', 'active_character', 'characters_summary', 'deploy', 'notify', 'update', 'remote_access', 'llm', 'accounts'],
      /** 仍保存在 config 中，但不在表单里展示（避免误改） */
      hiddenKeysBySection: { app: ['name'] },
      sectionLabels: { app: '应用设置', ocr: 'OCR 设置', emulator: '模拟器设置', llm: '智能体' },
      keyLabels: {
        name: '应用名称', app_to_start: '服务器选择', restart_on_error: '出错重启',
        run_in_background: '后台运行', auto_start: '兼容自动启动', max_retry: '最大重试',
        debug_mode: '调试模式', cpu_cores: 'CPU 核心数',
        use_gpu: '使用 GPU', index: '模拟器索引',
        adb_addr: 'ADB 地址', mumu_folder: 'MuMu 安装目录', post_execution: '执行后动作',
        emu_path: '模拟器路径', adb_path: 'ADB 路径',
        use_agent: '启用智能体', url: '智能体路径', model: '模型名称',
      },
      urlPlaceholder: '使用本机路径',
      /** MuMu 12：实例 0 → 16384，每多开一个实例端口 +32（与安装向导说明一致） */
      MUMU_ADB_BASE_PORT: 16384,
      MUMU_ADB_PORT_STEP: 32,
      /** 与 AutoScriptor.utils.app_package_resolve.ZMXY_PACKAGE_FALLBACK_ORDER 一致 */
      serverPackages: [
        { label: '4399官服', value: 'org.yjmobile.zmxy' },
        { label: '9游服务器', value: 'com.zmxyol.union.uc' },
        { label: '当乐服务器', value: 'com.zmxyol.union.dn' },
        { label: 'Vivo服务器', value: 'com.sy4399.zmxyol.vivo' },
      ],
    };
  },
  computed: {
    visibleSections() {
      const result = {};
      for (const [k, v] of Object.entries(this.filteredConfig)) {
        if (!this.hiddenSections.includes(k) && v && typeof v === 'object') result[k] = v;
      }
      return result;
    },
  },
  methods: {
    /** 调整模拟器索引时同步 ADB 地址中的端口号，保留主机部分（如 127.0.0.1 或局域网 IP） */
    onNumberFieldChange(secKey, key, val) {
      if (secKey !== 'emulator' || key !== 'index') return;
      this.syncAdbPortFromIndex(val);
    },
    syncAdbPortFromIndex(index) {
      const emu = this.filteredConfig.emulator;
      if (!emu) return;
      const n = Number(index);
      if (!Number.isFinite(n) || n < 0) return;
      const port = this.MUMU_ADB_BASE_PORT + n * this.MUMU_ADB_PORT_STEP;
      let addr = String(emu.adb_addr || '').trim();
      if (!addr || addr.startsWith('YOUR_')) {
        emu.adb_addr = `127.0.0.1:${port}`;
        return;
      }
      const colon = addr.lastIndexOf(':');
      if (colon >= 0) {
        emu.adb_addr = `${addr.slice(0, colon + 1)}${port}`;
      } else {
        emu.adb_addr = `127.0.0.1:${port}`;
      }
    },
    serverOptionsFor(currentValue) {
      const base = this.serverPackages;
      if (currentValue && !base.some((o) => o.value === currentValue)) {
        return [...base, { label: `其他 (${currentValue})`, value: currentValue }];
      }
      return base;
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
<div class="bg-white rounded-xl shadow-md p-6 h-full overflow-y-auto">
  <el-form :model="filteredConfig" label-width="130px" :disabled="executionBusy">
    <!-- 基础设置 -->
    <div v-for="(section, secKey) in visibleSections" :key="secKey" class="mb-6">
      <el-card shadow="hover">
        <template #header><div class="text-lg font-semibold">{{ sectionLabels[secKey] || secKey }}</div></template>
        <el-row :gutter="20">
          <template v-for="(value, key) in section" :key="key">
          <el-col :span="12" v-if="!(hiddenKeysBySection[secKey] && hiddenKeysBySection[secKey].includes(key))">
            <el-form-item :label="keyLabels[key] || key">
              <el-switch v-if="typeof value === 'boolean'" v-model="filteredConfig[secKey][key]" />
              <el-input-number v-else-if="typeof value === 'number'" v-model="filteredConfig[secKey][key]" :min="0"
                @change="(v) => onNumberFieldChange(secKey, key, v)" />
              <el-select v-else-if="key === 'post_execution'" v-model="filteredConfig[secKey][key]">
                <el-option label="什么都不做" value="none" />
                <el-option label="关闭模拟器" value="close_mumu" />
                <el-option label="仅关闭游戏" value="close_game_only" />
                <el-option label="回到主界面" value="goto_main" />
              </el-select>
              <el-select v-else-if="key === 'app_to_start'" v-model="filteredConfig[secKey][key]" placeholder="请选择服务器" style="width:100%">
                <el-option v-for="opt in serverOptionsFor(value)" :key="opt.value" :label="opt.label" :value="opt.value" />
              </el-select>
              <el-input v-else v-model="filteredConfig[secKey][key]"
                        :placeholder="key === 'url' ? urlPlaceholder : ''" />
            </el-form-item>
          </el-col>
          </template>
        </el-row>
      </el-card>
    </div>
  </el-form>

  <div class="flex justify-center sticky bottom-0 bg-white pt-4 pb-2">
    <el-button type="primary" size="large" class="w-2/5 min-w-[200px]" @click="saveAllSettings" :disabled="executionBusy">
      <span style="font-size:18px">保存设置</span>
    </el-button>
  </div>
</div>`,
};
