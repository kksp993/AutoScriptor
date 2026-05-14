const { createApp, ref, reactive, computed, nextTick, watch } = Vue;

/** 临时关闭「脚本画布」侧边入口与主区面板；改为 true 可恢复 */
const FEATURE_SCRIPT_CANVAS = false;

const app = createApp({
  components: { AppSidebar, NewsPanel, OverviewPanel, SchedulerPanel, TaskPanel, SettingsPanel, EditorPanel, CanvasPanel, ErrorArchivesPanel, UpdatePanel, AboutPanel },
  setup() {
    const configData = reactive({});
    const activeTab = ref('news');
    const logs = ref([]);
    const characterName = ref('');
    const schedulerStatus = reactive({ state: 'pending', label: '待运行', color: 'green', consecutive_errors: 0 });
    const overviewData = reactive({
      scheduler: { state: 'pending', label: '待运行', color: 'green', consecutive_errors: 0, next_execution: null },
      stats: { total: 0, enabled: 0, pending: 0, scheduled: 0, disabled: 0 },
      /** 当前账号下所有角色任务汇总（总览「下次执行」与「即将执行」用） */
      statsAll: { total: 0, enabled: 0, pending: 0, scheduled: 0, error: 0, disabled: 0 },
      /** 全账号最早一次计划执行时间（与各角色 next_execution 一致口径） */
      overall_next_execution: null,
      upcoming: [],
      runtime: { initialized: false, has_mixctrl: false, has_mumu: false, has_bg: false, has_vlm: false },
    });

    /** 错误汇总「前往标注」等：切换到编辑器后由 EditorPanel 消费并清空 */
    const pendingEditorImportUrl = ref('');

    const editModalVisible = ref(false);
    const editTaskData = ref({});
    const editTaskPath = ref('');
    const editTaskParent = ref(null);
    const editTaskKey = ref('');
    const activeGroupPath = ref('');
    const paramEnumOptions = reactive({});
    const PARAM_KEY_LABELS = {
      battle_config: '战斗配置',
      battle_flow: '战斗招式',
      battle_loop:'战斗循环次数',
      battle_times: '战斗轮数',
      speed_x: '战斗加速',
      has_cd: '关卡有CD',
      battle_weight: '战斗配比',
      difficulty: '难度选择',
      diff: '难度',
      preference: '关卡偏好',
      conquer_TianMo: '天魔挑战',
      method: '完成方式',
      Bingku_WuQi: '冰窟武器',
      Bingku_YiFu: '冰窟防具',
      Bingku_ChiBang: '冰窟翅膀',
      Changgui_WuQi: '常规武器',
      Changgui_YiFu: '常规防具',
      Changgui_ChiBang: '常规翅膀',
      HuShenZhiYa: '虎神之崖',
      CangLongYouGu: '苍龙幽谷',
      MingHaiZhiYuan: '溟海之渊',
      lingqi: '灵气',
      lingqi_priority: '灵气优先级',
      YanHao: '岩貉星宫',
      QuanShen: '犬神星宫',
      LangWang: '狼王星宫',
      HuWang: '虎王星宫',
      ZhangWang: '獐王星宫',
      AnShen: '犴神星宫',
      TuShen: '兔神星宫',
      cancel_on_failed: '不用点券复活',
      claim_past: '是否解锁过去',
    };
    function paramLabel(key) {
      return PARAM_KEY_LABELS[key] || key;
    }
    const addDialogVisible = ref(false);
    const addForm = reactive({ account: '', password: '', security_key: '' });

    // ── 账号管理 ──
    const accounts = ref([]);
    const currentAccount = ref('');
    const accountDialogVisible = ref(false);
    const newAccountForm = reactive({ name: '', account: '', password: '', server: '', character_name: '', security_key: '' });

    // ── 角色管理 ──
    const activeCharacter = reactive({ server: '', name: '' });
    /** 与后端同步当前 UI 选中角色，供 /api/run 在执行前写入 config */
    function runCharacterPayload() {
      const s = activeCharacter.server;
      const n = activeCharacter.name;
      if (s && n) return { server: s, character: n };
      return {};
    }
    const charactersTree = reactive({});
    const characterDialogVisible = ref(false);
    const newCharacterForm = reactive({ server: '', character: '' });

    /** 各角色游戏职业（悟空、唐僧…），与账号 JSON 同步 */
    const gameProfessionsByCharacter = reactive({});
    const gameProfessionOptions = ref([]);

    function mergeGameProfessionsFromPayload(data) {
      if (!data || typeof data !== 'object') return;
      if (data.game_professions_by_character) {
        Object.keys(gameProfessionsByCharacter).forEach((k) => delete gameProfessionsByCharacter[k]);
        Object.assign(gameProfessionsByCharacter, data.game_professions_by_character);
      }
      if (Array.isArray(data.game_profession_options)) {
        gameProfessionOptions.value = data.game_profession_options;
      }
    }

    async function setGameProfession(server, character, game_profession) {
      try {
        const res = await API.postRaw('/characters/game_profession', { server, character, game_profession });
        const payload = await res.json().catch(() => ({}));
        if (!res.ok) {
          ElementPlus.ElMessage.error((payload && payload.error) || '保存职业失败');
          return;
        }
        mergeGameProfessionsFromPayload(payload);
        if (payload.game && payload.game.game_profession && configData.game) {
          configData.game.game_profession = payload.game.game_profession;
        }
        ElementPlus.ElMessage.success('职业已保存');
      } catch (e) {
        ElementPlus.ElMessage.error('保存职业失败: ' + e);
      }
    }

    // ── 调度队列 ──
    const dispatchQueue = ref([]);
    const allTasksSummary = reactive({});
    const isDispatchRunning = ref(false);
    const dispatchProgress = reactive({
      currentChar: '',
      /** 点击「执行所有」时，队列内各角色待执行 (pending / 黄点) 任务总数 */
      totalTaskCount: 0,
      /** 本次调度已消化黄点任务数（与总览圆点一致，随 all_tasks_summary 动态刷新） */
      completedTaskCount: 0,
    });
    const _dispatchAbort = ref(false);
    /** 「执行所有」开始时各角色 pending 快照，key = server/name */
    const _dispatchPendingSnap = ref(null);
    /** 同上时刻的队列顺序，用于计算当前角色序号 */
    const _dispatchQueueOrder = ref([]);

    /** 后台 /api/run 直接执行线程是否存活（单任务、队列逐步执行） */
    const directRunRunning = ref(false);

    /** 总调度 / 调度模式 / 单任务互斥：任一路径占用即禁止其它入口 */
    const executionBusy = computed(() => {
      if (isDispatchRunning.value) return true;
      if (directRunRunning.value) return true;
      return schedulerStatus.state === 'running';
    });

    // ── 密码保护 ──
    const authRequired = ref(false);
    const loginPassword = ref('');

    // 总览「安全密码」与角色名解耦：characterName 来自账号 JSON，刷新后即有，不代表已验证。
    // 是否已解锁以服务端 HttpOnly Cookie + GET /api/credential/status 为准，禁止仅靠本地缓存「重放」绕过。
    const overviewSecurityUnlocked = ref(false);

    function markOverviewSecurityUnlocked() {
      overviewSecurityUnlocked.value = true;
    }
    async function clearOverviewSecurityUnlocked() {
      overviewSecurityUnlocked.value = false;
      try {
        await fetch('/api/credential/revoke', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ _timestamp: Date.now() / 1000 }),
        });
      } catch (e) { /* ignore */ }
    }
    async function fetchCredentialStatus() {
      try {
        const data = await API.get('/credential/status');
        if (data && !data.error) {
          overviewSecurityUnlocked.value = !!data.unlocked;
        }
      } catch (e) {
        overviewSecurityUnlocked.value = false;
      }
    }

    // ── 主题（固定浅色） ──
    const currentTheme = ref('light');

    const filteredConfig = computed(() => {
      const clone = { ...configData };
      delete clone.tasks;
      delete clone.encryption;
      delete clone.status;
      delete clone.current_account;
      delete clone.active_character;
      delete clone.characters_summary;
      delete clone.game_professions_by_character;
      delete clone.game_profession_options;
      return clone;
    });

    /** 用于拼接任务路径前缀；一般任务页内同时含「一般任务」「活动任务」两棵顶层树，前缀由树路径自带，故 general 为空。 */
    const activeTabLabel = computed(() => {
      return { daily: '每日任务', weekly: '每周任务', general: '', custom: '自定义任务' }[activeTab.value] || '';
    });

    const pageTitle = computed(() => {
      const map = {
        news: '资讯', overview: '总览', scheduler: '调度', editor: '编辑器', canvas: '脚本画布',
        errorArchives: '错误汇总', updater: '检查更新', settings: '设置', about: '关于',
        daily: '每日任务', weekly: '每周任务', general: '一般任务', custom: '自定义任务',
      };
      return map[activeTab.value] || '';
    });

    const currentTasks = computed(() => {
      const t = configData.tasks || {};
      if (activeTab.value === 'daily') return t['每日任务'] || {};
      if (activeTab.value === 'weekly') return t['每周任务'] || {};
      if (activeTab.value === 'general') {
        return {
          一般任务: t['一般任务'] || {},
          活动任务: t['活动任务'] || t['event_task'] || {},
        };
      }
      if (activeTab.value === 'custom') return t['自定义任务'] || {};
      return {};
    });

    /** 顶栏在「未选完整 server+name」时显示的单行名（来自配置） */
    const characterDisplayName = computed(() => characterName.value || '');

    const charactersList = computed(() => {
      const list = [];
      for (const [srv, chars] of Object.entries(charactersTree)) {
        const names = Array.isArray(chars) ? chars : Object.keys(chars);
        for (const charName of names) {
          list.push({ server: srv, name: charName });
        }
      }
      return list;
    });

    // ── API helpers ──
    const API = {
      async get(url) {
        return (await fetch('/api' + url, { credentials: 'same-origin' })).json();
      },
      async post(url, body) {
        return (await fetch('/api' + url, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...body, _timestamp: Date.now() / 1000 }),
        })).json();
      },
      async postRaw(url, body) {
        return fetch('/api' + url, {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...body, _timestamp: Date.now() / 1000 }),
        });
      },
    };

    // ── data fetching ──
    let _lastRefreshAt = 0;
    const REFRESH_COOLDOWN = 10000;

    async function refreshConfig(force = false) {
      const now = Date.now();
      if (!force && now - _lastRefreshAt < REFRESH_COOLDOWN) return;
      _lastRefreshAt = now;
      try {
        const data = await API.get('/refresh');
        if (data && !data.error) {
          Object.keys(configData).forEach(k => delete configData[k]);
          Object.assign(configData, data);
          mergeGameProfessionsFromPayload(data);
          if (data.game) characterName.value = data.game.character_name || '';
          if (data.active_character) {
            Object.assign(activeCharacter, data.active_character);
          }
          if (data.characters_summary) {
            Object.keys(charactersTree).forEach(k => delete charactersTree[k]);
            Object.assign(charactersTree, data.characters_summary);
          }
        }
      } catch (e) { console.error('Refresh failed:', e); }
    }

    async function fetchOverview() {
      try {
        const data = await API.get('/overview');
        if (data && !data.error) {
          Object.assign(overviewData.scheduler, data.scheduler);
          Object.assign(overviewData.stats, data.stats);
          if (data.stats_all) Object.assign(overviewData.statsAll, data.stats_all);
          if (data.overall_next_execution !== undefined) {
            overviewData.overall_next_execution = data.overall_next_execution;
          }
          overviewData.upcoming = data.upcoming || [];
          if (data.runtime) Object.assign(overviewData.runtime, data.runtime);
          Object.assign(schedulerStatus, {
            state: data.scheduler.state, label: data.scheduler.label,
            color: data.scheduler.color, consecutive_errors: data.scheduler.consecutive_errors,
          });
        }
      } catch (e) { /* ignore */ }
    }

    async function fetchSchedulerStatus() {
      try {
        const data = await API.get('/scheduler/status');
        Object.assign(schedulerStatus, data);
      } catch (e) { /* ignore */ }
    }

    async function fetchRunStatus() {
      try {
        const st = await API.get('/run/status');
        directRunRunning.value = !!(st && st.running);
      } catch (e) { /* ignore */ }
    }

    // ── WebSocket for logs (native WS, not Socket.IO) ──
    let ws = null;
    function setupWebSocket() {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      ws = new WebSocket(`${proto}//${location.host}/ws/logs`);
      const ansi_up = new AnsiUp();
      let buffer = [];
      let scheduled = false;
      let taskConfigRefreshTimer = null;
      const TASK_CONFIG_REFRESH_DEBOUNCE_MS = 400;

      const scheduleTaskConfigRefresh = () => {
        if (taskConfigRefreshTimer) clearTimeout(taskConfigRefreshTimer);
        taskConfigRefreshTimer = setTimeout(() => {
          taskConfigRefreshTimer = null;
          refreshConfig(true);
        }, TASK_CONFIG_REFRESH_DEBOUNCE_MS);
      };

      const LOG_NEEDS_TASK_REFRESH =
        /(所有任务执行完成|任务执行被中断|任务执行已被中断|Task \[END\])/;

      const ANSI_STRIP = /\x1b\[[0-9;]*m/g;
      const LOG_LEVEL_ORDER = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };
      function stripAnsi(s) {
        return String(s).replace(ANSI_STRIP, '');
      }
      function lineLogLevel(line) {
        const m = stripAnsi(line).match(/\|\s*([A-Z]{4,9})\s*\|/);
        return m ? m[1] : null;
      }
      function webuiMinLogLevel() {
        const raw = (configData.deploy && configData.deploy.log_level) || 'debug';
        const name = String(raw).trim().toUpperCase();
        return LOG_LEVEL_ORDER[name] != null ? LOG_LEVEL_ORDER[name] : LOG_LEVEL_ORDER.INFO;
      }
      function shouldShowLogLine(line) {
        const lv = lineLogLevel(line);
        if (lv === null) return true;
        const n = LOG_LEVEL_ORDER[lv];
        if (n == null) return true;
        return n >= webuiMinLogLevel();
      }

      const flush = () => {
        if (buffer.length) {
          logs.value.push(...buffer);
          buffer = [];
          if (logs.value.length > 2000) logs.value.splice(0, logs.value.length - 2000);
          scrollToBottom();
        }
        scheduled = false;
      };

      ws.onmessage = (event) => {
        let data;
        try { data = JSON.parse(event.data).data || ''; } catch { data = event.data; }
        const lines = String(data).split('\n');
        let needTaskConfigRefresh = false;
        for (const line of lines) {
          if (!shouldShowLogLine(line)) continue;
          if (LOG_NEEDS_TASK_REFRESH.test(line)) needTaskConfigRefresh = true;
          buffer.push({ html: ansi_up.ansi_to_html(line) });
        }
        if (needTaskConfigRefresh) {
          scheduleTaskConfigRefresh();
          fetchOverview();
          fetchAllTasksSummary();
        }
        if (!scheduled) {
          scheduled = true;
          requestAnimationFrame(flush);
        }
      };
      ws.onclose = () => { setTimeout(setupWebSocket, 3000); };
    }

    function scrollToBottom() {
      nextTick(() => {
        for (const id of ['logContainer', 'logContainerOverview', 'logContainerScheduler']) {
          const lc = document.getElementById(id);
          if (lc) lc.scrollTop = lc.scrollHeight;
        }
      });
    }

    // ── actions ──
    async function startRun() {
      if (!overviewSecurityUnlocked.value) {
        ElementPlus.ElMessage.warning('请先验证安全密码后再执行任务');
        return;
      }
      if (!characterName.value && !activeCharacter.name) {
        ElementPlus.ElMessage.warning('请先验证账号密码后再执行任务');
        return;
      }
      if (isDispatchRunning.value) {
        ElementPlus.ElMessage.warning('总览队列正在执行，请等待结束或先点「终止」');
        return;
      }
      if (directRunRunning.value) {
        ElementPlus.ElMessage.warning('单任务或队列正在执行中，请先终止');
        return;
      }
      const tasks = [];

      if (activeTab.value === 'overview' || activeTab.value === 'scheduler') {
        tasks.push(...collectEnabledLeafTaskPaths(configData.tasks || {}));
      } else {
        const base = (activeTabLabel.value ? activeTabLabel.value + '/' : '') +
                     (activeGroupPath.value ? activeGroupPath.value + '/' : '');
        function traverse(data, path = '') {
          for (const [key, item] of Object.entries(data)) {
            if (item.hasOwnProperty('on')) {
              if (item.on && item._due) tasks.push(base + path + key);
            } else { traverse(item, path + key + '/'); }
          }
        }
        let subtree = currentTasks.value;
        if (activeGroupPath.value) {
          for (const k of activeGroupPath.value.split('/')) {
            if (!k) continue;
            subtree = (subtree && typeof subtree === 'object') ? subtree[k] : undefined;
          }
          if (!subtree || typeof subtree !== 'object') subtree = {};
        }
        traverse(subtree);
      }

      const isSchedulerView = activeTab.value === 'overview' || activeTab.value === 'scheduler';
      if (!tasks.length && !isSchedulerView) {
        ElementPlus.ElMessage.info('暂无待执行的任务');
        return;
      }
      try {
        const res = await API.postRaw('/run', { tasks, activate_scheduler: true, ...runCharacterPayload() });
        const data = await res.json();
        if (res.status === 409) {
          ElementPlus.ElMessage.warning((data && data.message) || '执行冲突，请先终止其它任务');
          await fetchRunStatus();
          return;
        }
        if (res.status === 400) { ElementPlus.ElMessage.error(data.message || '角色切换失败'); return; }
        if (res.status === 403) {
          if (data && data.need_credential_unlock) await fetchCredentialStatus();
          ElementPlus.ElMessage.warning((data && data.message) || '请先验证安全密码后再执行任务');
          return;
        }
        fetchSchedulerStatus();
        fetchOverview();
        fetchRunStatus();
        if (res.ok && isSchedulerView && !tasks.length) {
          ElementPlus.ElMessage.success('调度器已启动，到期任务将自动执行');
        }
      } catch (e) { console.error('Run error:', e); }
    }

    async function runSingleTask(taskPath) {
      if (!overviewSecurityUnlocked.value) {
        ElementPlus.ElMessage.warning('请先验证安全密码后再执行任务');
        return;
      }
      if (!characterName.value && !activeCharacter.name) {
        ElementPlus.ElMessage.warning('请先验证账号密码后再执行任务');
        return;
      }
      if (isDispatchRunning.value) {
        ElementPlus.ElMessage.warning('总览队列正在执行，请等待结束或先终止');
        return;
      }
      if (directRunRunning.value) {
        ElementPlus.ElMessage.warning('已有任务正在执行，请先终止');
        return;
      }
      if (schedulerStatus.state === 'running') {
        ElementPlus.ElMessage.warning('调度器运行中，请先停止调度再跑单任务');
        return;
      }
      const fullPath = (activeTabLabel.value ? activeTabLabel.value + '/' : '') + taskPath;
      try {
        const res = await API.postRaw('/run', { tasks: [fullPath], activate_scheduler: false, ...runCharacterPayload() });
        const data = await res.json();
        if (res.status === 409) {
          ElementPlus.ElMessage.warning((data && data.message) || '执行冲突，请先终止其它任务');
          await fetchRunStatus();
          return;
        }
        if (res.status === 400) { ElementPlus.ElMessage.error(data.message || '角色切换失败'); return; }
        if (res.status === 403) {
          if (data && data.need_credential_unlock) await fetchCredentialStatus();
          ElementPlus.ElMessage.warning((data && data.message) || '请先验证安全密码后再执行任务');
          return;
        }
        ElementPlus.ElMessage.success('已加入队列: ' + taskPath.split('/').pop());
        fetchSchedulerStatus();
        fetchOverview();
        fetchRunStatus();
      } catch (e) { ElementPlus.ElMessage.error('执行失败: ' + e); }
    }

    function _resetDispatchProgress() {
      dispatchProgress.currentChar = '';
      dispatchProgress.totalTaskCount = 0;
      dispatchProgress.completedTaskCount = 0;
      _dispatchPendingSnap.value = null;
      _dispatchQueueOrder.value = [];
    }

    /** 某角色黄点（pending）数量，与总览圆点一致 */
    function _pendingTaskCountForChar(server, name) {
      const s = allTasksSummary[server]?.[name];
      if (!s) return 0;
      return Math.max(0, Number(s.pending) || 0);
    }

    /** 收集当前配置树下所有已启用的任务路径（不判断到期，仅供激活调度器时使用） */
    function collectEnabledLeafTaskPaths(data, path = '') {
      const tasks = [];
      for (const [key, item] of Object.entries(data || {})) {
        if (!item || typeof item !== 'object') continue;
        if (Object.prototype.hasOwnProperty.call(item, 'on')) {
          if (item.on && Object.prototype.hasOwnProperty.call(item, 'next_exec_time')) {
            tasks.push(path + key);
          }
        } else {
          tasks.push(...collectEnabledLeafTaskPaths(item, path + key + '/'));
        }
      }
      return tasks;
    }

    /** 只收集后端判定为到期（_due=true）的任务路径，供直接执行使用 */
    function collectDueLeafTaskPaths(data, path = '') {
      const tasks = [];
      for (const [key, item] of Object.entries(data || {})) {
        if (!item || typeof item !== 'object') continue;
        if (Object.prototype.hasOwnProperty.call(item, 'on')) {
          if (item.on && item._due) {
            tasks.push(path + key);
          }
        } else {
          tasks.push(...collectDueLeafTaskPaths(item, path + key + '/'));
        }
      }
      return tasks;
    }

    async function unifiedStop() {
      _dispatchAbort.value = true;
      isDispatchRunning.value = false;
      _resetDispatchProgress();
      try {
        await API.post('/stop', {});
      } catch (e) {
        console.error('Stop error:', e);
      }
      await fetchSchedulerStatus();
      await fetchRunStatus();
      await fetchOverview();
      await fetchAllTasksSummary();
    }

    function stopRun() {
      unifiedStop();
    }

    async function verifyAccount(securityKeyDirect) {
      try {
        let key = securityKeyDirect;
        if (!key) {
          const { value } = await ElementPlus.ElMessageBox.prompt(
            '请输入安全密码', '账号验证',
            { inputType: 'password', confirmButtonText: '验证', cancelButtonText: '取消' });
          key = value;
        }
        const res = await API.postRaw('/verify', { security_key: key });
        const data = await res.json().catch(() => ({}));
        if (res.ok && data && !data.error) {
          characterName.value = data.character_name || '';
          if (data.active_character) Object.assign(activeCharacter, data.active_character);
          if (!configData.game) configData.game = {};
          configData.game.character_name = characterName.value;
          await refreshConfig(true);
          await fetchCredentialStatus();
          fetchOverview();
          fetchAllTasksSummary();
          loadDispatchQueue();
          fetchAccounts();
          markOverviewSecurityUnlocked();
        } else if (!res.ok) {
          ElementPlus.ElMessage.error(data.error || '验证失败，请检查安全密码');
        }
      } catch (e) { /* cancelled */ }
    }

    async function resetScheduler() {
      try {
        const data = await API.post('/scheduler/reset', {});
        Object.assign(schedulerStatus, data);
        Object.assign(overviewData.scheduler, data);
        ElementPlus.ElMessage.success('调度器已恢复');
      } catch (e) { ElementPlus.ElMessage.error('恢复失败: ' + e); }
    }

    function _enumMetaPath(ep) {
      if (typeof ep === 'string') return ep;
      if (ep && typeof ep === 'object' && ep.enum) return ep.enum;
      return null;
    }

    function enumParamIsMultiple(key) {
      const m = editTaskData.value?.param_meta?.[key];
      if (m && typeof m === 'object' && !Array.isArray(m) && 'multiple' in m) {
        return m.multiple === true;
      }
      if (typeof m === 'string') {
        const v = editTaskData.value?.params?.[key];
        return Array.isArray(v);
      }
      const v = editTaskData.value?.params?.[key];
      return Array.isArray(v);
    }

    const tableRowsCache = reactive({});

    function _filterParamsToRegisteredKeys(cloned) {
      const pk = cloned.param_keys;
      if (!cloned.params || typeof cloned.params !== 'object' || !Array.isArray(pk) || !pk.length) return;
      const next = {};
      for (const k of pk) {
        if (Object.prototype.hasOwnProperty.call(cloned.params, k)) next[k] = cloned.params[k];
      }
      cloned.params = next;
    }

    function openEditModal(key, data, path, parent) {
      const cloned = JSON.parse(JSON.stringify(data));
      if (cloned.params && typeof cloned.params === 'object') {
        delete cloned.params.profession;
      }
      if (cloned.param_meta && typeof cloned.param_meta === 'object') {
        delete cloned.param_meta.profession;
      }
      _filterParamsToRegisteredKeys(cloned);
      const meta = (cloned && cloned.param_meta) || {};
      for (const [pk, mp] of Object.entries(meta)) {
        if (mp && typeof mp === 'object' && mp.multiple === false && cloned.params && Array.isArray(cloned.params[pk]) && cloned.params[pk].length === 1) {
          cloned.params[pk] = cloned.params[pk][0];
        }
      }
      editTaskData.value = cloned;
      editTaskPath.value = path || key;
      editTaskParent.value = parent || currentTasks.value;
      editTaskKey.value = key;
      Object.keys(paramEnumOptions).forEach(k => delete paramEnumOptions[k]);
      Object.keys(tableRowsCache).forEach(k => delete tableRowsCache[k]);
      const paths = Object.values(meta).map(_enumMetaPath).filter(Boolean);
      for (const [pk, mp] of Object.entries(meta)) {
        if (mp && typeof mp === 'object' && mp.type === 'table' && mp.columns) {
          for (const [col, colMeta] of Object.entries(mp.columns)) {
            if (colMeta.enum) paths.push(colMeta.enum);
          }
        }
      }
      const uniquePaths = [...new Set(paths)];
      if (uniquePaths.length) {
        API.post('/enum-options', { paths: uniquePaths, task_path: editTaskPath.value || '' }).then(map => {
          Object.entries(meta).forEach(([pk, ep]) => {
            if (ep && typeof ep === 'object' && ep.type === 'table' && ep.columns) {
              for (const [col, colMeta] of Object.entries(ep.columns)) {
                if (colMeta.enum && map[colMeta.enum]) {
                  paramEnumOptions[pk + '.' + col] = map[colMeta.enum];
                }
              }
            } else {
              const p = _enumMetaPath(ep);
              if (p) paramEnumOptions[pk] = map[p] || [];
            }
          });
          _initTableRowsCache(meta);
          editModalVisible.value = true;
        }).catch(() => { _initTableRowsCache(meta); editModalVisible.value = true; });
      } else { _initTableRowsCache(meta); editModalVisible.value = true; }
    }

    function _initTableRowsCache(meta) {
      const params = editTaskData.value?.params || {};
      for (const [pk, mp] of Object.entries(meta)) {
        if (mp && typeof mp === 'object' && mp.type === 'table') {
          const dict = params[pk];
          if (dict && typeof dict === 'object' && !Array.isArray(dict)) {
            tableRowsCache[pk] = Object.entries(dict).map(([rk, rv]) => ({ _rowKey: rk, ...rv }));
          }
        }
      }
    }

    function isTableParam(key) {
      const m = editTaskData.value?.param_meta?.[key];
      return m && typeof m === 'object' && m.type === 'table';
    }

    function getTableRows(key) {
      return tableRowsCache[key] || [];
    }

    function getTableColumns(key) {
      const m = editTaskData.value?.param_meta?.[key];
      return (m && m.columns) || {};
    }

    function getTableColumnLabel(key, col) {
      const m = editTaskData.value?.param_meta?.[key];
      if (m && m.column_labels && m.column_labels[col]) return m.column_labels[col];
      return PARAM_KEY_LABELS[col] || col;
    }

    function getTableEnumOptions(key, col) {
      return paramEnumOptions[key + '.' + col] || [];
    }

    function _syncTableRowsToParams(key) {
      const rows = tableRowsCache[key];
      if (!rows || !editTaskData.value?.params) return;
      const dict = {};
      for (const row of rows) {
        const { _rowKey, ...rest } = row;
        dict[_rowKey] = rest;
      }
      editTaskData.value.params[key] = dict;
    }

    function saveTask() {
      if (!(editTaskParent.value && editTaskKey.value)) return;
      const meta = editTaskData.value?.param_meta || {};
      for (const [pk, mp] of Object.entries(meta)) {
        if (mp && typeof mp === 'object' && mp.type === 'table') {
          _syncTableRowsToParams(pk);
        }
      }
      const payload = { ...editTaskData.value };
      _filterParamsToRegisteredKeys(payload);
      if (payload.params && typeof payload.params === 'object') {
        delete payload.params.profession;
      }
      if (payload.param_meta && typeof payload.param_meta === 'object') {
        delete payload.param_meta.profession;
      }
      editTaskParent.value[editTaskKey.value] = {
        ...editTaskParent.value[editTaskKey.value],
        ...payload,
      };
      if (editTaskParent.value[editTaskKey.value].on) {
        editTaskParent.value[editTaskKey.value].next_exec_time = 0;
      }
      API.postRaw('/tasks', { tasks: configData.tasks }).then(async res => {
        const data = await res.json();
        if (res.ok && data) {
          Object.keys(configData).forEach(k => delete configData[k]);
          Object.assign(configData, data);
          ElementPlus.ElMessage.success('任务已保存');
        } else { ElementPlus.ElMessage.error('保存失败'); }
      }).catch(e => ElementPlus.ElMessage.error('保存失败: ' + e))
        .finally(() => { editModalVisible.value = false; });
    }

    function addListItem(key) {
      if (!Array.isArray(editTaskData.value.params[key])) editTaskData.value.params[key] = [];
      editTaskData.value.params[key].push('');
    }
    function removeListItem(key, idx) {
      if (Array.isArray(editTaskData.value.params[key])) editTaskData.value.params[key].splice(idx, 1);
    }

    async function saveTasks() {
      try {
        const res = await API.postRaw('/tasks', { tasks: configData.tasks });
        const data = await res.json();
        if (res.ok && data) {
          Object.keys(configData).forEach(k => delete configData[k]);
          Object.assign(configData, data);
          ElementPlus.ElMessage.success('任务已保存');
        } else { ElementPlus.ElMessage.error('保存失败: ' + ((data && data.error) || '未知错误')); }
      } catch (e) { ElementPlus.ElMessage.error('保存失败: ' + e); }
    }

    async function saveSettings() {
      try {
        await loadTheme();
        await API.postRaw('/config', configData);
        ElementPlus.ElMessage.success('保存成功');
      } catch (e) {
        ElementPlus.ElMessage.error('保存失败: ' + e);
      }
    }

    function clearLogs() {
      logs.value.length = 0;
      for (const id of ['logContainer', 'logContainerOverview', 'logContainerScheduler']) {
        const lc = document.getElementById(id);
        if (lc) lc.scrollTop = 0;
      }
    }

    async function submitAddAccount() {
      try {
        const payload = { ...addForm };

        const res1 = await API.postRaw('/account', payload);
        const data1 = await res1.json();

        if (data1.need_current_key) {
          try {
            const { value: curKey } = await ElementPlus.ElMessageBox.prompt(
              '修改账密需要验证当前安全密码', '安全验证',
              { inputType: 'password', confirmButtonText: '验证', cancelButtonText: '取消' });
            payload.current_security_key = curKey;
          } catch { return; }
          const res1b = await API.postRaw('/account', payload);
          const data1b = await res1b.json();
          if (!res1b.ok) {
            ElementPlus.ElMessage.error(data1b.error || '验证失败');
            return;
          }
          if (data1b.need_confirm) {
            try {
              await ElementPlus.ElMessageBox.confirm(data1b.message, '确认覆盖', {
                confirmButtonText: '继续', cancelButtonText: '取消', type: 'warning' });
            } catch { return; }
            payload.confirmed = true;
            const res2 = await API.postRaw('/account', payload);
            const data2 = await res2.json();
            if (!res2.ok) { ElementPlus.ElMessage.error(data2.error || '更新失败'); return; }
            characterName.value = data2.character_name || '';
          } else {
            characterName.value = data1b.character_name || '';
          }
        } else if (data1.need_confirm) {
          try {
            await ElementPlus.ElMessageBox.confirm(data1.message, '确认覆盖', {
              confirmButtonText: '继续', cancelButtonText: '取消', type: 'warning' });
          } catch { return; }
          payload.confirmed = true;
          const res2 = await API.postRaw('/account', payload);
          const data2 = await res2.json();
          if (!res2.ok) { ElementPlus.ElMessage.error(data2.error || '更新失败'); return; }
          characterName.value = data2.character_name || '';
        } else {
          if (!res1.ok) { ElementPlus.ElMessage.error(data1.error || '更新失败'); return; }
          characterName.value = data1.character_name || '';
        }

        if (!configData.game) configData.game = {};
        configData.game.character_name = characterName.value;
        addDialogVisible.value = false;
        ElementPlus.ElMessage.success('账号信息已更新');
      } catch (e) { ElementPlus.ElMessage.error('更新失败: ' + e); }
    }

    // ── 主题：始终浅色，不读取部署配置 ──
    function applyTheme() {
      currentTheme.value = 'light';
      document.documentElement.classList.add('light');
    }

    async function loadTheme() {
      applyTheme();
    }

    // ── 密码认证 ──
    async function checkAuth() {
      try {
        const res = await fetch('/api/refresh', { credentials: 'same-origin' });
        if (res.status === 401) {
          authRequired.value = true;
          return false;
        }
        authRequired.value = false;
        return true;
      } catch (e) { return true; }
    }

    async function submitLogin() {
      try {
        const res = await fetch('/api/auth', {
          method: 'POST',
          credentials: 'same-origin',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: loginPassword.value }),
        });
        if (res.ok) {
          authRequired.value = false;
          loginPassword.value = '';
          ElementPlus.ElMessage.success('登录成功');
          await refreshConfig(true);
          await fetchCredentialStatus();
          fetchOverview();
          setupWebSocket();
        } else {
          const data = await res.json().catch(() => ({}));
          if (res.status === 429) {
            ElementPlus.ElMessage.error(data.error || '登录尝试过多，请稍后再试');
          } else {
            ElementPlus.ElMessage.error(data.error || '密码错误');
          }
        }
      } catch (e) { ElementPlus.ElMessage.error('登录失败: ' + e); }
    }

    // ── 账号管理 ──
    async function fetchAccounts() {
      try {
        const data = await API.get('/accounts');
        accounts.value = data.accounts || [];
        currentAccount.value = data.current_account || '';
        if (data.active_character) Object.assign(activeCharacter, data.active_character);
        if (data.characters) {
          Object.keys(charactersTree).forEach(k => delete charactersTree[k]);
          Object.assign(charactersTree, data.characters);
        }
      } catch (e) { console.error('fetchAccounts', e); }
    }

    async function switchAccount(name, securityKeyDirect) {
      if (name === '__new__') return;
      try {
        let securityKey = securityKeyDirect;
        if (!securityKey) {
          const { value } = await ElementPlus.ElMessageBox.prompt(
            '请输入安全密码以切换账号', '切换账号',
            { inputType: 'password', confirmButtonText: '切换', cancelButtonText: '取消' });
          securityKey = value;
        }
        if (!securityKey) return;
        const res = await API.postRaw('/accounts/switch', { name, security_key: securityKey });
        const data = await res.json();
        if (res.ok) {
          currentAccount.value = name;
          characterName.value = data.character_name || '';
          if (data.active_character) Object.assign(activeCharacter, data.active_character);
          if (data.characters) {
            Object.keys(charactersTree).forEach(k => delete charactersTree[k]);
            Object.assign(charactersTree, data.characters);
          }
          ElementPlus.ElMessage.success('已切换到账号: ' + name);
          await refreshConfig(true);
          await fetchCredentialStatus();
          fetchAllTasksSummary();
          loadDispatchQueue();
          markOverviewSecurityUnlocked();
        } else {
          ElementPlus.ElMessage.error(data.error || '切换失败');
        }
      } catch { /* cancelled */ }
    }

    async function addAccount() {
      const name = (newAccountForm.name || '').trim();
      const account = (newAccountForm.account || '').trim();
      const password = (newAccountForm.password || '').trim();
      const server = (newAccountForm.server || '').trim();
      const character_name = (newAccountForm.character_name || '').trim();
      const security_key = (newAccountForm.security_key || '').trim();
      if (!name) { ElementPlus.ElMessage.warning('请输入账号名称'); return; }
      if (!account) { ElementPlus.ElMessage.warning('请输入游戏账号'); return; }
      if (!password) { ElementPlus.ElMessage.warning('请输入游戏密码'); return; }
      if (!server) { ElementPlus.ElMessage.warning('请输入服务器'); return; }
      if (!character_name) { ElementPlus.ElMessage.warning('请输入角色名'); return; }
      if (!security_key) { ElementPlus.ElMessage.warning('请输入安全密码'); return; }
      try {
        const res = await API.postRaw('/accounts/add', { name, account, password, server, character_name, security_key });
        const data = await res.json();
        if (res.ok) {
          accounts.value = data.accounts || [];
          accountDialogVisible.value = false;
          Object.assign(newAccountForm, { name: '', account: '', password: '', server: '', character_name: '', security_key: '' });
          ElementPlus.ElMessage.success('账号已创建');
        } else {
          ElementPlus.ElMessage.error(data.error || '创建失败');
        }
      } catch (e) { ElementPlus.ElMessage.error('创建失败: ' + e); }
    }

    async function deleteAccount(name) {
      try {
        await ElementPlus.ElMessageBox.confirm(
          `确定删除账号 "${name}" 吗？该账号下所有角色数据将被删除，此操作不可恢复。`, '删除账号',
          { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' });
        const res = await API.postRaw('/accounts/delete', { name });
        const data = await res.json();
        if (res.ok) {
          accounts.value = data.accounts || [];
          currentAccount.value = data.current_account || '';
          ElementPlus.ElMessage.success('账号已删除');
        } else {
          ElementPlus.ElMessage.error(data.error || '删除失败');
        }
      } catch { /* cancelled */ }
    }

    // ── 角色管理 ──
    async function switchCharacter(server, character) {
      try {
        const res = await API.postRaw('/characters/switch', { server, character });
        const data = await res.json();
        if (res.ok) {
          characterName.value = data.character_name || character;
          if (data.active_character) Object.assign(activeCharacter, data.active_character);
          ElementPlus.ElMessage.success('已切换到角色: ' + server + '/' + character);
          refreshConfig(true);
          fetchAllTasksSummary();
        } else {
          ElementPlus.ElMessage.error(data.error || '切换失败');
        }
      } catch (e) { ElementPlus.ElMessage.error('切换角色失败: ' + e); }
    }

    async function addCharacter() {
      if (!newCharacterForm.server) { ElementPlus.ElMessage.warning('请输入服务器名称'); return; }
      if (!newCharacterForm.character) { ElementPlus.ElMessage.warning('请输入角色名称'); return; }
      try {
        const res = await API.postRaw('/characters/add', { ...newCharacterForm });
        const data = await res.json();
        if (res.ok) {
          if (data.characters) {
            Object.keys(charactersTree).forEach(k => delete charactersTree[k]);
            Object.assign(charactersTree, data.characters);
          }
          characterDialogVisible.value = false;
          Object.assign(newCharacterForm, { server: '', character: '' });
          ElementPlus.ElMessage.success('角色已添加');
          await refreshConfig(true);
          fetchAccounts();
        } else {
          ElementPlus.ElMessage.error(data.error || '添加失败');
        }
      } catch (e) { ElementPlus.ElMessage.error('添加失败: ' + e); }
    }

    async function deleteCharacter(server, character) {
      try {
        await ElementPlus.ElMessageBox.confirm(
          `确定删除角色 "${server}/${character}" 吗？该角色的任务数据将被删除，此操作不可恢复。`, '删除角色',
          { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' });
        const res = await API.postRaw('/characters/delete', { server, character });
        const data = await res.json();
        if (res.ok) {
          if (data.characters) {
            Object.keys(charactersTree).forEach(k => delete charactersTree[k]);
            Object.assign(charactersTree, data.characters);
          }
          ElementPlus.ElMessage.success('角色已删除');
          await refreshConfig(true);
          fetchAccounts();
        } else {
          ElementPlus.ElMessage.error(data.error || '删除失败');
        }
      } catch { /* cancelled */ }
    }

    // ── 调度队列方法 ──
    /** 根据点击时 pending 快照与当前 summary，刷新调度总进度（单次 /run 内也会随任务完成递增） */
    function _syncDispatchProgressFromSummary() {
      if (!isDispatchRunning.value) return;
      const snap = _dispatchPendingSnap.value;
      const q = _dispatchQueueOrder.value;
      if (!snap || !q.length) return;
      const total = dispatchProgress.totalTaskCount || 0;
      if (!total) return;
      const currentKey = dispatchProgress.currentChar;
      if (!currentKey) return;
      const idx = q.findIndex(c => `${c.server}/${c.name}` === currentKey);
      if (idx < 0) return;
      let done = 0;
      for (let j = 0; j < idx; j++) {
        const k = `${q[j].server}/${q[j].name}`;
        done += Number(snap[k]) || 0;
      }
      const kCur = `${q[idx].server}/${q[idx].name}`;
      const initI = Number(snap[kCur]) || 0;
      const cur = _pendingTaskCountForChar(q[idx].server, q[idx].name);
      done += Math.max(0, initI - cur);
      dispatchProgress.completedTaskCount = Math.min(done, total);
    }

    async function fetchAllTasksSummary() {
      try {
        const data = await API.get('/characters/all_tasks_summary');
        if (data && data.characters) {
          Object.keys(allTasksSummary).forEach(k => delete allTasksSummary[k]);
          Object.assign(allTasksSummary, data.characters);
        }
        _syncDispatchProgressFromSummary();
      } catch (e) { console.error('fetchAllTasksSummary', e); }
    }

    async function loadDispatchQueue() {
      try {
        const data = await API.get('/dispatch/queue');
        dispatchQueue.value = data.queue || [];
      } catch (e) { console.error('loadDispatchQueue', e); }
    }

    async function saveDispatchQueue() {
      try {
        await API.post('/dispatch/queue', { queue: dispatchQueue.value });
      } catch (e) { console.error('saveDispatchQueue', e); }
    }

    function addToDispatch(server, name) {
      const exists = dispatchQueue.value.some(c => c.server === server && c.name === name);
      if (!exists) {
        dispatchQueue.value.push({ server, name });
        saveDispatchQueue();
      }
    }

    function removeFromDispatch(server, name) {
      dispatchQueue.value = dispatchQueue.value.filter(c => !(c.server === server && c.name === name));
      saveDispatchQueue();
    }

    function reorderDispatchQueue(fromIndex, toIndex) {
      const q = [...dispatchQueue.value];
      if (fromIndex < 0 || fromIndex >= q.length || toIndex < 0 || toIndex >= q.length) return;
      if (fromIndex === toIndex) return;
      const [item] = q.splice(fromIndex, 1);
      q.splice(toIndex, 0, item);
      dispatchQueue.value = q;
      saveDispatchQueue();
    }

    function _waitForTaskCompletion() {
      return new Promise((resolve) => {
        const CHECK_INTERVAL = 800;
        const check = async () => {
          if (_dispatchAbort.value) { resolve('aborted'); return; }
          try {
            await fetchAllTasksSummary();
            const st = await API.get('/run/status');
            if (st && !st.running) {
              resolve('done');
              return;
            }
          } catch (e) { /* ignore */ }
          setTimeout(check, CHECK_INTERVAL);
        };
        check();
      });
    }

    async function runAllDispatchTasks() {
      if (isDispatchRunning.value) return;
      if (!overviewSecurityUnlocked.value) {
        ElementPlus.ElMessage.warning('请先验证安全密码后再执行队列');
        return;
      }
      if (!dispatchQueue.value.length) {
        ElementPlus.ElMessage.info('调度队列为空');
        return;
      }
      if (directRunRunning.value) {
        ElementPlus.ElMessage.warning('单任务或上一段执行尚未结束，请先终止');
        return;
      }
      if (schedulerStatus.state === 'running') {
        ElementPlus.ElMessage.warning('调度器已在运行，请先停止调度再执行总览队列');
        return;
      }
      try {
        await API.post('/scheduler/deactivate', {});
        await fetchSchedulerStatus();
      } catch (e) { /* ignore */ }
      isDispatchRunning.value = true;
      _dispatchAbort.value = false;
      await fetchAllTasksSummary();
      const queue = [...dispatchQueue.value];
      const pendingSnap = new Map();
      let totalPendingAtClick = 0;
      for (const c of queue) {
        const p = _pendingTaskCountForChar(c.server, c.name);
        pendingSnap.set(`${c.server}/${c.name}`, p);
        totalPendingAtClick += p;
      }
      const pendingSnapObj = {};
      for (const c of queue) {
        const k = `${c.server}/${c.name}`;
        pendingSnapObj[k] = pendingSnap.get(k) || 0;
      }
      _dispatchPendingSnap.value = pendingSnapObj;
      _dispatchQueueOrder.value = queue.map(c => ({ server: c.server, name: c.name }));

      dispatchProgress.totalTaskCount = totalPendingAtClick;
      dispatchProgress.completedTaskCount = 0;

      for (let i = 0; i < queue.length; i++) {
        if (_dispatchAbort.value) break;
        const char = queue[i];
        const dispatchKey = `${char.server}/${char.name}`;
        const p0 = pendingSnap.get(dispatchKey) || 0;

        dispatchProgress.currentChar = dispatchKey;
        _syncDispatchProgressFromSummary();

        try {
          const switchRes = await API.postRaw('/characters/switch', { server: char.server, character: char.name });
          const switchData = await switchRes.json();
          if (!switchRes.ok) {
            ElementPlus.ElMessage.error('切换角色失败: ' + (switchData.error || char.name));
            continue;
          }
          characterName.value = switchData.character_name || char.name;
          if (switchData.active_character) Object.assign(activeCharacter, switchData.active_character);
          await refreshConfig(true);

          const tasks = collectDueLeafTaskPaths(configData.tasks || {});

          if (p0 > 0) {
            if (!tasks.length) {
              await fetchAllTasksSummary();
              continue;
            }

            try {
              await API.post('/scheduler/deactivate', {});
              await fetchSchedulerStatus();
            } catch (e) { /* ignore */ }

            const runRes = await API.postRaw('/run', {
              tasks,
              activate_scheduler: false,
              server: char.server,
              character: char.name,
            });
            const runData = await runRes.json().catch(() => ({}));
            if (runRes.status === 409) {
              ElementPlus.ElMessage.warning((runData && runData.message) || '执行冲突，已跳过该角色');
              await fetchRunStatus();
              continue;
            }
            if (!runRes.ok) {
              ElementPlus.ElMessage.error(runData.message || ('执行失败: ' + char.name));
              continue;
            }

            await _waitForTaskCompletion();
            if (_dispatchAbort.value) break;
            await fetchAllTasksSummary();
          } else {
            // 无黄点时仍启动调度器，使状态为「运行中」，到期任务会自动执行；
            // 与总览「开始运行」在无到期任务时的行为一致。
            const runRes = await API.postRaw('/run', {
              tasks: [],
              activate_scheduler: true,
              server: char.server,
              character: char.name,
            });
            const runData = await runRes.json().catch(() => ({}));
            if (runRes.status === 409) {
              ElementPlus.ElMessage.warning((runData && runData.message) || '启动调度冲突: ' + char.name);
              await fetchRunStatus();
              continue;
            }
            if (!runRes.ok) {
              ElementPlus.ElMessage.error(runData.message || ('启动调度失败: ' + char.name));
              continue;
            }
            fetchSchedulerStatus();
            fetchOverview();
            fetchRunStatus();
          }

          await fetchAllTasksSummary();

        } catch (e) {
          console.error('dispatch run error for', char.name, e);
          ElementPlus.ElMessage.error('执行角色任务失败: ' + char.name);
        }
      }

      isDispatchRunning.value = false;
      _resetDispatchProgress();
      if (!_dispatchAbort.value) {
        if (totalPendingAtClick > 0) {
          ElementPlus.ElMessage.success('所有角色任务执行完毕');
        } else {
          ElementPlus.ElMessage.success('调度已启动，到期任务将自动执行');
        }
      }
      await fetchAllTasksSummary();
      await fetchRunStatus();
    }

    function stopDispatch() {
      unifiedStop();
    }

    // ── init ──
    async function refreshOverviewPanel() {
      await refreshConfig(true);
      await fetchOverview();
      await fetchAllTasksSummary();
      await fetchSchedulerStatus();
    }

    watch(activeTab, (v) => {
      if (!FEATURE_SCRIPT_CANVAS && v === 'canvas') {
        activeTab.value = 'news';
        return;
      }
      const map = { daily: '每日任务', weekly: '每周任务', general: '', custom: '自定义任务' };
      window.__TASK_HELP_PREFIX__ = map[v] !== undefined ? map[v] : '';
    }, { immediate: true });

    async function init() {
      await loadTheme();
      const ok = await checkAuth();
      if (!ok) return;
      setupWebSocket();
      await refreshConfig(true);
      await fetchCredentialStatus();
      fetchOverview();
      fetchSchedulerStatus();
      fetchRunStatus();
      fetchAccounts();
      loadDispatchQueue();
      fetchAllTasksSummary();
      setInterval(() => { fetchOverview(); fetchSchedulerStatus(); }, 15000);
      setInterval(fetchRunStatus, 4000);
    }

    // ── Electron 窗口控制 ──
    const isElectron = !!window.electron;
    function minimizeToTray() {
      if (window.electron) window.electron.windowTray();
    }

    function goToEditorWithImage(url) {
      pendingEditorImportUrl.value = typeof url === 'string' ? url : '';
      activeTab.value = 'editor';
    }

    function onEditorImported() {
      pendingEditorImportUrl.value = '';
    }

    return {
      configData, activeTab, logs, characterName, filteredConfig, currentTasks,
      schedulerStatus, overviewData, activeGroupPath, pageTitle,
      editModalVisible, editTaskData, editTaskPath, paramEnumOptions, paramLabel,
      addDialogVisible, addForm,
      accounts, currentAccount, accountDialogVisible, newAccountForm,
      activeCharacter, charactersTree, characterDialogVisible, newCharacterForm,
      characterDisplayName, charactersList,
      gameProfessionsByCharacter, gameProfessionOptions, setGameProfession,
      dispatchQueue, allTasksSummary, isDispatchRunning, dispatchProgress,
      directRunRunning, executionBusy, fetchRunStatus,
      fetchAccounts, switchAccount, addAccount, deleteAccount,
      switchCharacter, addCharacter, deleteCharacter,
      addToDispatch, removeFromDispatch, reorderDispatchQueue, runAllDispatchTasks, stopDispatch, unifiedStop,
      overviewSecurityUnlocked, clearOverviewSecurityUnlocked,
      fetchAllTasksSummary, loadDispatchQueue, saveDispatchQueue,
      authRequired, loginPassword, submitLogin,
      currentTheme, applyTheme,
      setActiveGroup: path => { activeGroupPath.value = path; },
      refreshConfig, fetchOverview, fetchSchedulerStatus, refreshOverviewPanel,
      startRun, stopRun, runSingleTask, verifyAccount, resetScheduler,
      openEditModal, enumParamIsMultiple, saveTask, addListItem, removeListItem,
      isTableParam, getTableRows, getTableColumns, getTableColumnLabel, getTableEnumOptions, tableRowsCache,
      saveTasks, saveSettings, clearLogs,
      openAddAccountDialog: () => { addDialogVisible.value = true; },
      submitAddAccount,
      isElectron, minimizeToTray,
      pendingEditorImportUrl, goToEditorWithImage, onEditorImported,
      featureScriptCanvas: FEATURE_SCRIPT_CANVAS,
      init,
    };
  },
  mounted() { this.init(); },
});

app.component('task-tree', TaskTree);
app.use(ElementPlus);
app.mount('#app');
