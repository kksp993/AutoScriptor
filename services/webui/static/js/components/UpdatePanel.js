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
      localPackagePath: '',
      localDryRun: null,
      localProgress: [],
      localDryRunning: false,
      localApplying: false,
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
    localUpdateApi() {
      return window.electron && window.electron.releaseUpdate;
    },
    localDryRunOk() {
      return !!(this.localDryRun && this.localDryRun.ok);
    },
    localPlanFiles() {
      return (this.localDryRun && this.localDryRun.plan && this.localDryRun.plan.files) || [];
    },
    changelogLines() {
      if (!this.sourceStatus.changelog) return [];
      return this.sourceStatus.changelog.split('\n').filter(l => l.trim());
    },
  },
  async mounted() {
    if (this.localUpdateApi && this.localUpdateApi.onProgress) {
      this.localUpdateApi.onProgress((data) => {
        if (!data) return;
        const msg = data.message || data.type || JSON.stringify(data);
        this.localProgress.push(msg);
        if (this.localProgress.length > 80) this.localProgress.shift();
      });
    }
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
    localPackageName(path) {
      if (!path) return '';
      return String(path).split(/[\\/]/).pop();
    },
    setLocalPackage(path) {
      this.localPackagePath = path || '';
      this.localDryRun = null;
      this.localProgress = [];
    },
    handleLocalDrop(e) {
      const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
      const filePath = file && (file.path || file.name);
      if (!filePath || !String(filePath).toLowerCase().endsWith('.zip')) {
        ElementPlus.ElMessage.warning('请拖入 .zip 更新包');
        return;
      }
      if (!file.path) {
        ElementPlus.ElMessage.warning('当前环境无法读取拖入文件路径，请使用“选择更新包”');
        return;
      }
      this.setLocalPackage(file.path);
    },
    async chooseLocalPackage() {
      if (!this.localUpdateApi) {
        ElementPlus.ElMessage.warning('本地更新只在桌面版中可用');
        return;
      }
      const result = await this.localUpdateApi.choosePackage();
      if (result && !result.canceled && result.path) {
        this.setLocalPackage(result.path);
      }
    },
    async dryRunLocalPackage() {
      if (!this.localUpdateApi || !this.localPackagePath) return;
      this.localDryRunning = true;
      this.localProgress = [];
      try {
        const report = await this.localUpdateApi.dryRunPackage({ packagePath: this.localPackagePath });
        this.localDryRun = report;
        if (report.ok) {
          ElementPlus.ElMessage.success('更新包预检通过');
        } else {
          ElementPlus.ElMessage.error('更新包预检未通过');
        }
      } catch (e) {
        this.localDryRun = {
          ok: false,
          errors: [String(e && e.message ? e.message : e)],
          checks: [],
          plan: { replace: 0, add: 0, skip: 0, mkdir: 0, requiresBackendStop: false, configDefaults: { missingKeys: [] }, files: [] },
        };
        ElementPlus.ElMessage.error('预检失败: ' + (e.message || e));
      } finally {
        this.localDryRunning = false;
      }
    },
    async applyLocalPackage() {
      if (!this.localUpdateApi || !this.localPackagePath || !this.localDryRunOk) return;
      try {
        await ElementPlus.ElMessageBox.confirm(
          '将停止当前 backend，备份旧文件后应用此小版本更新包。完成后会自动重启 backend。',
          '应用本地更新包',
          { confirmButtonText: '开始更新', cancelButtonText: '取消', type: 'warning' },
        );
      } catch {
        return;
      }
      this.localApplying = true;
      this.localProgress = [];
      try {
        const result = await this.localUpdateApi.applyPackage({ packagePath: this.localPackagePath });
        if (result && result.ok) {
          this.localDryRun = result.report || this.localDryRun;
          ElementPlus.ElMessage.success('小版本更新完成，正在恢复后端');
          setTimeout(() => location.reload(), 2500);
        } else {
          this.localDryRun = result && result.report ? result.report : this.localDryRun;
          ElementPlus.ElMessage.error('更新未执行，请查看预检结果');
        }
      } catch (e) {
        ElementPlus.ElMessage.error('应用更新失败: ' + (e.message || e));
      } finally {
        this.localApplying = false;
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
        <span class="text-lg font-semibold">本地小版本更新包</span>
        <el-tag :type="localDryRunOk ? 'success' : 'info'" effect="dark" size="small">
          {{ localDryRunOk ? '预检通过' : '待预检' }}
        </el-tag>
      </div>
    </template>

    <el-alert
      v-if="!localUpdateApi"
      type="info"
      :closable="false"
      show-icon
      title="本地更新包只在 Electron 桌面版中可用。"
    ></el-alert>

    <div
      v-else
      class="mt-1"
      @dragover.prevent
      @drop.prevent="handleLocalDrop"
      style="border:1px dashed #cbd5e1;border-radius:8px;padding:16px;background:#f8fafc;"
    >
      <div class="flex flex-wrap items-center gap-3">
        <el-button @click="chooseLocalPackage">
          <i class="fa fa-folder-open mr-1"></i>选择更新包
        </el-button>
        <el-button type="primary" :loading="localDryRunning" :disabled="!localPackagePath" @click="dryRunLocalPackage">
          <i v-if="!localDryRunning" class="fa fa-check-circle mr-1"></i>先做预检
        </el-button>
        <el-button type="warning" :loading="localApplying" :disabled="!localDryRunOk" @click="applyLocalPackage">
          <i v-if="!localApplying" class="fa fa-download mr-1"></i>应用更新
        </el-button>
      </div>
      <div class="mt-3 text-sm text-slate-600">
        {{ localPackagePath ? localPackageName(localPackagePath) : '可将 AutoScriptor_Update_x.y.z.zip 拖入此处。' }}
      </div>
    </div>

    <el-descriptions v-if="localDryRun" class="mt-4" :column="3" border size="small">
      <el-descriptions-item label="当前版本">{{ localDryRun.currentVersion || '-' }}</el-descriptions-item>
      <el-descriptions-item label="目标版本">{{ localDryRun.targetVersion || '-' }}</el-descriptions-item>
      <el-descriptions-item label="兼容线">{{ localDryRun.compatLine || '-' }}</el-descriptions-item>
      <el-descriptions-item label="替换">{{ localDryRun.plan.replace }}</el-descriptions-item>
      <el-descriptions-item label="新增">{{ localDryRun.plan.add }}</el-descriptions-item>
      <el-descriptions-item label="跳过">{{ localDryRun.plan.skip }}</el-descriptions-item>
      <el-descriptions-item label="需停后端">{{ localDryRun.plan.requiresBackendStop ? '是' : '否' }}</el-descriptions-item>
      <el-descriptions-item label="补目录">{{ localDryRun.plan.mkdir }}</el-descriptions-item>
      <el-descriptions-item label="配置补项">{{ localDryRun.plan.configDefaults.missingKeys.length }}</el-descriptions-item>
    </el-descriptions>

    <el-alert
      v-if="localDryRun && localDryRun.errors && localDryRun.errors.length"
      class="mt-4"
      type="error"
      :closable="false"
      show-icon
      :title="localDryRun.errors.join('；')"
    ></el-alert>

    <el-table v-if="localPlanFiles.length" class="mt-4" :data="localPlanFiles" size="small" border>
      <el-table-column prop="action" label="动作" width="130"></el-table-column>
      <el-table-column prop="path" label="路径" min-width="260">
        <template #default="{ row }"><code class="text-xs">{{ row.path }}</code></template>
      </el-table-column>
      <el-table-column label="状态" width="120">
        <template #default="{ row }">
          <el-tag :type="row.same ? 'info' : (row.exists ? 'warning' : 'success')" size="small">
            {{ row.same ? '已一致' : (row.exists ? '将替换' : '将新增') }}
          </el-tag>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="localProgress.length" class="mt-4 text-xs text-slate-600" style="max-height:140px;overflow:auto;background:#f8fafc;border:1px solid #e2e8f0;border-radius:6px;padding:8px;">
      <div v-for="(line, i) in localProgress" :key="i">{{ line }}</div>
    </div>
  </el-card>

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
