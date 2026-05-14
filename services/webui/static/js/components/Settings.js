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
        run_in_background: '后台运行', auto_start: '自动启动', max_retry: '最大重试',
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

    <!-- 以下区块暂不支持，已整体注释保留；恢复时取消注释并同步取消下方「注释保留的 data / mounted / methods」
    <el-card shadow="hover" class="mb-6">
      <template #header><div class="text-lg font-semibold">通知推送</div></template>
      <el-form-item label="启用通知">
        <el-switch v-model="notifyConfig.enabled" />
      </el-form-item>
      <el-form-item label="推送配置 (YAML)">
        <el-input v-model="notifyConfig.config_yaml" type="textarea" :rows="4"
                  placeholder="provider: pushplus&#10;token: your_token" />
      </el-form-item>
      <el-form-item>
        <el-button @click="testNotify" :loading="notifyTestLoading">发送测试</el-button>
      </el-form-item>
    </el-card>

    <el-card shadow="hover" class="mb-6">
      <template #header><div class="text-lg font-semibold">自动更新</div></template>
      <el-row :gutter="20">
        <el-col :span="12">
          <el-form-item label="自动检查">
            <el-switch v-model="updateConfig.auto_check" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="检查间隔(分钟)">
            <el-input-number v-model="updateConfig.check_interval_minutes" :min="5" :max="1440" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="定时重启更新">
        <el-input v-model="updateConfig.auto_restart_time" placeholder="如 03:50（留空禁用）" style="width:200px" />
      </el-form-item>
      <el-form-item label="当前状态">
        <el-tag :type="updateStatus.state === 'available' ? 'warning' : 'info'" size="small">
          {{ updateStatus.state }} | {{ updateStatus.current_version || '?' }}
        </el-tag>
        <el-button size="small" @click="checkUpdate" style="margin-left:8px">检查更新</el-button>
        <el-button v-if="updateStatus.state === 'available'" size="small" type="warning" @click="runUpdate">立即更新</el-button>
      </el-form-item>
      <el-form-item v-if="updateStatus.changelog" label="更新日志">
        <pre style="font-size:12px;max-height:120px;overflow:auto;background:#f5f5f5;padding:8px;border-radius:4px">{{ updateStatus.changelog }}</pre>
      </el-form-item>
    </el-card>

    <el-card shadow="hover" class="mb-6">
      <template #header><div class="text-lg font-semibold">远程访问 (SSH 隧道)</div></template>
      <el-row :gutter="20">
        <el-col :span="12">
          <el-form-item label="SSH 服务器">
            <el-input v-model="remoteConfig.ssh_server" placeholder="host:port" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="SSH 用户名">
            <el-input v-model="remoteConfig.ssh_user" placeholder="nokey" />
          </el-form-item>
        </el-col>
      </el-row>
      <el-form-item label="状态">
        <el-tag :type="remoteStatus.state === 'connected' ? 'success' : remoteStatus.state === 'connecting' ? 'warning' : 'info'" size="small">
          {{ remoteStatus.state }}
        </el-tag>
        <span v-if="remoteStatus.address" style="margin-left:8px;color:#22c55e">{{ remoteStatus.address }}</span>
      </el-form-item>
      <el-form-item>
        <el-button v-if="remoteStatus.state === 'stopped'" type="primary" size="small" @click="toggleRemote(true)">启动</el-button>
        <el-button v-else type="danger" size="small" @click="toggleRemote(false)">停止</el-button>
      </el-form-item>
    </el-card>

    <el-card shadow="hover" class="mb-6">
      <template #header><div class="text-lg font-semibold">部署设置</div></template>
      <el-row :gutter="20">
        <el-col :span="12">
          <el-form-item label="主题">
            <el-select v-model="deployConfig.theme">
              <el-option label="深色" value="dark" />
              <el-option label="浅色" value="light" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="访问密码">
            <div style="display:flex;align-items:center;gap:8px;width:100%">
              <el-input v-model="deployConfig.password" :placeholder="passwordProtected ? '留空不修改' : '留空不设密码'" show-password style="flex:1" />
              <el-tag v-if="passwordProtected" type="success" size="small">已设置</el-tag>
              <el-button v-if="passwordProtected" size="small" type="danger" plain @click="clearDeployPassword">清除</el-button>
            </div>
          </el-form-item>
        </el-col>
      </el-row>
    </el-card>

    <el-card shadow="hover" class="mb-6">
      <template #header><div class="text-lg font-semibold">配置管理</div></template>
      <el-form-item>
        <el-button @click="exportConfig"><i class="fa fa-download"></i> 导出配置</el-button>
        <el-button @click="importConfig"><i class="fa fa-upload"></i> 导入配置</el-button>
      </el-form-item>
    </el-card>
    -->

  </el-form>

  <div class="flex justify-center sticky bottom-0 bg-white pt-4 pb-2">
    <el-button type="primary" size="large" class="w-2/5 min-w-[200px]" @click="saveAllSettings" :disabled="executionBusy">
      <span style="font-size:18px">保存设置</span>
    </el-button>
  </div>
</div>`,
};

/*
 * ── 以下为先前实现，功能未开放时从模板中 HTML 注释掉；恢复 UI 时请取消模板注释，并把下列字段/钩子/方法合并回组件（勿重复定义）──
 *
 * data() 追加：
 *   passwordProtected: false,
 *   deployConfig: {},
 *   notifyConfig: {},
 *   updateConfig: {},
 *   remoteConfig: {},
 *   remoteStatus: { state: 'stopped', address: null },
 *   updateStatus: { state: 'idle' },
 *   notifyTestLoading: false,
 *
 * async mounted() {
 *   await this.loadDeploy();
 *   this.loadRemoteStatus();
 *   this.loadUpdateStatus();
 * },
 *
 * methods 追加：
 *   async loadDeploy() {
 *     try {
 *       const data = await (await fetch('/api/deploy')).json();
 *       this.deployConfig = data.deploy || {};
 *       this.passwordProtected = data.password_protected || false;
 *       this.notifyConfig = data.notify || {};
 *       this.updateConfig = data.update || {};
 *       this.remoteConfig = data.remote_access || {};
 *     } catch (e) { console.error('loadDeploy', e); }
 *   },
 *   async clearDeployPassword() {
 *     try {
 *       const { value } = await ElementPlus.ElMessageBox.prompt(
 *         '清除访问密码需要验证当前密码', '安全验证',
 *         { inputType: 'password', confirmButtonText: '验证', cancelButtonText: '取消' });
 *       this.deployConfig.password = null;
 *       await this._persistDeploy({ current_password: value });
 *       this.passwordProtected = false;
 *       this.deployConfig.password = '';
 *       ElementPlus.ElMessage.success('访问密码已清除');
 *     } catch (e) {
 *       if (e !== 'cancel' && e !== 'close') {
 *         ElementPlus.ElMessage.error(e.message || '清除失败');
 *       }
 *     }
 *   },
 *   async _persistDeploy(extraDeployFields) {
 *     const deployPayload = { ...this.deployConfig, ...(extraDeployFields || {}) };
 *     const res = await fetch('/api/deploy', { method: 'POST', headers: {'Content-Type':'application/json'},
 *       body: JSON.stringify({ deploy: deployPayload, notify: this.notifyConfig, update: this.updateConfig, remote_access: this.remoteConfig })
 *     });
 *     if (!res.ok) {
 *       const data = await res.json().catch(() => ({}));
 *       throw new Error(data.error || '保存失败');
 *     }
 *     if (this.deployConfig.theme === 'light') {
 *       document.documentElement.classList.add('light');
 *     } else {
 *       document.documentElement.classList.remove('light');
 *     }
 *   },
 *   async saveAllSettings() {
 *     try {
 *       let extra = {};
 *       const hasNewPwd = this.deployConfig.password && this.deployConfig.password.length > 0;
 *       if (hasNewPwd && this.passwordProtected) {
 *         try {
 *           const { value } = await ElementPlus.ElMessageBox.prompt(
 *             '修改访问密码需要验证当前密码', '安全验证',
 *             { inputType: 'password', confirmButtonText: '验证', cancelButtonText: '取消' });
 *           extra.current_password = value;
 *         } catch { return; }
 *       }
 *       await this._persistDeploy(extra);
 *       if (hasNewPwd) this.passwordProtected = true;
 *       this.$emit('save-settings');
 *     } catch (e) {
 *       ElementPlus.ElMessage.error(e.message || '保存失败（部署类配置）');
 *     }
 *   },
 *   async testNotify() {
 *     this.notifyTestLoading = true;
 *     try {
 *       const res = await fetch('/api/notify/test', { method: 'POST', headers: {'Content-Type':'application/json'},
 *         body: JSON.stringify({ config_yaml: this.notifyConfig.config_yaml || '' })
 *       });
 *       const data = await res.json();
 *       if (data.success) ElementPlus.ElMessage.success('通知发送成功');
 *       else ElementPlus.ElMessage.warning('通知发送失败，请检查配置');
 *     } catch (e) { ElementPlus.ElMessage.error('测试失败: ' + e); }
 *     this.notifyTestLoading = false;
 *   },
 *   async loadRemoteStatus() {
 *     try { this.remoteStatus = await (await fetch('/api/remote-access')).json(); } catch(e) {}
 *   },
 *   async toggleRemote(enabled) {
 *     try {
 *       const res = await fetch('/api/remote-access', { method: 'POST', headers: {'Content-Type':'application/json'},
 *         body: JSON.stringify({ enabled })
 *       });
 *       this.remoteStatus = await res.json();
 *     } catch(e) { ElementPlus.ElMessage.error('操作失败'); }
 *   },
 *   async loadUpdateStatus() {
 *     try { this.updateStatus = await (await fetch('/api/update/status')).json(); } catch(e) {}
 *   },
 *   async checkUpdate() {
 *     try {
 *       const res = await fetch('/api/update/check', { method: 'POST' });
 *       this.updateStatus = await res.json();
 *       if (this.updateStatus.has_update) ElementPlus.ElMessage.info('发现新版本');
 *       else ElementPlus.ElMessage.success('已是最新版本');
 *     } catch(e) { ElementPlus.ElMessage.error('检查失败'); }
 *   },
 *   async runUpdate() {
 *     try {
 *       const res = await fetch('/api/update/run', { method: 'POST' });
 *       this.updateStatus = await res.json();
 *       if (this.updateStatus.success) ElementPlus.ElMessage.success('更新完成，请重启应用');
 *       else ElementPlus.ElMessage.error('更新失败');
 *     } catch(e) { ElementPlus.ElMessage.error('更新失败'); }
 *   },
 *   async exportConfig() {
 *     try {
 *       const res = await fetch('/api/config/export');
 *       const blob = await res.blob();
 *       const url = URL.createObjectURL(blob);
 *       const a = document.createElement('a');
 *       a.href = url; a.download = 'autoscriptor-config.json'; a.click();
 *       URL.revokeObjectURL(url);
 *     } catch(e) { ElementPlus.ElMessage.error('导出失败'); }
 *   },
 *   async importConfig() {
 *     const input = document.createElement('input');
 *     input.type = 'file'; input.accept = '.json';
 *     input.onchange = async (e) => {
 *       const file = e.target.files[0]; if (!file) return;
 *       const text = await file.text();
 *       try {
 *         const data = JSON.parse(text);
 *         await fetch('/api/config/import', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
 *         ElementPlus.ElMessage.success('导入成功，请刷新页面');
 *         setTimeout(() => location.reload(), 1000);
 *       } catch(e) { ElementPlus.ElMessage.error('导入失败: ' + e); }
 *     };
 *     input.click();
 *   },
 */
