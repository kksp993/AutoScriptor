const UpdatePanel = {
  name: 'UpdatePanel',
  data() {
    return {
      status: {
        state: 'idle',
        current_version: '',
        branch: '',
        remote_version: '',
        changelog: '',
        last_error: '',
      },
      checking: false,
      updating: false,
    };
  },
  computed: {
    stateTag() {
      const map = {
        idle:       { label: '已是最新',     type: 'success' },
        checking:   { label: '检查中…',      type: 'warning' },
        available:  { label: '有新版本',     type: 'danger'  },
        updating:   { label: '更新中…',      type: 'warning' },
        done:       { label: '更新完成',     type: 'success' },
        restarting: { label: '正在重启…',    type: 'warning' },
        failed:     { label: '操作失败',     type: 'danger'  },
      };
      return map[this.status.state] || { label: this.status.state, type: 'info' };
    },
    changelogLines() {
      if (!this.status.changelog) return [];
      return this.status.changelog.split('\n').filter(l => l.trim());
    },
  },
  async mounted() {
    await this.loadStatus();
  },
  methods: {
    async loadStatus() {
      try {
        const res = await fetch('/api/update/status');
        this.status = await res.json();
      } catch (e) {
        console.error('loadUpdateStatus', e);
      }
    },
    async checkUpdate() {
      this.checking = true;
      try {
        const res = await fetch('/api/update/check', { method: 'POST' });
        this.status = await res.json();
        if (this.status.has_update) {
          ElementPlus.ElMessage.info('发现新版本');
        } else {
          ElementPlus.ElMessage.success('已是最新版本');
        }
      } catch (e) {
        ElementPlus.ElMessage.error('检查失败');
      }
      this.checking = false;
    },
    async runUpdate() {
      try {
        await ElementPlus.ElMessageBox.confirm(
          '更新将拉取远程代码并安装依赖，完成后自动重启后端。',
          '确认更新',
          { confirmButtonText: '立即更新', cancelButtonText: '取消', type: 'warning' }
        );
      } catch {
        return;
      }
      this.updating = true;
      try {
        const res = await fetch('/api/update/run', { method: 'POST' });
        this.status = await res.json();
        if (this.status.state === 'restarting') {
          ElementPlus.ElMessage.success('更新完成，后端正在重启…');
          this._waitForRestart();
        } else if (this.status.success) {
          ElementPlus.ElMessage.success('更新完成，建议重启应用以加载新版本');
        } else {
          ElementPlus.ElMessage.error('更新失败: ' + (this.status.last_error || '未知错误'));
        }
      } catch (e) {
        ElementPlus.ElMessage.error('更新请求失败');
      }
      this.updating = false;
    },
    _waitForRestart() {
      let attempts = 0;
      const maxAttempts = 30;
      const poll = setInterval(async () => {
        attempts++;
        try {
          const res = await fetch('/api/update/status', { signal: AbortSignal.timeout(3000) });
          if (res.ok) {
            clearInterval(poll);
            ElementPlus.ElMessage.success('后端已重启完成');
            setTimeout(() => location.reload(), 500);
          }
        } catch {
          // 服务尚未恢复，继续等待
        }
        if (attempts >= maxAttempts) {
          clearInterval(poll);
          ElementPlus.ElMessage.warning('重启超时，请手动刷新页面');
        }
      }, 3000);
    },
  },
  template: `
<div class="bg-white rounded-xl shadow-md p-6 h-full overflow-y-auto">

  <el-card shadow="hover" class="mb-6">
    <template #header>
      <div class="flex items-center justify-between">
        <span class="text-lg font-semibold">版本信息</span>
        <el-tag :type="stateTag.type" effect="dark" size="small">{{ stateTag.label }}</el-tag>
      </div>
    </template>

    <el-descriptions :column="2" border size="default">
      <el-descriptions-item label="当前版本">
        <code class="text-sm">{{ status.current_version || '-' }}</code>
      </el-descriptions-item>
      <el-descriptions-item label="当前分支">
        <el-tag size="small" type="info">{{ status.branch || '-' }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="远程版本" v-if="status.remote_version">
        <code class="text-sm text-orange-600">{{ status.remote_version }}</code>
      </el-descriptions-item>
    </el-descriptions>

    <div class="mt-4 flex gap-3">
      <el-button type="primary" :loading="checking" @click="checkUpdate">
        <i v-if="!checking" class="fa fa-refresh" style="margin-right:6px"></i>检查更新
      </el-button>
      <el-button v-if="status.state === 'available'" type="warning" :loading="updating" @click="runUpdate">
        <i v-if="!updating" class="fa fa-download" style="margin-right:6px"></i>立即更新
      </el-button>
    </div>
  </el-card>

  <el-card v-if="changelogLines.length" shadow="hover" class="mb-6">
    <template #header><span class="text-lg font-semibold">更新日志</span></template>
    <div class="changelog-list">
      <div v-for="(line, i) in changelogLines" :key="i" class="changelog-item">
        <code class="changelog-hash">{{ line.substring(0, 8) }}</code>
        <span class="changelog-msg">{{ line.substring(9) }}</span>
      </div>
    </div>
  </el-card>

  <el-card v-if="status.last_error" shadow="hover">
    <template #header><span class="text-lg font-semibold" style="color:#ef4444">错误信息</span></template>
    <el-alert type="error" :closable="false" show-icon>{{ status.last_error }}</el-alert>
  </el-card>

  <el-card shadow="hover" class="mb-6" style="margin-top:24px">
    <template #header><span class="text-lg font-semibold">说明</span></template>
    <ul style="color:#64748b;font-size:14px;line-height:2;padding-left:16px">
      <li>点击「检查更新」将从远程仓库 fetch 最新代码并比较版本差异</li>
      <li>「立即更新」会通过 git pull 拉取代码，并自动安装新增的 Python 依赖</li>
      <li>更新过程中会自动 stash 保护本地修改，更新完成后恢复</li>
      <li>更新完成后将自动重启后端以加载新版本</li>
    </ul>
  </el-card>

</div>`,
};
