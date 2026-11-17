const NotificationsPanel = {
  name: 'NotificationsPanel',
  components: { NotificationsTutorial },
  props: {
    executionBusy: { type: Boolean, default: false },
    embedded: { type: Boolean, default: false },
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
      history: [],
      tutorialVisible: false,
      localBot: null,
      localError: '',
      robotAccount: '',
      loginStatus: null,
      loginError: '',
      loginLoading: false,
      loginActing: false,
      loginTimer: null,
      loginController: null,
      loginPollingUntil: 0,
      disposed: false,
    };
  },
  mounted() {
    this.loadSettings(true);
    this.loadLocalBot();
  },
  beforeUnmount() {
    this.disposed = true;
    clearTimeout(this.loginTimer);
    this.loginController?.abort();
    this.loginStatus = null;
    this.token = '';
    this.tutorialVisible = false;
  },
  computed: {
    /** Configuration alignment is not QQ login or successful delivery. */
    localBotReady() {
      const bot = this.localBot;
      return !!(bot && bot.installed && bot.token_matches && bot.endpoint_matches);
    },
    /** Installed, but the saved address/token are not this robot's. */
    needsLocalSync() {
      const bot = this.localBot;
      return !!(bot && bot.installed && (!bot.token_matches || !bot.endpoint_matches));
    },
    canQuickLogin() {
      return !!this.loginStatus?.cached_accounts?.includes(this.robotAccount.trim());
    },
    canRememberAccount() {
      return !!(this.loginStatus?.logged_in && this.loginStatus.account === this.robotAccount.trim());
    },
    loginStateLabel() {
      if (this.loginActing) return '处理中';
      if (this.loginError || this.localError) return '状态未知';
      if (!this.localBot) return '检测中';
      if (!this.localBot.installed) return '未安装';
      if (!this.loginStatus) return this.loginLoading ? '查询中' : '待查询';
      return this.loginStatus.logged_in ? '已登录' : '未登录';
    },
    endpointIsLoopback() {
      return /^https?:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/i.test(String(this.form.endpoint || '').trim());
    },
    tokenPlaceholder() {
      if (this.tokenSet && !this.tokenCleared) return '已保存，留空即可';
      if (this.localBot && this.localBot.installed && this.endpointIsLoopback) return '本机机器人会自动带上，不用填';
      return '与机器人 HTTP 服务的 token 一致';
    },
  },
  methods: {
    async loadLocalBot() {
      this.localError = '';
      try {
        const result = await window.WebUIApi.request('GET', '/notify/qq/local');
        if (!result.ok) throw new Error(window.WebUIApi.errorMessage(result.data));
        this.localBot = result.data;
        if (this.localBot.installed) await this.loadLoginStatus();
      } catch (error) {
        this.localError = error.message;
      }
    },
    async loadLoginStatus() {
      if (this.disposed || this.loginLoading || this.loginActing) return;
      clearTimeout(this.loginTimer);
      this.loginLoading = true;
      this.loginError = '';
      const controller = new AbortController();
      this.loginController = controller;
      try {
        const result = await window.WebUIApi.request('GET', '/notify/qq/login', null, {
          signal: controller.signal, cache: 'no-store', headers: { 'X-QQ-Login': '1' },
        });
        if (this.disposed || controller.signal.aborted) return;
        if (!result.ok) throw new Error(window.WebUIApi.errorMessage(result.data));
        this.loginStatus = result.data;
        if (!this.robotAccount) {
          this.robotAccount = result.data.requested_account || result.data.account || result.data.remembered_account || '';
        }
        if (!result.data.logged_in && Date.now() < this.loginPollingUntil) {
          this.loginTimer = setTimeout(() => this.loadLoginStatus(), 2500);
        }
      } catch (error) {
        if (error.name !== 'AbortError' && !this.disposed) {
          this.loginStatus = null;
          this.loginError = error.message;
        }
      } finally {
        this.loginLoading = false;
        if (this.loginController === controller) this.loginController = null;
      }
    },
    async loginAction(action) {
      if (this.executionBusy || this.loginActing || this.testing || this.saving) return;
      const account = this.robotAccount.trim();
      if (['qr', 'quick', 'remember'].includes(action) && !/^[1-9][0-9]{4,19}$/.test(account)) {
        this.loginError = '请填写发送通知的小号 QQ 号';
        return;
      }
      this.loginActing = true;
      try {
        let confirmSwitch = false;
        if (action === 'qr' || action === 'quick') {
          await ElementPlus.ElMessageBox.confirm(
            '登录机器人 ' + account + '？现有机器人将重新登录，确认账号前暂停通知。桌面 QQ 和接收号码不受影响。',
            '登录 / 切换机器人账号', { type: 'warning', confirmButtonText: '确认登录', cancelButtonText: '取消' },
          );
          confirmSwitch = true;
        }
        if (this.disposed) return;
        clearTimeout(this.loginTimer);
        this.loginController?.abort();
        this.loginStatus = null;
        this.loginError = '';
        const result = await window.WebUIApi.request('POST', '/notify/qq/login', {
          action, account, confirm_switch: confirmSwitch,
        }, { cache: 'no-store', headers: { 'X-QQ-Login': '1' } });
        if (this.disposed) return;
        if (!result.ok) throw new Error(window.WebUIApi.errorMessage(result.data));
        ElementPlus.ElMessage.success(result.data.message);
        this.loginPollingUntil = Date.now() + 120000;
      } catch (error) {
        if (error !== 'cancel' && error !== 'close' && !this.disposed) this.loginError = error.message;
      } finally {
        this.loginActing = false;
        if (!this.disposed && !this.loginError) await this.loadLoginStatus();
      }
    },
    async useLocalBot() {
      if (this.executionBusy || this.loginActing || this.saving || this.testing || this.loading || !this.loaded) return;
      this.saving = true;
      this.error = '';
      try {
        await ElementPlus.ElMessageBox.confirm(
          '将连接本机机器人并重新加载设置，未保存的修改将丢失。继续吗？',
          '使用本机配置', { confirmButtonText: '继续', cancelButtonText: '取消' },
        );
        if (this.disposed) return;
        const result = await window.WebUIApi.request('POST', '/notify/qq/local', {});
        if (!result.ok) throw new Error(window.WebUIApi.errorMessage(result.data));
        await this.loadSettings(true);
        await this.loadLocalBot();
        ElementPlus.ElMessage.success('已使用本机配置');
      } catch (error) {
        if (error !== 'cancel' && error !== 'close') this.error = error.message;
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
        this.history = result.data.history;
      } catch (error) {
        this.error = error.message;
      } finally {
        this.loading = false;
      }
    },
    async saveSettings() {
      if (this.executionBusy || this.loginActing || this.saving || this.testing || !this.loaded) return;
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
      if (this.loginActing || this.testing || this.saving || !this.loaded) return;
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
        // A failed test is exactly when the running state matters, so refresh it
        // rather than leaving whatever the page loaded with.
        await this.loadLocalBot();
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
<section class="settings-page notifications-page" :class="embedded ? 'notifications-page--embedded' : 'h-full overflow-y-auto'">
  <div class="settings-hero">
    <div>
      <h2 class="settings-title">QQ 结果通知</h2>
    </div>
    <div class="notifications-actions">
      <el-button @click="tutorialVisible = true"><i class="fa fa-play-circle-o" aria-hidden="true"></i>新手教程</el-button>
    </div>
  </div>

  <el-alert v-if="error" :title="error" type="error" :closable="false" show-icon></el-alert>
  <el-alert v-if="executionBusy" title="任务执行中，请结束后再登录或保存。"
    type="warning" :closable="false" show-icon></el-alert>

  <div class="settings-grid settings-grid--two notifications-grid">
    <article class="settings-card notifications-main-card" aria-label="机器人登录">
      <div class="settings-card-head">
        <h3><span class="notifications-step">1</span>机器人登录</h3>
        <el-tag :type="loginStateLabel === '已登录' ? 'success' : 'info'" size="small">{{ loginStateLabel }}</el-tag>
      </div>
      <div class="notifications-card-body">
        <el-alert v-if="localError" :title="localError" type="error" :closable="false" show-icon></el-alert>
        <el-alert v-if="loginError" :title="loginError" type="error" :closable="false" show-icon></el-alert>
        <template v-if="localBot && localBot.installed">
          <el-form label-position="top" :disabled="executionBusy || loginActing || testing || saving">
            <el-form-item label="机器人 QQ 号">
              <el-input v-model="robotAccount" aria-label="机器人 QQ 号" placeholder="发送通知的小号"
                inputmode="numeric" maxlength="20" autocomplete="off"></el-input>
            </el-form-item>
          </el-form>
          <details v-if="loginStatus?.cached_accounts.length" class="notifications-history-accounts">
            <summary>历史账号</summary>
            <div class="notifications-actions">
              <el-button v-for="account in loginStatus.cached_accounts" :key="account" size="small"
                :disabled="executionBusy || loginActing || testing || saving" @click="robotAccount = account">{{ account }}</el-button>
            </div>
          </details>
          <div v-if="loginStatus?.logged_in" class="notifications-login-result">
            <p>当前已登录：<strong>{{ loginStatus.account }}</strong></p>
            <p v-if="!canRememberAccount" class="notifications-warning">账号不一致，请核对左侧号码或重新扫码。</p>
            <el-button type="success" :disabled="executionBusy || loginActing || testing || saving || !canRememberAccount"
              @click="loginAction('remember')">确认账号</el-button>
          </div>
          <p v-else-if="loginStatus?.running && !loginActing" class="notifications-status" role="status">{{ loginStatus.message }}</p>
          <div v-if="loginStatus && !loginStatus.logged_in && loginStatus.qr_image" class="notifications-qr">
            <img :src="loginStatus.qr_image" alt="QQ 登录二维码" width="192" height="192" referrerpolicy="no-referrer">
            <p>用 {{ robotAccount || '小号' }} 的手机 QQ 扫码</p>
          </div>
          <el-button v-if="loginStatus?.running && !loginStatus.logged_in" text
            :disabled="executionBusy || loginActing || testing || saving" @click="loginAction('refresh_qr')">刷新二维码</el-button>
        </template>
        <div v-else-if="localBot" class="notifications-install">
          <p>先安装机器人，再登录 QQ。</p>
          <code>scripts\\install.bat qq</code>
        </div>
      </div>
      <div class="notifications-card-actions notifications-actions">
        <template v-if="localBot?.installed">
          <el-button type="primary" :loading="loginActing" :disabled="executionBusy || testing || saving"
            @click="loginAction('qr')">{{ loginStatus?.logged_in ? '切换账号' : '扫码登录' }}</el-button>
          <el-button v-if="canQuickLogin" :disabled="executionBusy || loginActing || testing || saving"
            @click="loginAction('quick')">快捷登录</el-button>
          <el-button text :loading="loginLoading" :disabled="loginActing" aria-label="刷新登录状态"
            @click="loadLoginStatus">刷新状态</el-button>
        </template>
        <el-button v-else @click="loadLocalBot">重新检测</el-button>
      </div>
    </article>

    <article class="settings-card notifications-main-card" aria-label="接收通知">
      <div class="settings-card-head"><h3><span class="notifications-step">2</span>接收通知</h3></div>
      <el-form class="notifications-card-body" label-position="top" :model="form"
        :disabled="loginActing || loading || saving || testing || !loaded">
        <el-form-item label="接收对象">
          <div class="notifications-recipient">
            <el-select v-model="form.target_type" aria-label="接收类型">
              <el-option label="QQ 好友" value="private"></el-option>
              <el-option label="QQ 群" value="group"></el-option>
            </el-select>
            <el-input v-model="form.target_id" :placeholder="form.target_type === 'group' ? '群号' : '接收消息的 QQ 号'"
              aria-label="接收号码" inputmode="numeric" maxlength="20"></el-input>
          </div>
        </el-form-item>
        <el-form-item label="自动推送">
          <el-switch v-model="form.enabled" aria-label="自动推送" active-text="角色结束后通知我"></el-switch>
        </el-form-item>
        <div v-if="needsLocalSync && endpointIsLoopback" class="notifications-sync">
          <span>尚未连接本机机器人</span>
          <el-button size="small" :disabled="executionBusy" @click="useLocalBot">使用本机配置</el-button>
        </div>
        <details class="notifications-advanced">
          <summary>高级设置</summary>
          <el-form-item label="机器人 HTTP 地址">
            <el-input v-model="form.endpoint" aria-label="机器人 HTTP 地址" placeholder="http://127.0.0.1:3000"></el-input>
          </el-form-item>
          <el-form-item label="发送令牌">
            <el-input v-model="token" aria-label="发送令牌" type="password" show-password autocomplete="new-password"
              :placeholder="tokenPlaceholder"></el-input>
            <el-button v-if="tokenSet && !tokenCleared" text size="small" @click="clearToken">清除已保存令牌</el-button>
            <span v-if="tokenCleared" class="notifications-warning">保存后清除原令牌</span>
          </el-form-item>
          <div v-if="localBot?.installed" class="notifications-actions">
            <el-tag v-if="localBotReady" type="info" size="small">本机配置已匹配</el-tag>
            <el-button v-if="!needsLocalSync || !endpointIsLoopback" :disabled="executionBusy" @click="useLocalBot">使用本机配置</el-button>
          </div>
        </details>
      </el-form>
      <div class="notifications-card-actions notifications-actions">
        <el-button type="primary" :loading="saving" :disabled="executionBusy || loginActing || loading || testing || !loaded"
          @click="saveSettings">保存设置</el-button>
        <el-button :loading="testing" :disabled="loginActing || loading || saving || !loaded" @click="testSettings">发送测试</el-button>
        <el-button v-if="!loaded" :loading="loading" @click="loadSettings(true)">重新加载</el-button>
      </div>
    </article>
  </div>

  <details class="settings-card notifications-history">
    <summary>发送记录<span>{{ history.length }}</span></summary>
    <div class="notifications-actions">
      <el-button text :loading="loading" :disabled="testing || saving" @click="loadSettings()">刷新记录</el-button>
    </div>
    <el-empty v-if="!history.length" description="暂无发送记录" :image-size="60"></el-empty>
    <div v-for="(record, index) in history" :key="index" class="notifications-record">
      <div class="notifications-actions">
        <el-tag :type="record.success ? 'success' : 'danger'" size="small">{{ record.success ? '接口确认成功' : '发送失败' }}</el-tag>
        <span>{{ record.time }}</span>
      </div>
      <pre>{{ record.message }}</pre>
      <p v-if="record.error" class="notifications-error">{{ record.error }}</p>
    </div>
  </details>
  <notifications-tutorial v-if="tutorialVisible" @close="tutorialVisible = false" />
</section>`,
};
