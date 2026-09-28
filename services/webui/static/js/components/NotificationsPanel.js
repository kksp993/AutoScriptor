const NotificationsPanel = {
  name: 'NotificationsPanel',
  props: {
    executionBusy: { type: Boolean, default: false },
  },
  data() {
    return {
      form: { enabled: false, endpoint: '', target_type: 'private', target_id: '' },
      token: '',
      tokenSet: false,
      tokenCleared: false,
      loaded: false,
      loading: false,
      saving: false,
      testing: false,
      error: '',
      preview: '',
      history: [],
      localBot: null,
      localError: '',
    };
  },
  mounted() {
    this.loadSettings(true);
    this.loadLocalBot();
  },
  methods: {
    async loadLocalBot() {
      this.localError = '';
      try {
        const result = await window.WebUIApi.request('GET', '/notify/qq/local');
        if (!result.ok) throw new Error(window.WebUIApi.errorMessage(result.data));
        this.localBot = result.data;
      } catch (error) {
        this.localError = error.message;
      }
    },
    async useLocalBot() {
      if (this.executionBusy || this.saving || this.testing || this.loading || !this.loaded) return;
      this.saving = true;
      this.error = '';
      try {
        const result = await window.WebUIApi.request('POST', '/notify/qq/local', {});
        if (!result.ok) throw new Error(window.WebUIApi.errorMessage(result.data));
        await this.loadSettings(true);
        ElementPlus.ElMessage.success('本机地址和令牌已保存，请填写接收号码并测试');
      } catch (error) {
        this.error = error.message;
      } finally {
        this.saving = false;
      }
    },
    payload() {
      const payload = { ...this.form };
      if (this.token || this.tokenCleared) payload.access_token = this.token;
      return payload;
    },
    async loadSettings(applySettings = false) {
      if (this.loading) return;
      this.loading = true;
      this.error = '';
      try {
        const result = await window.WebUIApi.request('GET', '/notify/qq');
        if (!result.ok) throw new Error(window.WebUIApi.errorMessage(result.data));
        if (applySettings) {
          const settings = result.data.settings;
          this.form = {
            enabled: settings.enabled, endpoint: settings.endpoint,
            target_type: settings.target_type, target_id: settings.target_id,
          };
          this.tokenSet = settings.token_set;
          this.token = '';
          this.tokenCleared = false;
          this.loaded = true;
        }
        this.preview = result.data.preview;
        this.history = result.data.history;
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async saveSettings() {
      if (this.executionBusy || this.saving || this.testing || !this.loaded) return;
      this.saving = true;
      this.error = '';
      try {
        const result = await window.WebUIApi.request('POST', '/notify/qq', this.payload());
        if (!result.ok) throw new Error(window.WebUIApi.errorMessage(result.data));
        await this.loadSettings(true);
        ElementPlus.ElMessage.success('QQ 通知配置已保存');
      } catch (error) {
        this.error = error.message;
      } finally {
        this.saving = false;
      }
    },
    async testSettings() {
      if (this.testing || this.saving || !this.loaded) return;
      this.testing = true;
      this.error = '';
      let deliveryError = '';
      try {
        const result = await window.WebUIApi.request('POST', '/notify/qq/test', this.payload());
        if (!result.ok) throw new Error(window.WebUIApi.errorMessage(result.data));
        ElementPlus.ElMessage.success(result.data.message);
      } catch (error) {
        deliveryError = error.message;
      } finally {
        await this.loadSettings();
        if (deliveryError) this.error = deliveryError;
        this.testing = false;
      }
    },
    clearToken() {
      this.token = '';
      this.tokenCleared = true;
    },
  },
  template: `
<section class="settings-page h-full overflow-y-auto">
  <div class="settings-hero">
    <div>
      <h2 class="settings-title">QQ 结果通知</h2>
      <p class="text-sm text-gray-500 mt-1">一个角色，一条结果。不转发运行日志，不打断游戏任务。</p>
    </div>
    <el-tag type="info">OneBot HTTP</el-tag>
  </div>

  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon class="mb-4"></el-alert>
  <el-alert v-if="executionBusy" title="任务执行中可查看与测试通知；保存配置请等待任务结束。"
    type="warning" :closable="false" show-icon class="mb-4"></el-alert>

  <article class="settings-card mb-4">
    <div class="settings-card-head"><h3>本机机器人</h3></div>
    <p v-if="localError" class="text-sm text-red-600">{{ localError }}</p>
    <template v-if="localBot && localBot.installed">
      <p class="text-sm text-gray-600">NapCat {{ localBot.version }} 已安装（不代表已登录）。地址和令牌由安装程序准备，无需复制。</p>
      <p class="text-sm text-gray-600 mt-2">运行 <code>scripts\\run.bat qq</code>，保持机器人窗口开启，在本机登录页扫码登录。</p>
      <div class="flex gap-2 mt-3">
        <el-button :disabled="executionBusy || saving || testing || loading || !loaded" @click="useLocalBot">使用本机配置</el-button>
        <a :href="localBot.login_url" target="_blank" rel="noopener noreferrer" class="text-blue-600">本机登录页（请在运行机器打开）</a>
      </div>
      <p class="text-xs text-gray-500 mt-2">使用本机配置会替换已保存的地址和令牌，并重新加载表单；接收号码和推送开关保留服务器已保存值。</p>
    </template>
    <p v-else-if="localBot" class="text-sm text-gray-600">尚未安装。运行 <code>scripts\\install.bat qq</code> 即可安装并自动生成本机 HTTP 配置。也可继续使用已有的外部 OneBot 服务。</p>
    <el-button text @click="loadLocalBot">重新检测安装</el-button>
  </article>

  <div class="settings-grid settings-grid--two">
    <article class="settings-card">
      <div class="settings-card-head"><h3><i class="fa fa-qq"></i> 接收设置</h3></div>
      <el-form label-position="top" :model="form" :disabled="loading || saving || testing || !loaded">
        <el-form-item label="自动推送">
          <el-switch v-model="form.enabled" active-text="角色执行结束后发送"></el-switch>
        </el-form-item>
        <el-form-item label="机器人 HTTP 地址">
          <el-input v-model="form.endpoint" placeholder="http://127.0.0.1:3000"></el-input>
          <p class="text-xs text-gray-500 mt-1">填写 NapCat / OneBot 的正向 HTTP 服务地址，不是 WebUI 地址。</p>
        </el-form-item>
        <el-form-item label="接收对象">
          <div class="flex gap-2 w-full">
            <el-select v-model="form.target_type" style="width:120px; flex-shrink:0" aria-label="接收类型">
              <el-option label="QQ 好友" value="private"></el-option>
              <el-option label="QQ 群" value="group"></el-option>
            </el-select>
            <el-input v-model="form.target_id" :placeholder="form.target_type === 'group' ? '群号' : '接收消息的 QQ 号'"
              aria-label="接收号码" inputmode="numeric" maxlength="20"></el-input>
          </div>
        </el-form-item>
        <el-form-item label="访问令牌（选填）">
          <el-input v-model="token" type="password" show-password autocomplete="new-password"
            :placeholder="tokenSet && !tokenCleared ? '已保存，留空保留原令牌' : '与机器人 HTTP 服务的 token 一致'"></el-input>
          <el-button v-if="tokenSet && !tokenCleared" text size="small" @click="clearToken">清除已保存令牌</el-button>
          <span v-if="tokenCleared" class="text-xs text-amber-600 mt-1">保存后清除原令牌；输入新令牌可替换。</span>
        </el-form-item>
        <div class="flex gap-2">
          <el-button type="primary" :loading="saving" :disabled="executionBusy" @click="saveSettings">保存配置</el-button>
          <el-button :loading="testing" @click="testSettings">发送测试消息</el-button>
        </div>
        <p class="text-xs text-gray-500 mt-2">测试使用当前填写值，不会保存，也不受自动推送开关影响。</p>
      </el-form>
      <el-button v-if="!loaded" class="mt-2" :loading="loading" @click="loadSettings(true)">重新加载</el-button>
    </article>

    <article class="settings-card">
      <div class="settings-card-head"><h3><i class="fa fa-comment-o"></i> 消息示例</h3></div>
      <div class="rounded-xl bg-gray-100 p-5">
        <div class="text-xs text-gray-500 mb-2">示例数据，非实际执行结果</div>
        <pre class="rounded-lg bg-white p-4 text-sm whitespace-pre-wrap break-words">{{ preview }}</pre>
      </div>
      <ul class="text-sm text-gray-600 mt-4 space-y-2">
        <li>角色编号沿用调度队列；不在队列中的手动任务仅显示角色名。</li>
        <li>重试合并为最终结果；失败、停止和中断会明确标注。</li>
        <li>当前报告任务结果，不虚构战力、活跃值或玉虚完成状态。</li>
      </ul>
      <details class="mt-5 text-sm text-gray-600">
        <summary class="cursor-pointer font-medium">首次连接怎么做？</summary>
        <ol class="mt-2 space-y-2 list-decimal pl-5">
          <li>安装时选装 QQ 机器人，或运行 scripts\\install.bat qq；再运行 scripts\\run.bat qq 并扫码登录。</li>
          <li>点击“使用本机配置”自动保存地址和令牌，再填写好友 QQ 号或机器人已加入的群号。已有外部服务也可手动填写。</li>
          <li>发送测试消息，确认 QQ 收到后开启自动推送并保存。</li>
        </ol>
        <p class="mt-2">安装是可选的，不代登录 QQ。第三方机器人存在账号风控风险，建议使用专用小号。本机服务只监听回环地址；远程服务应使用 HTTPS 和令牌，WebUI 应启用访问密码。</p>
      </details>
    </article>
  </div>

  <article class="settings-card mt-4">
    <div class="settings-card-head flex justify-between items-center">
      <h3><i class="fa fa-history"></i> 最近发送</h3>
      <el-button text :loading="loading" :disabled="testing || saving" @click="loadSettings()">刷新记录</el-button>
    </div>
    <p class="text-xs text-gray-500 mb-3">仅保留本次进程最近 20 条。发送失败不会重跑游戏任务；超时不自动重发，避免重复消息。</p>
    <el-empty v-if="!history.length" description="暂无发送记录" :image-size="60"></el-empty>
    <div v-for="(record, index) in history" :key="index" class="border-b border-gray-100 py-3">
      <div class="flex items-center gap-2 mb-2">
        <el-tag :type="record.success ? 'success' : 'danger'" size="small">{{ record.success ? '接口确认成功' : '发送失败' }}</el-tag>
        <span class="text-xs text-gray-500">{{ record.time }}</span>
      </div>
      <pre class="text-sm whitespace-pre-wrap break-words">{{ record.message }}</pre>
      <p v-if="record.error" class="text-sm text-red-600 mt-1">{{ record.error }}</p>
    </div>
  </article>
</section>`,
};
