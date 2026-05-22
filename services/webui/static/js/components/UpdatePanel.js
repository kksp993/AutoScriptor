const UpdatePanel = {
  name: 'UpdatePanel',
  data() {
    return {
      releaseStatus: {
        kind: 'release-content-manifest',
        available: false,
        state: 'idle',
        content_version_local: '',
        remote_content_version: null,
        manifest_url: '',
        last_error: '',
        apply_cooldown_remaining_sec: 0,
        manifest_summary: {
          artifact_count: 0,
          artifacts_preview: [],
          protected_paths: [],
          touches_backend: false,
          touches_shell: false,
          has_backend_incremental_zip: false,
        },
      },
      sourceStatus: {
        kind: 'source-git',
        available: false,
        state: 'disabled',
        current_version: '',
        branch: '',
        remote_version: '',
        changelog: '',
        last_error: '',
        unavailable_reason: '',
      },
      releaseHasUpdate: false,
      releaseMessage: '',
      checkingRelease: false,
      applyingRelease: false,
      checkingSource: false,
      updatingSource: false,
    };
  },
  computed: {
    releaseVisualState() {
      if (!this.releaseStatus.available) return 'disabled';
      if (this.checkingRelease) return 'checking';
      if (this.applyingRelease) return 'applying';
      if (this.releaseHasUpdate) return 'available';
      return this.releaseStatus.state || 'idle';
    },
    releaseTag() {
      const map = {
        disabled: { label: '未配置', type: 'info' },
        idle: { label: '待检查', type: 'info' },
        checking: { label: '检查中', type: 'warning' },
        available: { label: '有更新', type: 'danger' },
        applying: { label: '应用中', type: 'warning' },
        done: { label: '已完成', type: 'success' },
        failed: { label: '失败', type: 'danger' },
      };
      return map[this.releaseVisualState] || { label: this.releaseVisualState, type: 'info' };
    },
    sourceVisualState() {
      if (this.sourceStatus.available === false) return 'disabled';
      if (this.checkingSource) return 'checking';
      if (this.updatingSource) return 'updating';
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
    manifestSummary() {
      return this.releaseStatus.manifest_summary || {};
    },
    manifestArtifacts() {
      return this.manifestSummary.artifacts_preview || [];
    },
    releaseApplyDisabled() {
      return (
        !this.releaseHasUpdate ||
        this.applyingRelease ||
        Number(this.releaseStatus.apply_cooldown_remaining_sec || 0) > 0 ||
        (this.manifestSummary.protected_paths || []).length > 0
      );
    },
    changelogLines() {
      if (!this.sourceStatus.changelog) return [];
      return this.sourceStatus.changelog.split('\n').filter(l => l.trim());
    },
  },
  async mounted() {
    await Promise.all([this.loadReleaseStatus(), this.loadSourceStatus()]);
  },
  methods: {
    async readJson(res) {
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.error || data.last_error || `HTTP ${res.status}`);
      }
      return data;
    },
    async loadReleaseStatus() {
      try {
        const res = await fetch('/api/content-update/status');
        this.releaseStatus = await this.readJson(res);
      } catch (e) {
        this.releaseStatus = {
          ...this.releaseStatus,
          available: false,
          state: 'failed',
          last_error: '读取发行版更新状态失败: ' + e.message,
        };
      }
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
          last_error: '读取源码更新状态失败: ' + e.message,
        };
      }
    },
    async checkReleaseUpdate() {
      this.checkingRelease = true;
      this.releaseMessage = '';
      try {
        const res = await fetch('/api/content-update/check', { method: 'POST' });
        const data = await this.readJson(res);
        this.releaseStatus = data;
        this.releaseHasUpdate = !!data.has_update;
        this.releaseMessage = data.message || '';
        if (data.last_error || data.state === 'failed') {
          ElementPlus.ElMessage.error('发行版更新检查失败: ' + (data.last_error || data.message || '未知错误'));
        } else if (this.releaseHasUpdate) {
          ElementPlus.ElMessage.info('发现发行版内容更新');
        } else {
          ElementPlus.ElMessage.success(data.message || '当前内容已是最新');
        }
      } catch (e) {
        this.releaseHasUpdate = false;
        this.releaseStatus = { ...this.releaseStatus, state: 'failed', last_error: e.message };
        ElementPlus.ElMessage.error('发行版更新检查失败: ' + e.message);
      } finally {
        this.checkingRelease = false;
      }
    },
    async applyReleaseUpdate() {
      try {
        await ElementPlus.ElMessageBox.confirm(
          '将按发行版 manifest 下载并校验增量文件。用户配置、账号、自定义任务和职业脚本会被保护。',
          '应用发行版更新',
          { confirmButtonText: '开始应用', cancelButtonText: '取消', type: 'warning' },
        );
      } catch {
        return;
      }
      this.applyingRelease = true;
      try {
        const res = await fetch('/api/content-update/apply', { method: 'POST' });
        const data = await this.readJson(res);
        this.releaseStatus = data;
        if (data.success) {
          this.releaseHasUpdate = false;
          ElementPlus.ElMessage.success('发行版内容更新已完成，建议重启应用后继续使用');
        } else {
          ElementPlus.ElMessage.error('发行版更新失败: ' + (data.last_error || '未知错误'));
        }
      } catch (e) {
        this.releaseStatus = { ...this.releaseStatus, state: 'failed', last_error: e.message };
        ElementPlus.ElMessage.error('发行版更新请求失败: ' + e.message);
      } finally {
        this.applyingRelease = false;
      }
    },
    async checkSourceUpdate() {
      this.checkingSource = true;
      try {
        const res = await fetch('/api/update/check', { method: 'POST' });
        const data = await this.readJson(res);
        this.sourceStatus = data;
        if (data.available === false) {
          ElementPlus.ElMessage.warning(data.unavailable_reason || data.last_error || '源码更新不可用');
        } else if (data.has_update) {
          ElementPlus.ElMessage.info('发现源码更新');
        } else {
          ElementPlus.ElMessage.success('源码仓库已是最新');
        }
      } catch (e) {
        this.sourceStatus = { ...this.sourceStatus, state: 'failed', last_error: e.message };
        ElementPlus.ElMessage.error('源码更新检查失败: ' + e.message);
      } finally {
        this.checkingSource = false;
      }
    },
    async runSourceUpdate() {
      try {
        await ElementPlus.ElMessageBox.confirm(
          '源码更新会执行 Git 拉取、依赖安装，并在完成后重启后端。此通道只适用于源码部署。',
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
        this.sourceStatus = data;
        if (data.state === 'restarting') {
          ElementPlus.ElMessage.success('源码更新完成，后端正在重启');
          this.waitForSourceRestart();
        } else if (data.success) {
          ElementPlus.ElMessage.success('源码更新完成，建议重启应用');
        } else {
          ElementPlus.ElMessage.error('源码更新失败: ' + (data.last_error || '未知错误'));
        }
      } catch (e) {
        this.sourceStatus = { ...this.sourceStatus, state: 'failed', last_error: e.message };
        ElementPlus.ElMessage.error('源码更新请求失败: ' + e.message);
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
          // 后端重启中，继续轮询。
        }
        if (attempts >= maxAttempts) {
          clearInterval(poll);
          ElementPlus.ElMessage.warning('后端重启等待超时，请手动刷新页面');
        }
      }, 3000);
    },
    shortUrl(url) {
      if (!url) return '-';
      return url.length > 80 ? url.slice(0, 77) + '...' : url;
    },
  },
  template: `
<div class="bg-white rounded-xl shadow-md p-6 h-full overflow-y-auto">

  <el-card shadow="hover" class="mb-6">
    <template #header>
      <div class="flex items-center justify-between gap-3">
        <span class="text-lg font-semibold">发行版更新</span>
        <el-tag :type="releaseTag.type" effect="dark" size="small">{{ releaseTag.label }}</el-tag>
      </div>
    </template>

    <el-descriptions :column="2" border size="default">
      <el-descriptions-item label="本地内容版本">
        <code class="text-sm">{{ releaseStatus.content_version_local || '-' }}</code>
      </el-descriptions-item>
      <el-descriptions-item label="远端内容版本">
        <code class="text-sm text-orange-600">{{ releaseStatus.remote_content_version || '-' }}</code>
      </el-descriptions-item>
      <el-descriptions-item label="更新清单" :span="2">
        <code class="text-xs break-all">{{ shortUrl(releaseStatus.manifest_url) }}</code>
      </el-descriptions-item>
      <el-descriptions-item label="文件数量" v-if="manifestSummary.artifact_count">
        {{ manifestSummary.artifact_count }}
      </el-descriptions-item>
      <el-descriptions-item label="冷却时间" v-if="releaseStatus.apply_cooldown_remaining_sec">
        {{ releaseStatus.apply_cooldown_remaining_sec }} 秒
      </el-descriptions-item>
    </el-descriptions>

    <el-alert
      v-if="!releaseStatus.available"
      class="mt-4"
      type="info"
      :closable="false"
      show-icon
      title="未配置 deploy.content_manifest_url，发行版不会联网拉取更新。"
    ></el-alert>

    <el-alert
      v-else
      class="mt-4"
      type="success"
      :closable="false"
      show-icon
      title="用户配置、账号、自定义任务和职业脚本会被保护。"
    ></el-alert>

    <el-alert
      v-if="manifestSummary.protected_paths && manifestSummary.protected_paths.length"
      class="mt-4"
      type="error"
      :closable="false"
      show-icon
      title="远端清单包含受保护用户数据路径，已阻止应用。"
    ></el-alert>

    <el-alert
      v-if="manifestSummary.touches_backend"
      class="mt-4"
      type="warning"
      :closable="false"
      show-icon
      title="本次更新包含 backend 文件，应用完成后需要重启应用。"
    ></el-alert>

    <el-alert
      v-if="manifestSummary.has_backend_incremental_zip"
      class="mt-4"
      type="success"
      :closable="false"
      show-icon
      title="清单包含 backend_incremental.zip，可配合安装器增量流程避免重新下载完整安装包。"
    ></el-alert>

    <div class="mt-4 flex flex-wrap gap-3">
      <el-button type="primary" :loading="checkingRelease" :disabled="!releaseStatus.available" @click="checkReleaseUpdate">
        <i v-if="!checkingRelease" class="fa fa-refresh mr-1"></i>检查发行版更新
      </el-button>
      <el-button type="warning" :loading="applyingRelease" :disabled="releaseApplyDisabled" @click="applyReleaseUpdate">
        <i v-if="!applyingRelease" class="fa fa-download mr-1"></i>应用内容更新
      </el-button>
    </div>

    <div v-if="releaseMessage" class="mt-3 text-sm text-slate-600">{{ releaseMessage }}</div>
  </el-card>

  <el-card v-if="manifestArtifacts.length" shadow="hover" class="mb-6">
    <template #header><span class="text-lg font-semibold">发行版更新文件</span></template>
    <el-table :data="manifestArtifacts" size="small" border>
      <el-table-column prop="kind" label="类型" width="110"></el-table-column>
      <el-table-column prop="relative_path" label="路径" min-width="260">
        <template #default="{ row }">
          <code class="text-xs">{{ row.relative_path }}</code>
        </template>
      </el-table-column>
      <el-table-column label="策略" width="120">
        <template #default="{ row }">
          <el-tag :type="row.protected ? 'danger' : 'success'" size="small">
            {{ row.protected ? '受保护' : '可更新' }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>
  </el-card>

  <el-card v-if="releaseStatus.last_error" shadow="hover" class="mb-6">
    <template #header><span class="text-lg font-semibold text-red-500">发行版错误</span></template>
    <el-alert type="error" :closable="false" show-icon>{{ releaseStatus.last_error }}</el-alert>
  </el-card>

  <el-card shadow="hover" class="mb-6">
    <template #header>
      <div class="flex items-center justify-between gap-3">
        <span class="text-lg font-semibold">源码仓库更新</span>
        <el-tag :type="sourceTag.type" effect="dark" size="small">{{ sourceTag.label }}</el-tag>
      </div>
    </template>

    <el-descriptions :column="2" border size="default">
      <el-descriptions-item label="当前 Commit">
        <code class="text-sm">{{ sourceStatus.current_version || '-' }}</code>
      </el-descriptions-item>
      <el-descriptions-item label="当前分支">
        <el-tag size="small" type="info">{{ sourceStatus.branch || '-' }}</el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="远端 Commit" v-if="sourceStatus.remote_version">
        <code class="text-sm text-orange-600">{{ sourceStatus.remote_version }}</code>
      </el-descriptions-item>
    </el-descriptions>

    <el-alert
      v-if="sourceStatus.available === false"
      class="mt-4"
      type="info"
      :closable="false"
      show-icon
      :title="sourceStatus.unavailable_reason || sourceStatus.last_error || '源码 Git 更新不可用。'"
    ></el-alert>

    <div class="mt-4 flex flex-wrap gap-3">
      <el-button :loading="checkingSource" :disabled="sourceStatus.available === false" @click="checkSourceUpdate">
        <i v-if="!checkingSource" class="fa fa-code-fork mr-1"></i>检查源码更新
      </el-button>
      <el-button v-if="sourceStatus.state === 'available'" type="warning" :loading="updatingSource" @click="runSourceUpdate">
        <i v-if="!updatingSource" class="fa fa-download mr-1"></i>拉取源码
      </el-button>
    </div>
  </el-card>

  <el-card v-if="changelogLines.length" shadow="hover" class="mb-6">
    <template #header><span class="text-lg font-semibold">源码更新日志</span></template>
    <div class="changelog-list">
      <div v-for="(line, i) in changelogLines" :key="i" class="changelog-item">
        <code class="changelog-hash">{{ line.substring(0, 8) }}</code>
        <span class="changelog-msg">{{ line.substring(9) }}</span>
      </div>
    </div>
  </el-card>

  <el-card v-if="sourceStatus.last_error && sourceStatus.available !== false" shadow="hover">
    <template #header><span class="text-lg font-semibold text-red-500">源码错误</span></template>
    <el-alert type="error" :closable="false" show-icon>{{ sourceStatus.last_error }}</el-alert>
  </el-card>

</div>`,
};
