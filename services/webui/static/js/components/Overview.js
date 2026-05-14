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
    /** 总调度 / 调度模式 / 单任务 任一路径占用 */
    executionBusy: { type: Boolean, default: false },
    logs: { type: Array, default: () => [] },
    /** 本浏览器会话内是否已通过安全密码解锁总览（与 characterName 无关） */
    overviewSecurityUnlocked: { type: Boolean, default: false },
    /** 游戏职业下拉选项（悟空、唐僧…） */
    gameProfessionOptions: { type: Array, default: () => [] },
    /** { 服务器: { 角色名: 职业 } } */
    gameProfessionsByCharacter: { type: Object, default: () => ({}) },
  },
  emits: [
    'verify-account', 'switch-character', 'add-to-dispatch', 'remove-from-dispatch',
    'reorder-dispatch',
    'run-all-dispatch', 'stop-dispatch', 'switch-account', 'refresh-overview',
    'lock-overview-security',
    'set-game-profession',
  ],
  data() {
    return {
      securityKey: '',
      selectedAccount: '',
      expandedServers: {},
      /** 至多展开一个角色详情：'server/name' 或 null */
      expandedDispatchKey: null,
      dragOverIndex: null,
      taskDetailVisible: false,
      taskDetail: null,
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
    /** 全局是否有待到期任务（全账号汇总，避免仅当前角色时与总览不一致） */
    globalPendingAny() {
      const a = this.overviewData.statsAll;
      const s = this.overviewData.stats;
      const p = (a && a.pending) || (s && s.pending) || 0;
      return p > 0;
    },
    /** 总览「下次执行」时间戳：优先全账号最早时间，否则当前角色调度器侧 */
    overviewNextDisplayTs() {
      const o = this.overviewData;
      if (!o) return null;
      if (o.overall_next_execution != null && o.overall_next_execution !== undefined) {
        return o.overall_next_execution;
      }
      const nx = o.scheduler && o.scheduler.next_execution;
      return nx != null && nx !== undefined ? nx : null;
    },
    /** 总调度或调度模式是否处于活跃/运行中 */
    isAnyScheduleActive() {
      return this.isDispatchRunning || (this.overviewData.scheduler && this.overviewData.scheduler.state === 'running');
    },
    /** 调度状态的文字说明 */
    overviewSchedHint() {
      const s = this.overviewData.scheduler;
      if (this.isDispatchRunning) return '总调度执行中：正在按队列顺序执行各角色任务';
      if (s && s.state === 'running') return '调度已激活：将自动执行到期任务';
      if (s && s.state === 'error') return '调度已暂停：连续失败，需在调度面板手动恢复';
      return '调度未激活：点击「执行所有」启动总调度，或在调度面板启动单角色调度';
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
    getCharNextExecution(server, name) {
      const s = this.getCharSummary(server, name);
      if (!s || s.next_execution == null || s.next_execution === undefined) return null;
      return s.next_execution;
    },
    /** 调度卡片右侧「下次」展示：绝对时间 + 相对倒计时（分行） */
    getCharNextExecDisplay(server, name) {
      const ts = this.getCharNextExecution(server, name);
      if (!ts) return null;
      const rel = this.formatCountdown(ts);
      return {
        abs: `下次 ${this.formatTimestamp(ts)}`,
        rel: rel || '',
      };
    },
    dispatchCharKey(server, name) {
      return server + '/' + name;
    },
    toggleDispatchChar(server, name) {
      const key = this.dispatchCharKey(server, name);
      this.expandedDispatchKey = this.expandedDispatchKey === key ? null : key;
    },
    isDispatchCharExpanded(server, name) {
      return this.expandedDispatchKey === this.dispatchCharKey(server, name);
    },
    onDragStartDispatch(e, idx) {
      if (this.executionBusy) {
        e.preventDefault();
        return;
      }
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', String(idx));
      try {
        e.dataTransfer.setData('application/x-dispatch-index', String(idx));
      } catch (_) { /* ignore */ }
    },
    onDragOverDispatchCard(e, idx) {
      if (this.executionBusy) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      this.dragOverIndex = idx;
    },
    onDropDispatchCard(e, idx) {
      if (this.executionBusy) return;
      this.dragOverIndex = null;
      let raw = e.dataTransfer.getData('text/plain');
      if (!raw) raw = e.dataTransfer.getData('application/x-dispatch-index');
      const from = parseInt(raw, 10);
      if (Number.isNaN(from) || from === idx) return;
      this.$emit('reorder-dispatch', from, idx);
    },
    onDragEndDispatch() {
      this.dragOverIndex = null;
    },
    dotColor(status) {
      return { scheduled: '#22c55e', pending: '#f59e0b', error: '#ef4444', disabled: '#cbd5e1' }[status] || '#cbd5e1';
    },
    dotLabel(status) {
      return { scheduled: '已完成', pending: '待执行', error: '错误', disabled: '未启用' }[status] || '未知';
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
    openTaskDetail(t) {
      this.taskDetail = t;
      this.taskDetailVisible = true;
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
    professionFor(server, name) {
      const srv = this.gameProfessionsByCharacter && this.gameProfessionsByCharacter[server];
      const v = srv && srv[name];
      return v || '悟空';
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
            <div v-if="activeCharacter.server && activeCharacter.name && gameProfessionOptions.length" class="ov-avatar-profession">
              <span class="ov-avatar-profession-label">职业</span>
              <el-select
                size="small"
                class="ov-avatar-profession-select"
                :model-value="professionFor(activeCharacter.server, activeCharacter.name)"
                placeholder="职业"
                filterable
                :disabled="executionBusy"
                @change="v => $emit('set-game-profession', activeCharacter.server, activeCharacter.name, v)"
              >
                <el-option v-for="p in gameProfessionOptions" :key="p" :label="p" :value="p"></el-option>
              </el-select>
            </div>
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
                       class="ov-char-item"
                       :class="{ 'ov-char-active': isActiveChar(srv, name), 'ov-char-item--no-prof': !gameProfessionOptions.length }">
                    <div class="ov-char-item-name">
                      <span class="ov-char-name">{{ name }}</span>
                      <span v-if="getCharPending(srv, name) > 0" class="ov-char-pending-badge">
                        {{ getCharPending(srv, name) }}
                      </span>
                    </div>
                    <div v-if="gameProfessionOptions.length" class="ov-char-item-prof">
                      <el-select
                        size="small"
                        class="ov-char-profession-select"
                        :model-value="professionFor(srv, name)"
                        placeholder="职业"
                        filterable
                        :disabled="executionBusy"
                        @change="v => $emit('set-game-profession', srv, name, v)"
                      >
                        <el-option v-for="p in gameProfessionOptions" :key="p" :label="p" :value="p"></el-option>
                      </el-select>
                    </div>
                    <el-button class="ov-char-btn" size="small" :type="isActiveChar(srv, name) ? 'success' : 'primary'" text
                               @click.stop="$emit('switch-character', srv, name)"
                               :disabled="executionBusy || isActiveChar(srv, name)">
                      {{ isActiveChar(srv, name) ? '当前' : '上号' }}
                    </el-button>
                    <el-button class="ov-char-btn" size="small" text :type="isInDispatch(srv, name) ? 'info' : 'warning'"
                               @click.stop="isInDispatch(srv, name) ? $emit('remove-from-dispatch', srv, name) : $emit('add-to-dispatch', srv, name)"
                               :disabled="executionBusy">
                      <i class="fa" :class="isInDispatch(srv, name) ? 'fa-check' : 'fa-plus'"></i>
                    </el-button>
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
            <span v-if="isDispatchRunning" class="ov-dispatch-progress"><i class="fa fa-spinner fa-spin"></i> 调度运行中</span>
          </div>
          <div class="ov-dispatch-sched-meta">
            <span class="ov-dispatch-meta-label">调度状态</span>
            <span class="ov-dispatch-meta-value" :style="{ color: schedColor(overviewData.scheduler && overviewData.scheduler.color) }" :title="overviewSchedHint">
              {{ (overviewData.scheduler && overviewData.scheduler.label) || '未知' }}
            </span>
            <span class="ov-dispatch-meta-sep">|</span>
            <span class="ov-dispatch-meta-label">下次执行</span>
            <span class="ov-dispatch-meta-value ov-dispatch-meta-time">
              <template v-if="!isAnyScheduleActive">-- --</template>
              <template v-else-if="globalPendingAny">即将执行</template>
              <template v-else>{{ overviewNextDisplayTs ? formatTimestamp(overviewNextDisplayTs) : '暂无计划' }}</template>
            </span>
            <span v-if="isAnyScheduleActive && overviewNextDisplayTs && !globalPendingAny" class="ov-dispatch-meta-countdown">
              {{ formatCountdown(overviewNextDisplayTs) }}
            </span>
          </div>
          <div class="text-xs text-gray-400 mt-1" style="line-height:1.4">{{ overviewSchedHint }}</div>
          <div class="ov-dispatch-actions">
            <el-button type="primary" size="large" @click="$emit('run-all-dispatch')" :disabled="!dispatchQueue.length || executionBusy">
              <i class="fa fa-play mr-1.5"></i>执行所有
            </el-button>
            <el-button type="danger" size="large" @click="$emit('stop-dispatch')">
              <i class="fa fa-stop mr-1.5"></i>终止
            </el-button>
            <span class="ov-dispatch-queue-count">
              队列: <strong>{{ dispatchQueue.length }}</strong> 个角色
            </span>
          </div>
        </div>

        <!-- 下区：角色任务状态 -->
        <div class="ov-dispatch-status">
          <div v-if="!dispatchQueue.length" class="ov-empty-dispatch">
            <i class="fa fa-inbox"></i>
            <p>从左侧角色列表点击 <strong>+</strong> 添加角色到调度队列</p>
          </div>

          <div v-for="(char, dIdx) in dispatchQueue" :key="char.server + '/' + char.name"
               class="ov-dispatch-card"
               :class="{ 'ov-dispatch-card--drag-over': dragOverIndex === dIdx && !executionBusy }"
               @dragover="onDragOverDispatchCard($event, dIdx)"
               @drop="onDropDispatchCard($event, dIdx)">
            <div class="ov-dispatch-card-top">
              <span class="ov-dispatch-drag-handle"
                    :class="{ 'ov-dispatch-drag-handle--disabled': executionBusy }"
                    :draggable="!executionBusy"
                    title="拖拽排序执行顺序"
                    @dragstart="onDragStartDispatch($event, dIdx)"
                    @dragend="onDragEndDispatch"
                    @click.stop>
                <i class="fa fa-bars"></i>
              </span>
              <div class="ov-dispatch-card-header" @click="toggleDispatchChar(char.server, char.name)">
                <div class="ov-dispatch-card-left">
                  <i class="fa" :class="isDispatchCharExpanded(char.server, char.name) ? 'fa-caret-down' : 'fa-caret-right'" style="width:14px"></i>
                  <span class="ov-dispatch-card-name">
                    <span class="ov-dispatch-card-server">{{ char.server }}</span>
                    <span class="ov-dispatch-card-character">{{ char.name }}</span>
                  </span>
                </div>
                <div class="ov-dispatch-card-right">
                  <div class="ov-task-dots">
                    <span v-for="(t, i) in getCharTasks(char.server, char.name)" :key="i"
                          class="ov-task-dot-char"
                          :style="{ color: dotColor(t.status) }"
                          :title="t.name + ' - ' + dotLabel(t.status)">●</span>
                  </div>
                  <template v-for="nx in [getCharNextExecDisplay(char.server, char.name)]" :key="char.server + '/' + char.name + '-next'">
                    <span v-if="!isDispatchRunning && nx" class="ov-char-next-exec">
                      <span class="ov-char-next-exec-line1">{{ nx.abs }}</span>
                      <span v-if="nx.rel" class="ov-char-next-exec-line2">{{ nx.rel }}</span>
                    </span>
                  </template>
                  <el-button size="small" type="danger" text @click.stop="$emit('remove-from-dispatch', char.server, char.name)"
                             :disabled="executionBusy">
                    <i class="fa fa-minus"></i>
                  </el-button>
                </div>
              </div>
            </div>
            <transition name="ov-collapse">
              <div v-show="isDispatchCharExpanded(char.server, char.name)" class="ov-dispatch-card-body">
                <div class="ov-dispatch-task-grid">
                  <div v-for="(t, i) in getCharTasks(char.server, char.name)" :key="(t.path || t.name) + '-' + i" class="ov-dispatch-task-block">
                    <div class="ov-dispatch-task-cell" @click="openTaskDetail(t)">
                      <span class="ov-task-dot-char ov-task-dot-char--cell" :style="{ color: dotColor(t.status) }" :title="t.name + ' - ' + dotLabel(t.status)">●</span>
                      <div class="flex-1 min-w-0 flex items-center gap-1">
                        <span class="ov-dispatch-task-name ov-dispatch-task-name--cell flex-1 min-w-0">{{ t.name }}</span>
                        <span v-if="t.custom" class="task-custom-tag flex-shrink-0">自定义</span>
                        <span v-if="t.beta" class="task-beta-tag flex-shrink-0">Beta</span>
                      </div>
                      <i class="fa fa-info-circle ov-task-help-chev text-gray-400" title="任务简介"></i>
                    </div>
                  </div>
                </div>
                <div v-if="!getCharTasks(char.server, char.name).length" class="ov-dispatch-no-tasks">暂无任务数据</div>
              </div>
            </transition>
          </div>
        </div>
      </div>
    </div>
  </transition>
  <el-dialog v-model="taskDetailVisible" :title="taskDetail ? taskDetail.name : ''" width="520px" destroy-on-close align-center @closed="taskDetail = null">
    <div v-if="taskDetail" class="space-y-3 text-sm">
      <p v-if="taskDetail.custom" class="task-doc-custom-line">*自定义任务：任意 Python 与主程序同进程运行；请仅使用可信来源脚本，风险自负。</p>
      <p v-if="taskDetail.beta" class="task-doc-beta-line">*该任务为 Beta 实验功能：自动化流程、界面识别或参数含义可能随版本快速调整，不保证与当前游戏完全一致；请谨慎启用并及时反馈问题。</p>
      <p v-if="taskDetail.task_description" class="text-gray-700 leading-relaxed">{{ taskDetail.task_description }}</p>
      <p v-if="taskDetail.task_doc_flow" class="text-xs text-gray-500 leading-relaxed whitespace-pre-wrap">{{ taskDetail.task_doc_flow }}</p>
      <p v-if="taskDetail.path" class="text-xs text-gray-400 font-mono break-all">路径：{{ taskDetail.path }}</p>
    </div>
  </el-dialog>
</div>`,
};
