const UpdatePanel = {
  name: 'UpdatePanel',
  data() {
    return {
      sourceStatus: {
        kind: 'source-git',
        available: false,
        state: 'disabled',
        current_version: '',
        branch: '',
        remote_branch: 'main',
        remote_version: '',
        ahead_count: 0,
        behind_count: 0,
        changelog: '',
        last_error: '',
        unavailable_reason: '',
        has_update: false,
      },
      checkingSource: false,
      updatingSource: false,
    };
  },
  computed: {
    sourceVisualState() {
      if (this.sourceStatus.available === false) return 'disabled';
      if (this.checkingSource) return 'checking';
      if (this.updatingSource) return 'updating';
      if (this.sourceStatus.has_update) return 'available';
      return this.sourceStatus.state || 'idle';
    },
    sourceTag() {
      const map = {
        disabled: { label: '不可用', type: 'info' },
        idle: { label: '待检查', type: 'info' },
        checking: { label: '检查中', type: 'warning' },
        available: { label: '有更新', type: 'danger' },
        updating: { label: '更新中', type: 'warning' },
        done: { label: '已完成', type: 'success' },
        restarting: { label: '重启中', type: 'warning' },
        failed: { label: '失败', type: 'danger' },
      };
      return map[this.sourceVisualState] || { label: this.sourceVisualState, type: 'info' };
    },
    changelogLines() {
      if (!this.sourceStatus.changelog) return [];
      return this.sourceStatus.changelog.split('\n').filter(line => line.trim());
    },
    remoteBranch() {
      return this.sourceStatus.remote_branch || 'main';
    },
    aheadCount() {
      const count = Number(this.sourceStatus.ahead_count || 0);
      return Number.isFinite(count) ? count : 0;
    },
    behindCount() {
      const count = Number(this.sourceStatus.behind_count || 0);
      return Number.isFinite(count) ? count : 0;
    },
    statusMessage() {
      if (this.sourceStatus.available === false) {
        return this.sourceStatus.unavailable_reason || this.sourceStatus.last_error || '当前目录不是可更新的 Git 源码仓库。';
      }
      if (this.sourceStatus.last_error) return this.sourceStatus.last_error;
      if (this.sourceStatus.has_update) return `远端 ${this.remoteBranch} 有 ${this.behindCount} 个新提交，可拉取后重启后端。`;
      if (this.aheadCount > 0 && this.behindCount === 0) return `源码仓库已是最新，本地比远端 ${this.remoteBranch} 新 ${this.aheadCount} 个提交。`;
      if (this.sourceStatus.state === 'done') return '源码仓库已是最新状态。';
      return '源码模式通过 Git 拉取更新；请在源码仓库内执行检查和拉取。';
    },
  },
  async mounted() {
    await this.loadSourceStatus();
  },
  methods: {
    async readJson(res) {
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || data.last_error || `HTTP ${res.status}`);
      }
      return data;
    },
    async loadSourceStatus() {
      try {
        const res = await fetch('/api/update/status');
        this.sourceStatus = await this.readJson(res);
      } catch (e) {
        this.sourceStatus = {
          ...this.sourceStatus,
          available: false,
          state: 'disabled',
          last_error: '读取源码更新状态失败：' + e.message,
        };
      }
    },
    async checkSourceUpdate() {
      this.checkingSource = true;
      try {
        const res = await fetch('/api/update/check', { method: 'POST' });
        const data = await this.readJson(res);
        this.sourceStatus = data;
        const remoteBranch = data.remote_branch || 'main';
        const aheadCount = Number(data.ahead_count || 0);
        const behindCount = Number(data.behind_count || 0);
        if (data.available === false) {
          ElementPlus.ElMessage.warning(data.unavailable_reason || data.last_error || '源码更新不可用');
        } else if (data.has_update) {
          ElementPlus.ElMessage.info(`远端 ${remoteBranch} 有 ${behindCount} 个新提交`);
        } else if (aheadCount > 0 && behindCount === 0) {
          ElementPlus.ElMessage.success(`源码仓库已是最新，本地比远端 ${remoteBranch} 新 ${aheadCount} 个提交`);
        } else {
          ElementPlus.ElMessage.success('源码仓库已是最新');
        }
      } catch (e) {
        this.sourceStatus = { ...this.sourceStatus, state: 'failed', last_error: e.message };
        ElementPlus.ElMessage.error('源码更新检查失败：' + e.message);
      } finally {
        this.checkingSource = false;
      }
    },
    async runSourceUpdate() {
      try {
        await ElementPlus.ElMessageBox.confirm(
          '将执行 Git fetch/pull --ff-only。完成后后端会尝试重启；如果依赖文件变更，请再运行 scripts\\install.bat。',
          '执行源码更新',
          { confirmButtonText: '立即更新', cancelButtonText: '取消', type: 'warning' },
        );
      } catch {
        return;
      }
      this.updatingSource = true;
      try {
        const res = await fetch('/api/update/run', { method: 'POST' });
        const data = await this.readJson(res);
        const wasUpdatingFromRemote = this.sourceStatus.has_update === true;
        this.sourceStatus = data;
        const remoteBranch = data.remote_branch || 'main';
        const aheadCount = Number(data.ahead_count || 0);
        const behindCount = Number(data.behind_count || 0);
        if (data.state === 'restarting') {
          ElementPlus.ElMessage.success('源码更新完成，后端正在重启');
          this.waitForSourceRestart();
        } else if (data.success && aheadCount > 0 && behindCount === 0) {
          ElementPlus.ElMessage.success(`源码仓库已是最新，本地比远端 ${remoteBranch} 新 ${aheadCount} 个提交`);
        } else if (data.success && !wasUpdatingFromRemote && behindCount === 0) {
          ElementPlus.ElMessage.success('源码仓库已是最新');
        } else if (data.success) {
          ElementPlus.ElMessage.success('源码更新完成，建议重启应用');
        } else {
          ElementPlus.ElMessage.error('源码更新失败：' + (data.last_error || '未知错误'));
        }
      } catch (e) {
        this.sourceStatus = { ...this.sourceStatus, state: 'failed', last_error: e.message };
        ElementPlus.ElMessage.error('源码更新请求失败：' + e.message);
      } finally {
        this.updatingSource = false;
      }
    },
    waitForSourceRestart() {
      let attempts = 0;
      const maxAttempts = 30;
      const poll = setInterval(async () => {
        attempts += 1;
        try {
          const res = await fetch('/api/update/status', { signal: AbortSignal.timeout(3000) });
          if (res.ok) {
            clearInterval(poll);
            ElementPlus.ElMessage.success('后端已恢复');
            setTimeout(() => location.reload(), 500);
          }
        } catch {
          // Backend is restarting.
        }
        if (attempts >= maxAttempts) {
          clearInterval(poll);
          ElementPlus.ElMessage.warning('后端重启等待超时，请手动刷新页面');
        }
      }, 3000);
    },
    shortCommit(value) {
      if (!value) return '-';
      const s = String(value);
      return s.length > 12 ? s.slice(0, 12) : s;
    },
  },
  template: `
<div class="bg-white rounded-xl shadow-md p-6 h-full overflow-y-auto">
  <el-card shadow="hover" class="mb-6">
    <template #header>
      <div class="flex items-center justify-between gap-3">
        <span class="text-lg font-semibold">源码仓库更新</span>
        <el-tag :type="sourceTag.type" effect="dark" size="small">{{ sourceTag.label }}</el-tag>
      </div>
    </template>

    <el-alert
      class="mb-4"
      :type="sourceStatus.available === false ? 'info' : (sourceStatus.last_error ? 'error' : 'success')"
      :closable="false"
      show-icon
      :title="statusMessage"
    ></el-alert>

    <el-descriptions :column="2" border size="default">
      <el-descriptions-item label="当前 Commit">
        <code class="text-sm">{{ shortCommit(sourceStatus.current_version) }}</code>
      </el-descriptions-item>
      <el-descriptions-item label="当前分支">
        <el-tag size="small" type="info">{{ sourceStatus.branch || '-' }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="远端目标">
        <el-tag size="small" type="info">origin/{{ remoteBranch }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="远端 Commit" v-if="sourceStatus.remote_version">
        <code class="text-sm text-orange-600">{{ shortCommit(sourceStatus.remote_version) }}</code>
      </el-descriptions-item>
      <el-descriptions-item label="提交差异" v-if="sourceStatus.available !== false">
        <span>领先 {{ aheadCount }} / 落后 {{ behindCount }}</span>
      </el-descriptions-item>
      <el-descriptions-item label="更新类型">
        <span>源码 Git 拉取</span>
      </el-descriptions-item>
    </el-descriptions>

    <div class="mt-4 flex flex-wrap gap-3">
      <el-button type="primary" :loading="checkingSource" :disabled="sourceStatus.available === false" @click="checkSourceUpdate">
        <i v-if="!checkingSource" class="fa fa-code-fork mr-1"></i>检查源码更新
      </el-button>
      <el-button type="warning" :loading="updatingSource" :disabled="sourceStatus.available === false || !sourceStatus.has_update" @click="runSourceUpdate">
        <i v-if="!updatingSource" class="fa fa-download mr-1"></i>拉取源码
      </el-button>
    </div>
  </el-card>

  <el-card v-if="changelogLines.length" shadow="hover">
    <template #header><span class="text-lg font-semibold">源码更新日志</span></template>
    <div class="changelog-list">
      <div v-for="(line, i) in changelogLines" :key="i" class="changelog-item">
        <code class="changelog-hash">{{ line.substring(0, 8) }}</code>
        <span class="changelog-msg">{{ line.substring(9) }}</span>
      </div>
    </div>
  </el-card>
</div>`,
};
