const SettingsPanel = {
  name: 'SettingsPanel',
  props: {
    filteredConfig: { type: Object, required: true },
  },
  emits: ['save-settings'],
  data() {
    return {
      hiddenSections: ['game', 'status', 'encryption', 'profiles', 'deploy', 'notify', 'update', 'remote_access'],
      sectionLabels: { app: '应用设置', ocr: 'OCR 设置', emulator: '模拟器设置', llm: '智能体' },
      keyLabels: {
        name: '应用名称', app_to_start: '启动包名', restart_on_error: '出错重启',
        run_in_background: '后台运行', auto_start: '自动启动', max_retry: '最大重试',
        debug_mode: '调试模式', cpu_cores: 'CPU 核心数',
        use_gpu: '使用 GPU', index: '模拟器索引',
        adb_addr: 'ADB 地址', mumu_folder: 'MuMu 安装目录', post_execution: '执行后动作',
        emu_path: '模拟器路径', adb_path: 'ADB 路径',
        use_agent: '启用智能体', url: '智能体路径', model: '模型名称',
      },
      urlPlaceholder: '使用本机路径',
      // deploy
      deployConfig: {},
      notifyConfig: {},
      updateConfig: {},
      remoteConfig: {},
      remoteStatus: { state: 'stopped', address: null },
      updateStatus: { state: 'idle' },
      notifyTestLoading: false,
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
  async mounted() {
    await this.loadDeploy();
    this.loadRemoteStatus();
    this.loadUpdateStatus();
  },
  methods: {
    async loadDeploy() {
      try {
        const data = await (await fetch('/api/deploy')).json();
        this.deployConfig = data.deploy || {};
        this.notifyConfig = data.notify || {};
        this.updateConfig = data.update || {};
        this.remoteConfig = data.remote_access || {};
      } catch (e) { console.error('loadDeploy', e); }
    },
    async _persistDeploy() {
      await fetch('/api/deploy', { method: 'POST', headers: {'Content-Type':'application/json'},
        body: JSON.stringify({ deploy: this.deployConfig, notify: this.notifyConfig, update: this.updateConfig, remote_access: this.remoteConfig })
      });
      if (this.deployConfig.theme === 'light') {
        document.documentElement.classList.add('light');
      } else {
        document.documentElement.classList.remove('light');
      }
    },
    /** 先保存部署/通知/更新/远程，再交给父组件保存 app/emulator/ocr/llm */
    async saveAllSettings() {
      try {
        await this._persistDeploy();
        this.$emit('save-settings');
      } catch (e) {
        ElementPlus.ElMessage.error('保存失败（部署类配置）');
      }
    },
    async testNotify() {
      this.notifyTestLoading = true;
      try {
        const res = await fetch('/api/notify/test', { method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ config_yaml: this.notifyConfig.config_yaml || '' })
        });
        const data = await res.json();
        if (data.success) ElementPlus.ElMessage.success('通知发送成功');
        else ElementPlus.ElMessage.warning('通知发送失败，请检查配置');
      } catch (e) { ElementPlus.ElMessage.error('测试失败: ' + e); }
      this.notifyTestLoading = false;
    },
    async loadRemoteStatus() {
      try { this.remoteStatus = await (await fetch('/api/remote-access')).json(); } catch(e) {}
    },
    async toggleRemote(enabled) {
      try {
        const res = await fetch('/api/remote-access', { method: 'POST', headers: {'Content-Type':'application/json'},
          body: JSON.stringify({ enabled })
        });
        this.remoteStatus = await res.json();
      } catch(e) { ElementPlus.ElMessage.error('操作失败'); }
    },
    async loadUpdateStatus() {
      try { this.updateStatus = await (await fetch('/api/update/status')).json(); } catch(e) {}
    },
    async checkUpdate() {
      try {
        const res = await fetch('/api/update/check', { method: 'POST' });
        this.updateStatus = await res.json();
        if (this.updateStatus.has_update) ElementPlus.ElMessage.info('发现新版本');
        else ElementPlus.ElMessage.success('已是最新版本');
      } catch(e) { ElementPlus.ElMessage.error('检查失败'); }
    },
    async runUpdate() {
      try {
        const res = await fetch('/api/update/run', { method: 'POST' });
        this.updateStatus = await res.json();
        if (this.updateStatus.success) ElementPlus.ElMessage.success('更新完成，请重启应用');
        else ElementPlus.ElMessage.error('更新失败');
      } catch(e) { ElementPlus.ElMessage.error('更新失败'); }
    },
    async exportConfig() {
      try {
        const res = await fetch('/api/config/export');
        const blob = await res.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = 'autoscriptor-config.json'; a.click();
        URL.revokeObjectURL(url);
      } catch(e) { ElementPlus.ElMessage.error('导出失败'); }
    },
    async importConfig() {
      const input = document.createElement('input');
      input.type = 'file'; input.accept = '.json';
      input.onchange = async (e) => {
        const file = e.target.files[0]; if (!file) return;
        const text = await file.text();
        try {
          const data = JSON.parse(text);
          await fetch('/api/config/import', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(data) });
          ElementPlus.ElMessage.success('导入成功，请刷新页面');
          setTimeout(() => location.reload(), 1000);
        } catch(e) { ElementPlus.ElMessage.error('导入失败: ' + e); }
      };
      input.click();
    },
  },
  template: `
<div class="bg-white rounded-xl shadow-md p-6 h-full overflow-y-auto">
  <el-form :model="filteredConfig" label-width="130px">
    <!-- 基础设置 -->
    <div v-for="(section, secKey) in visibleSections" :key="secKey" class="mb-6">
      <el-card shadow="hover">
        <template #header><div class="text-lg font-semibold">{{ sectionLabels[secKey] || secKey }}</div></template>
        <el-row :gutter="20">
          <el-col :span="12" v-for="(value, key) in section" :key="key">
            <el-form-item :label="keyLabels[key] || key">
              <el-switch v-if="typeof value === 'boolean'" v-model="filteredConfig[secKey][key]" />
              <el-input-number v-else-if="typeof value === 'number'" v-model="filteredConfig[secKey][key]" :min="0" />
              <el-select v-else-if="key === 'post_execution'" v-model="filteredConfig[secKey][key]">
                <el-option label="什么都不做" value="none" />
                <el-option label="关闭模拟器" value="close_mumu" />
                <el-option label="仅关闭游戏" value="close_game_only" />
                <el-option label="回到主界面" value="goto_main" />
              </el-select>
              <el-input v-else v-model="filteredConfig[secKey][key]"
                        :placeholder="key === 'url' ? urlPlaceholder : ''" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-card>
    </div>

    <!-- 通知推送 -->
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

    <!-- 自动更新 -->
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

    <!-- 远程访问 -->
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

    <!-- 部署设置 -->
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
            <el-input v-model="deployConfig.password" placeholder="留空不设密码" show-password />
          </el-form-item>
        </el-col>
      </el-row>
    </el-card>

    <!-- 配置导入导出 -->
    <el-card shadow="hover" class="mb-6">
      <template #header><div class="text-lg font-semibold">配置管理</div></template>
      <el-form-item>
        <el-button @click="exportConfig"><i class="fa fa-download"></i> 导出配置</el-button>
        <el-button @click="importConfig"><i class="fa fa-upload"></i> 导入配置</el-button>
      </el-form-item>
    </el-card>

  </el-form>

  <div class="flex justify-center sticky bottom-0 bg-white pt-4 pb-2">
    <el-button type="primary" size="large" class="w-2/5 min-w-[200px]" @click="saveAllSettings">
      <span style="font-size:18px">保存设置</span>
    </el-button>
  </div>
</div>`,
};
