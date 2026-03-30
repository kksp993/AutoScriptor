const OverviewPanel = {
  name: 'OverviewPanel',
  props: {
    overviewData: { type: Object, required: true },
    characterName: { type: String, default: '' },
    accounts: { type: Array, default: () => [] },
    currentAccount: { type: String, default: '' },
    charactersTree: { type: Object, default: () => ({}) },
    activeCharacter: { type: Object, default: () => ({}) },
    dispatchQueue: { type: Array, default: () => [] },
    allTasksSummary: { type: Object, default: () => ({}) },
    isDispatchRunning: { type: Boolean, default: false },
    dispatchProgress: { type: Object, default: () => ({ current: 0, total: 0, currentChar: '' }) },
    logs: { type: Array, default: () => [] },
    /** 本浏览器会话内是否已通过安全密码解锁总览（与 characterName 无关） */
    overviewSecurityUnlocked: { type: Boolean, default: false },
  },
  emits: [
    'verify-account', 'switch-character', 'add-to-dispatch', 'remove-from-dispatch',
    'run-all-dispatch', 'stop-dispatch', 'switch-account', 'refresh-overview',
    'lock-overview-security',
  ],
  data() {
    return {
      securityKey: '',
      selectedAccount: '',
      expandedServers: {},
      expandedDispatchChars: {},
      loginLoading: false,
    };
  },
  computed: {
    isLoggedIn() {
      return this.overviewSecurityUnlocked === true;
    },
    charactersList() {
      const list = [];
      for (const [srv, chars] of Object.entries(this.charactersTree)) {
        const names = Array.isArray(chars) ? chars : Object.keys(chars);
        for (const name of names) {
          list.push({ server: srv, name });
        }
      }
      return list;
    },
    sortedDispatchQueue() {
      const q = [...this.dispatchQueue];
      q.sort((a, b) => {
        const aP = this.getCharPending(a.server, a.name);
        const bP = this.getCharPending(b.server, b.name);
        if (aP === 0 && bP > 0) return 1;
        if (bP === 0 && aP > 0) return -1;
        return 0;
      });
      return q;
    },
  },
  watch: {
    currentAccount: {
      immediate: true,
      handler(val) { this.selectedAccount = val; },
    },
    charactersTree: {
      immediate: true,
      handler(tree) {
        for (const srv of Object.keys(tree)) {
          if (!(srv in this.expandedServers)) this.expandedServers[srv] = true;
        }
      },
    },
  },
  methods: {
    handleLogin() {
      if (!this.securityKey) {
        ElementPlus.ElMessage.warning('请输入安全密码');
        return;
      }
      if (this.selectedAccount && this.selectedAccount !== this.currentAccount) {
        this.loginLoading = true;
        this.$emit('switch-account', this.selectedAccount, this.securityKey);
        setTimeout(() => { this.loginLoading = false; }, 2000);
      } else {
        this.loginLoading = true;
        this.$emit('verify-account', this.securityKey);
        setTimeout(() => { this.loginLoading = false; }, 2000);
      }
      this.securityKey = '';
    },
    toggleServer(srv) {
      this.expandedServers[srv] = !this.expandedServers[srv];
    },
    isInDispatch(server, name) {
      return this.dispatchQueue.some(c => c.server === server && c.name === name);
    },
    isActiveChar(server, name) {
      return this.activeCharacter.server === server && this.activeCharacter.name === name;
    },
    getCharSummary(server, name) {
      const srv = this.allTasksSummary[server];
      return srv ? (srv[name] || null) : null;
    },
    getCharPending(server, name) {
      const s = this.getCharSummary(server, name);
      return s ? s.pending : 0;
    },
    getCharTasks(server, name) {
      const s = this.getCharSummary(server, name);
      return s ? s.tasks_flat : [];
    },
    toggleDispatchChar(server, name) {
      const key = server + '/' + name;
      this.expandedDispatchChars[key] = !this.expandedDispatchChars[key];
    },
    isDispatchCharExpanded(server, name) {
      return !!this.expandedDispatchChars[server + '/' + name];
    },
    dotColor(status) {
      return { completed: '#22c55e', pending: '#f59e0b', error: '#ef4444', disabled: '#cbd5e1' }[status] || '#cbd5e1';
    },
    dotLabel(status) {
      return { completed: '已完成', pending: '待执行', error: '错误', disabled: '未启用' }[status] || '未知';
    },
    formatProgress() {
      if (!this.isDispatchRunning) return '';
      return `(${this.dispatchProgress.current}/${this.dispatchProgress.total}) ${this.dispatchProgress.currentChar}`;
    },
    formatTimestamp(ts) {
      if (!ts || ts <= 0) return '\u2014';
      const d = new Date(ts * 1000);
      const now = new Date();
      const pad = n => String(n).padStart(2, '0');
      const time = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
      if (d.toDateString() === now.toDateString()) return `今天 ${time}`;
      const tmr = new Date(now); tmr.setDate(tmr.getDate() + 1);
      if (d.toDateString() === tmr.toDateString()) return `明天 ${time}`;
      return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${time}`;
    },
    formatCountdown(ts) {
      if (!ts || ts <= 0) return '';
      const diff = ts - Date.now() / 1000;
      if (diff <= 0) return '即将执行';
      const h = Math.floor(diff / 3600);
      const m = Math.floor((diff % 3600) / 60);
      return h > 0 ? `${h}小时${m}分钟后` : `${m}分钟后`;
    },
    schedColor(color) {
      return { green: '#22c55e', orange: '#f59e0b', red: '#ef4444' }[color] || '#94a3b8';
    },
    refreshOverview() {
      this.$emit('refresh-overview');
    },
  },
  template: `
<div class="ov-root h-full overflow-hidden">
  <!-- ===== 登录视图 ===== -->
  <transition name="ov-fade">
    <div v-if="!isLoggedIn" class="ov-login-wrap">
      <div class="ov-login-card">
        <div class="ov-login-avatar">
          <i class="fa fa-user"></i>
        </div>
        <h2 class="ov-login-title">AutoScriptor</h2>
        <p class="ov-login-subtitle">请输入<strong>安全密码</strong>验证当前账号（与角色名是否显示无关；未验证前仅显示本页）</p>

        <div class="ov-login-form">
          <el-select v-model="selectedAccount" placeholder="选择账号" size="large" class="ov-login-select">
            <el-option v-for="a in accounts" :key="a" :label="a" :value="a"></el-option>
          </el-select>
          <el-input v-model="securityKey" type="password" placeholder="安全密码" size="large"
                    show-password @keyup.enter="handleLogin" class="ov-login-input"></el-input>
          <el-button type="primary" size="large" round class="ov-login-btn"
                     :loading="loginLoading" @click="handleLogin">
            <i class="fa fa-sign-in mr-2" v-if="!loginLoading"></i>登 录
          </el-button>
        </div>
      </div>
    </div>
  </transition>

  <!-- ===== 仪表盘视图 ===== -->
  <transition name="ov-fade">
    <div v-if="isLoggedIn" class="ov-dashboard">
      <!-- 左侧面板 -->
      <div class="ov-left">
        <!-- 头像区 -->
        <div class="ov-avatar-section">
          <div class="ov-avatar-badge">
            <i class="fa fa-user"></i>
          </div>
          <div class="ov-avatar-info">
            <div class="ov-avatar-name">{{ characterName }}</div>
            <div class="ov-avatar-status">
              <span class="ov-status-dot"></span>在线
            </div>
            <button type="button" class="ov-relock-btn" @click="$emit('lock-overview-security')">重新验证</button>
          </div>
        </div>

        <!-- 角色列表 -->
        <div class="ov-char-list">
          <div class="ov-char-list-header">
            <span class="ov-section-label"><i class="fa fa-server mr-1.5"></i>角色列表</span>
            <button type="button" class="ov-refresh-btn" @click="refreshOverview">
              <i class="fa fa-repeat"></i> 刷新
            </button>
          </div>
          <div class="ov-char-list-body">
            <div v-for="(chars, srv) in charactersTree" :key="srv" class="ov-server-group">
              <div class="ov-server-header" @click="toggleServer(srv)">
                <i class="fa ov-server-chevron" :class="expandedServers[srv] ? 'fa-caret-down' : 'fa-chevron-right'"></i>
                <span class="ov-server-name">{{ srv }}</span>
                <span class="ov-server-count">{{ (Array.isArray(chars) ? chars : Object.keys(chars)).length }}</span>
              </div>
              <transition name="ov-collapse">
                <div v-show="expandedServers[srv]" class="ov-char-items">
                  <div v-for="name in (Array.isArray(chars) ? chars : Object.keys(chars))" :key="name"
                       class="ov-char-item" :class="{ 'ov-char-active': isActiveChar(srv, name) }">
                    <div class="ov-char-item-left">
                      <span class="ov-char-name">{{ name }}</span>
                      <span v-if="getCharPending(srv, name) > 0" class="ov-char-pending-badge">
                        {{ getCharPending(srv, name) }}
                      </span>
                    </div>
                    <div class="ov-char-item-actions">
                      <el-button size="small" :type="isActiveChar(srv, name) ? 'success' : 'primary'" text
                                 @click.stop="$emit('switch-character', srv, name)"
                                 :disabled="isActiveChar(srv, name)">
                        {{ isActiveChar(srv, name) ? '当前' : '上号' }}
                      </el-button>
                      <el-button size="small" text :type="isInDispatch(srv, name) ? 'info' : 'warning'"
                                 @click.stop="isInDispatch(srv, name) ? $emit('remove-from-dispatch', srv, name) : $emit('add-to-dispatch', srv, name)">
                        <i class="fa" :class="isInDispatch(srv, name) ? 'fa-check' : 'fa-plus'"></i>
                      </el-button>
                    </div>
                  </div>
                </div>
              </transition>
            </div>
            <div v-if="!Object.keys(charactersTree).length" class="ov-empty-hint">暂无角色数据</div>
          </div>
        </div>
      </div>

      <!-- 右侧面板 -->
      <div class="ov-right">
        <!-- 上区：调度控制 -->
        <div class="ov-dispatch-control">
          <div class="ov-dispatch-header">
            <span class="ov-section-label"><i class="fa fa-play-circle mr-1.5"></i>全角色调度</span>
            <span v-if="isDispatchRunning" class="ov-dispatch-progress">{{ formatProgress() }}</span>
          </div>
          <div class="ov-dispatch-sched-meta">
            <span class="ov-dispatch-meta-label">调度状态</span>
            <span class="ov-dispatch-meta-value" :style="{ color: schedColor(overviewData.scheduler && overviewData.scheduler.color) }">
              {{ (overviewData.scheduler && overviewData.scheduler.label) || '未知' }}
            </span>
            <span class="ov-dispatch-meta-sep">|</span>
            <span class="ov-dispatch-meta-label">下次执行</span>
            <span class="ov-dispatch-meta-value ov-dispatch-meta-time">
              <template v-if="overviewData.stats && overviewData.stats.pending > 0">即将执行</template>
              <template v-else>{{ overviewData.scheduler && overviewData.scheduler.next_execution ? formatTimestamp(overviewData.scheduler.next_execution) : '暂无计划' }}</template>
            </span>
            <span v-if="overviewData.scheduler && overviewData.scheduler.next_execution && !(overviewData.stats && overviewData.stats.pending > 0)" class="ov-dispatch-meta-countdown">
              {{ formatCountdown(overviewData.scheduler.next_execution) }}
            </span>
          </div>
          <div class="ov-dispatch-actions">
            <el-button type="primary" size="large" @click="$emit('run-all-dispatch')" :disabled="isDispatchRunning || !dispatchQueue.length">
              <i class="fa fa-play mr-1.5"></i>执行所有
            </el-button>
            <el-button type="danger" size="large" @click="$emit('stop-dispatch')">
              <i class="fa fa-stop mr-1.5"></i>终止
            </el-button>
            <span class="ov-dispatch-queue-count">
              队列: <strong>{{ dispatchQueue.length }}</strong> 个角色
            </span>
          </div>
          <div v-if="isDispatchRunning" class="ov-dispatch-progress-bar">
            <el-progress :percentage="dispatchProgress.total ? Math.round(dispatchProgress.current / dispatchProgress.total * 100) : 0"
                         :stroke-width="6" color="#22c55e"></el-progress>
          </div>
        </div>

        <!-- 下区：角色任务状态 -->
        <div class="ov-dispatch-status">
          <div v-if="!sortedDispatchQueue.length" class="ov-empty-dispatch">
            <i class="fa fa-inbox"></i>
            <p>从左侧角色列表点击 <strong>+</strong> 添加角色到调度队列</p>
          </div>

          <div v-for="char in sortedDispatchQueue" :key="char.server + '/' + char.name" class="ov-dispatch-card">
            <div class="ov-dispatch-card-header" @click="toggleDispatchChar(char.server, char.name)">
              <div class="ov-dispatch-card-left">
                <i class="fa" :class="isDispatchCharExpanded(char.server, char.name) ? 'fa-caret-down' : 'fa-caret-right'" style="width:14px"></i>
                <span class="ov-dispatch-card-name">{{ char.server }} / {{ char.name }}</span>
                <span v-if="isDispatchRunning && dispatchProgress.currentChar === char.server + '/' + char.name"
                      class="ov-dispatch-running-tag"><i class="fa fa-spinner fa-spin"></i> 执行中</span>
              </div>
                <div class="ov-dispatch-card-right">
                <div class="ov-task-dots">
                  <span v-for="(t, i) in getCharTasks(char.server, char.name)" :key="i"
                        class="ov-task-dot-char"
                        :style="{ color: dotColor(t.status) }"
                        :title="t.name + ' - ' + dotLabel(t.status)">●</span>
                </div>
                <el-button size="small" type="danger" text @click.stop="$emit('remove-from-dispatch', char.server, char.name)"
                           :disabled="isDispatchRunning">
                  <i class="fa fa-minus"></i>
                </el-button>
              </div>
            </div>
            <transition name="ov-collapse">
              <div v-show="isDispatchCharExpanded(char.server, char.name)" class="ov-dispatch-card-body">
                <div v-for="(t, i) in getCharTasks(char.server, char.name)" :key="i" class="ov-dispatch-task-row">
                  <span class="ov-task-dot-char ov-task-dot-char--row" :style="{ color: dotColor(t.status) }">●</span>
                  <span class="ov-dispatch-task-name">{{ t.name }}</span>
                  <span class="ov-dispatch-task-status" :style="{ color: dotColor(t.status) }">{{ dotLabel(t.status) }}</span>
                </div>
                <div v-if="!getCharTasks(char.server, char.name).length" class="ov-dispatch-no-tasks">暂无任务数据</div>
              </div>
            </transition>
          </div>
        </div>
      </div>
    </div>
  </transition>
</div>`,
};
