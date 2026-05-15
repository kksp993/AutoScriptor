const { createApp, ref, reactive, computed, nextTick, watch } = Vue;

/** 临时关闭「脚本画布」侧边入口与主区面板；改为 true 可恢复 */
const FEATURE_SCRIPT_CANVAS = false;

const app = createApp({
  components: { AppSidebar, NewsPanel, OverviewPanel, SchedulerPanel, TaskPanel, SettingsPanel, EditorPanel, DiagnosticsPanel, CanvasPanel, ErrorArchivesPanel, UpdatePanel, AboutPanel },
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

    async function setGameProfession(server, character, game_profession) {
      if (!ensureIdle('执行中不能修改角色职业，请先终止当前任务')) return;
      try {
        const { ok, data: payload } = await API.request('POST', '/characters/game_profession', { server, character, game_profession });
        if (!ok) {
          showApiError(payload, '保存职业失败');
          return;
        }
        applyRuntimeSnapshotPayload(payload);
        ElementPlus.ElMessage.success('职业已保存');
      } catch (e) {
        ElementPlus.ElMessage.error('保存职业失败: ' + e);
      }
    }

    // ── 调度队列 ──
    const dispatchQueue = ref([]);
    const allTasksSummary = reactive({});
    const isDispatchRunning = computed(() => schedulerStatus.state === 'running');

    /** 后台 /api/run 直接执行线程是否存活（单任务、队列逐步执行） */
    const directRunRunning = ref(false);

    /** 总调度 / 调度模式 / 单任务互斥：任一路径占用即禁止其它入口 */
    const executionBusy = computed(() => {
      if (directRunRunning.value) return true;
      return schedulerStatus.state === 'running' || schedulerStatus.busy === true || schedulerStatus.executing === true;
    });

    // ── 密码保护 ──
    const authRequired = ref(false);
    const loginPassword = ref('');

    // 总览「安全密码」与角色名解耦：characterName 来自账号 JSON，刷新后即有，不代表已验证。
    // 是否已解锁以服务端 runtime snapshot 为准，禁止仅靠本地缓存「重放」绕过。
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
        diagnostics: '启动诊断', errorArchives: '错误汇总', updater: '检查更新', settings: '设置', about: '关于',
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
    const API = window.WebUIApi;

    function showApiError(data, fallback, level = 'error') {
      const text = API.errorMessage(data, fallback);
      ElementPlus.ElMessage({ type: level, message: text });
    }

    function ensureIdle(message = '执行中不能修改配置，请先终止当前任务') {
      if (!executionBusy.value) return true;
      ElementPlus.ElMessage.warning(message);
      return false;
    }

    const runtimeSnapshotState = {
      configData,
      accounts,
      currentAccount,
      activeCharacter,
      charactersTree,
      characterName,
      gameProfessionsByCharacter,
      gameProfessionOptions,
      dispatchQueue,
      allTasksSummary,
      overviewData,
      schedulerStatus,
      directRunRunning,
      overviewSecurityUnlocked,
    };

    function applyRuntimeSnapshotPayload(data) {
      return window.WebUIRuntimeStore.applySnapshot(runtimeSnapshotState, data);
    }

    async function refreshRuntimePanels() {
      await fetchRuntimeSnapshot({ refreshConfigIfChanged: true });
    }

    // ── data fetching ──
    let _lastRefreshAt = 0;
    const REFRESH_COOLDOWN = 10000;

    function applyPublicConfigPayload(data) {
      if (!data || data.error) return false;
      Object.keys(configData).forEach(k => delete configData[k]);
      Object.assign(configData, data);
      return applyRuntimeSnapshotPayload(data);
    }

    async function refreshConfig(force = false) {
      const now = Date.now();
      if (!force && now - _lastRefreshAt < REFRESH_COOLDOWN) return;
      try {
        const data = await API.get('/refresh');
        if (applyPublicConfigPayload(data)) {
          _lastRefreshAt = now;
        }
      } catch (e) { console.error('Refresh failed:', e); }
    }

    async function fetchRuntimeSnapshot({ refreshConfigIfChanged = true } = {}) {
      const publicVersion = Number(configData.config_version || 0);
      try {
        const data = await API.get('/runtime/snapshot');
        if (!applyRuntimeSnapshotPayload(data)) return false;
        const nextVersion = Number(data.config_version || 0);
        if (refreshConfigIfChanged && nextVersion && nextVersion !== publicVersion) {
          await refreshConfig(true);
        }
        return true;
      } catch (e) {
        console.error('runtime snapshot failed:', e);
        return false;
      }
    }

    async function reloadTasks() {
      if (!ensureIdle('执行中不能重载任务，请先终止当前任务')) return;
      try {
        const { ok, data } = await API.request('POST', '/tasks/reload', {});
        if (!ok) {
          showApiError(data, '重载任务失败');
          return;
        }
        applyPublicConfigPayload(data);
        ElementPlus.ElMessage.success('任务已重载');
      } catch (e) {
        ElementPlus.ElMessage.error('重载任务失败: ' + e);
      }
    }

    // ── WebSocket for logs (native WS, not Socket.IO) ──
    let ws = null;
    function setupWebSocket() {
      const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
      ws = new WebSocket(`${proto}//${location.host}/ws/logs`);
      const ansi_up = new AnsiUp();
      let buffer = [];
      let scheduled = false;
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
        for (const line of lines) {
          if (!shouldShowLogLine(line)) continue;
          buffer.push({ html: ansi_up.ansi_to_html(line) });
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
    async function handleRunStartResponse(result, fallbackMessage) {
      const data = result.data || {};
      if (result.status === 409) {
        showApiError(data, '执行冲突，请先终止当前任务', 'warning');
        await refreshRuntimePanels();
        return null;
      }
      if (result.status === 400) {
        showApiError(data, fallbackMessage || '启动失败');
        await refreshRuntimePanels();
        return null;
      }
      if (result.status === 403) {
        if (data && data.need_credential_unlock) overviewSecurityUnlocked.value = false;
        showApiError(data, '请先验证安全密码后再执行任务', 'warning');
        await refreshRuntimePanels();
        return null;
      }
      if (!result.ok) {
        showApiError(data, fallbackMessage || '启动失败');
        await refreshRuntimePanels();
        return null;
      }
      await refreshRuntimePanels();
      return data || {};
    }

    async function startSchedulerRun(successMessage = '调度器已启动，到期任务将自动执行') {
      if (!overviewSecurityUnlocked.value) {
        ElementPlus.ElMessage.warning('请先验证安全密码后再执行任务');
        return false;
      }
      if (!dispatchQueue.value.length) {
        ElementPlus.ElMessage.info('调度队列为空');
        return false;
      }
      if (executionBusy.value) {
        ElementPlus.ElMessage.warning('当前仍有任务在运行或停止中，请先终止或稍候再试');
        return false;
      }
      try {
        const result = await API.request('POST', '/run', { tasks: [], activate_scheduler: true });
        const data = await handleRunStartResponse(result, '启动调度失败');
        if (!data) return false;
        ElementPlus.ElMessage.success(successMessage);
        return true;
      } catch (e) {
        ElementPlus.ElMessage.error('启动调度失败: ' + e);
        return false;
      }
    }

    function schedulerViewActive() {
      return activeTab.value === 'overview' || activeTab.value === 'scheduler';
    }

    function ensureRunReady(message = '当前仍有任务在运行或停止中，请先终止或稍候再试') {
      if (!overviewSecurityUnlocked.value) {
        ElementPlus.ElMessage.warning('请先验证安全密码后再执行任务');
        return false;
      }
      if (!characterName.value && !activeCharacter.name) {
        ElementPlus.ElMessage.warning('请先验证账号密码后再执行任务');
        return false;
      }
      if (executionBusy.value) {
        ElementPlus.ElMessage.warning(message);
        return false;
      }
      return true;
    }

    function collectDueTasks() {
      const tasks = [];
      const base = (activeTabLabel.value ? activeTabLabel.value + '/' : '') +
                   (activeGroupPath.value ? activeGroupPath.value + '/' : '');
      let subtree = currentTasks.value;
      if (activeGroupPath.value) {
        for (const k of activeGroupPath.value.split('/').filter(Boolean)) {
          subtree = subtree && typeof subtree === 'object' ? subtree[k] : null;
        }
      }
      function traverse(data, path = '') {
        for (const [key, item] of Object.entries(data || {})) {
          if (item && Object.prototype.hasOwnProperty.call(item, 'on')) {
            if (item.on && item._due) tasks.push(base + path + key);
          } else if (item && typeof item === 'object') {
            traverse(item, path + key + '/');
          }
        }
      }
      traverse(subtree);
      return tasks;
    }

    async function startRun() {
      if (schedulerViewActive()) {
        await startSchedulerRun('调度器已启动，到期任务将自动执行');
        return;
      }
      if (!ensureRunReady()) return;
      const tasks = collectDueTasks();

      if (!tasks.length) {
        ElementPlus.ElMessage.info('暂无待执行的任务');
        return;
      }
      try {
        const result = await API.request('POST', '/run', {
          tasks,
          activate_scheduler: false,
          ...runCharacterPayload(),
        });
        const data = await handleRunStartResponse(result, '启动执行失败');
        if (data) ElementPlus.ElMessage.success('已开始执行当前任务列表');
      } catch (e) { ElementPlus.ElMessage.error('执行失败: ' + e); }
    }

    async function runSingleTask(taskPath) {
      if (!ensureRunReady('已有任务正在执行，请先终止后再跑单任务')) return;
      const fullPath = (activeTabLabel.value ? activeTabLabel.value + '/' : '') + taskPath;
      try {
        const result = await API.request('POST', '/run', { tasks: [fullPath], activate_scheduler: false, ...runCharacterPayload() });
        const data = await handleRunStartResponse(result, '执行失败');
        if (data) ElementPlus.ElMessage.success('已加入队列: ' + taskPath.split('/').pop());
      } catch (e) { ElementPlus.ElMessage.error('执行失败: ' + e); }
    }

    async function unifiedStop() {
      try {
        const { ok, data } = await API.request('POST', '/stop', {});
        if (!ok) showApiError(data, '终止失败');
      } catch (e) {
        console.error('Stop error:', e);
      }
      await refreshRuntimePanels();
    }

    function stopRun() {
      unifiedStop();
    }

    async function verifyAccount(securityKeyDirect) {
      if (!ensureIdle('执行中不能验证账号，请先终止当前任务')) return;
      try {
        let key = securityKeyDirect;
        if (!key) {
          const { value } = await ElementPlus.ElMessageBox.prompt(
            '请输入安全密码', '账号验证',
            { inputType: 'password', confirmButtonText: '验证', cancelButtonText: '取消' });
          key = value;
        }
        const { ok, data } = await API.request('POST', '/verify', { security_key: key });
        if (!ok) {
          showApiError(data, '验证失败，请检查安全密码');
          return;
        }
        await refreshConfig(true);
        await fetchRuntimeSnapshot({ refreshConfigIfChanged: false });
        markOverviewSecurityUnlocked();
      } catch (e) { /* cancelled */ }
    }

    async function resetScheduler() {
      if (!ensureIdle('执行中不能恢复调度，请先终止当前任务')) return;
      try {
        const { ok, data } = await API.request('POST', '/scheduler/reset', {});
        if (!ok) {
          showApiError(data, '恢复失败');
          await refreshRuntimePanels();
          return;
        }
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

    function openEditModal(key, data, path) {
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

    function _deepClone(value) {
      return JSON.parse(JSON.stringify(value || {}));
    }

    function _editTaskFullPath() {
      const path = editTaskPath.value || editTaskKey.value || '';
      const prefix = activeTabLabel.value || '';
      if (!prefix || path === prefix || path.startsWith(prefix + '/')) return path;
      return `${prefix}/${path}`;
    }

    function _taskSlotByPath(tasksRoot, path) {
      const parts = String(path || '').split('/').filter(Boolean);
      if (!parts.length) return null;
      let parent = tasksRoot;
      for (const part of parts.slice(0, -1)) {
        if (!parent || typeof parent !== 'object' || !parent[part] || typeof parent[part] !== 'object') {
          return null;
        }
        parent = parent[part];
      }
      return { parent, key: parts[parts.length - 1] };
    }

    async function persistTasks(tasks, successMessage = '任务已保存') {
      const { ok, data } = await API.request('POST', '/tasks', { tasks });
      if (!ok) {
        ElementPlus.ElMessage.error('保存失败: ' + API.errorMessage(data, '未知错误'));
        return false;
      }
      if (!applyPublicConfigPayload(data)) {
        ElementPlus.ElMessage.error('保存失败: 服务端返回配置不完整');
        return false;
      }
      ElementPlus.ElMessage.success(successMessage);
      fetchRuntimeSnapshot({ refreshConfigIfChanged: false });
      return true;
    }

    async function saveTask() {
      if (!editTaskKey.value) return;
      if (!ensureIdle('执行中不能修改任务配置，请先终止当前任务')) return;
      const meta = editTaskData.value?.param_meta || {};
      for (const [pk, mp] of Object.entries(meta)) {
        if (mp && typeof mp === 'object' && mp.type === 'table') {
          _syncTableRowsToParams(pk);
        }
      }
      const payload = _deepClone(editTaskData.value);
      _filterParamsToRegisteredKeys(payload);
      if (payload.params && typeof payload.params === 'object') {
        delete payload.params.profession;
      }
      if (payload.param_meta && typeof payload.param_meta === 'object') {
        delete payload.param_meta.profession;
      }
      const tasksDraft = _deepClone(configData.tasks || {});
      const slot = _taskSlotByPath(tasksDraft, _editTaskFullPath());
      if (!slot || !slot.parent[slot.key] || typeof slot.parent[slot.key] !== 'object') {
        ElementPlus.ElMessage.error('保存失败: 找不到任务路径 ' + _editTaskFullPath());
        return;
      }
      const previous = slot.parent[slot.key];
      const next = { ...previous, ...payload };
      if (next.on && !previous.on) {
        next.next_exec_time = 0;
        next._due = true;
      } else if (!next.on) {
        next._due = false;
      }
      slot.parent[slot.key] = next;
      try {
        const ok = await persistTasks(tasksDraft);
        if (ok) editModalVisible.value = false;
      } catch (e) {
        ElementPlus.ElMessage.error('保存失败: ' + e);
      }
    }

    function addListItem(key) {
      if (!Array.isArray(editTaskData.value.params[key])) editTaskData.value.params[key] = [];
      editTaskData.value.params[key].push('');
    }
    function removeListItem(key, idx) {
      if (Array.isArray(editTaskData.value.params[key])) editTaskData.value.params[key].splice(idx, 1);
    }

    async function saveTasks() {
      if (!ensureIdle('执行中不能保存任务配置，请先终止当前任务')) return;
      try {
        await persistTasks(configData.tasks || {});
      } catch (e) { ElementPlus.ElMessage.error('保存失败: ' + e); }
    }

    async function saveSettings() {
      if (!ensureIdle('执行中不能保存设置，请先终止当前任务')) return;
      try {
        applyTheme();
        const { ok, data } = await API.request('POST', '/config', configData);
        if (!ok) {
          ElementPlus.ElMessage.error('保存失败: ' + API.errorMessage(data, '未知错误'));
          return;
        }
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
      if (!ensureIdle('执行中不能修改账号密码，请先终止当前任务')) return;
      try {
        const payload = { ...addForm };
        let result = await API.request('POST', '/account', payload);
        let data = result.data || {};
        if (data.need_current_key) {
          let value;
          try {
            ({ value } = await ElementPlus.ElMessageBox.prompt(
              '修改账密需要验证当前安全密码', '安全验证',
              { inputType: 'password', confirmButtonText: '验证', cancelButtonText: '取消' }));
          } catch { return; }
          payload.current_security_key = value;
          result = await API.request('POST', '/account', payload);
          data = result.data || {};
        }
        if (data.need_confirm) {
          try {
            await ElementPlus.ElMessageBox.confirm(data.message, '确认覆盖', {
              confirmButtonText: '继续', cancelButtonText: '取消', type: 'warning' });
          } catch { return; }
          payload.confirmed = true;
          result = await API.request('POST', '/account', payload);
          data = result.data || {};
        }
        if (!result.ok) {
          showApiError(data, '更新失败');
          return;
        }
        addDialogVisible.value = false;
        await refreshConfig(true);
        await fetchRuntimeSnapshot({ refreshConfigIfChanged: false });
        markOverviewSecurityUnlocked();
        ElementPlus.ElMessage.success('账号信息已更新');
      } catch (e) { ElementPlus.ElMessage.error('更新失败: ' + e); }
    }

    // ── 主题：始终浅色，不读取部署配置 ──
    function applyTheme() {
      currentTheme.value = 'light';
      document.documentElement.classList.add('light');
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
          await fetchRuntimeSnapshot({ refreshConfigIfChanged: false });
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

    function openAccountDialog() {
      if (!ensureIdle('执行中不能新增账号，请先终止当前任务')) return;
      accountDialogVisible.value = true;
    }

    function openCharacterDialog() {
      if (!ensureIdle('执行中不能新增角色，请先终止当前任务')) return;
      characterDialogVisible.value = true;
    }

    function handleAccountCommand(command) {
      if (command === '__new__') {
        openAccountDialog();
        return;
      }
      switchAccount(command);
    }

    function requireFields(fields) {
      for (const [value, message] of fields) {
        if (!String(value || '').trim()) {
          ElementPlus.ElMessage.warning(message);
          return false;
        }
      }
      return true;
    }

    async function switchAccount(name, securityKeyDirect) {
      if (name === '__new__') return;
      if (!ensureIdle('执行中不能切换账号，请先终止当前任务')) return;
      try {
        let securityKey = securityKeyDirect;
        if (!securityKey) {
          const { value } = await ElementPlus.ElMessageBox.prompt(
            '请输入安全密码以切换账号', '切换账号',
            { inputType: 'password', confirmButtonText: '切换', cancelButtonText: '取消' });
          securityKey = value;
        }
        if (!securityKey) return;
        const { ok, data } = await API.request('POST', '/accounts/switch', { name, security_key: securityKey });
        if (ok) {
          ElementPlus.ElMessage.success('已切换到账号: ' + name);
          await refreshConfig(true);
          await fetchRuntimeSnapshot({ refreshConfigIfChanged: false });
          markOverviewSecurityUnlocked();
        } else {
          showApiError(data, '切换失败');
        }
      } catch { /* cancelled */ }
    }

    async function addAccount() {
      if (!ensureIdle('执行中不能新增账号，请先终止当前任务')) return;
      const name = (newAccountForm.name || '').trim();
      const account = (newAccountForm.account || '').trim();
      const password = (newAccountForm.password || '').trim();
      const server = (newAccountForm.server || '').trim();
      const character_name = (newAccountForm.character_name || '').trim();
      const security_key = (newAccountForm.security_key || '').trim();
      if (!requireFields([
        [name, '请输入账号名称'],
        [account, '请输入游戏账号'],
        [password, '请输入游戏密码'],
        [server, '请输入服务器'],
        [character_name, '请输入角色名'],
        [security_key, '请输入安全密码'],
      ])) return;
      try {
        const { ok, data } = await API.request('POST', '/accounts/add', { name, account, password, server, character_name, security_key });
        if (ok) {
          applyRuntimeSnapshotPayload(data);
          accountDialogVisible.value = false;
          Object.assign(newAccountForm, { name: '', account: '', password: '', server: '', character_name: '', security_key: '' });
          ElementPlus.ElMessage.success('账号已创建');
        } else {
          showApiError(data, '创建失败');
        }
      } catch (e) { ElementPlus.ElMessage.error('创建失败: ' + e); }
    }

    async function deleteAccount(name) {
      if (!ensureIdle('执行中不能删除账号，请先终止当前任务')) return;
      try {
        await ElementPlus.ElMessageBox.confirm(
          `确定删除账号 "${name}" 吗？该账号下所有角色数据将被删除，此操作不可恢复。`, '删除账号',
          { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' });
        const { ok, data } = await API.request('POST', '/accounts/delete', { name });
        if (ok) {
          applyRuntimeSnapshotPayload(data);
          ElementPlus.ElMessage.success('账号已删除');
        } else {
          showApiError(data, '删除失败');
        }
      } catch { /* cancelled */ }
    }

    // ── 角色管理 ──
    async function switchCharacter(server, character) {
      if (!ensureIdle('执行中不能切换角色，请先终止当前任务')) return;
      try {
        const { ok, data } = await API.request('POST', '/characters/switch', { server, character });
        if (ok) {
          ElementPlus.ElMessage.success('已切换到角色: ' + server + '/' + character);
          await refreshConfig(true);
          await fetchRuntimeSnapshot({ refreshConfigIfChanged: false });
        } else {
          showApiError(data, '切换失败');
        }
      } catch (e) { ElementPlus.ElMessage.error('切换角色失败: ' + e); }
    }

    async function addCharacter() {
      if (!ensureIdle('执行中不能新增角色，请先终止当前任务')) return;
      if (!requireFields([
        [newCharacterForm.server, '请输入服务器名称'],
        [newCharacterForm.character, '请输入角色名称'],
      ])) return;
      try {
        const { ok, data } = await API.request('POST', '/characters/add', { ...newCharacterForm });
        if (ok) {
          characterDialogVisible.value = false;
          Object.assign(newCharacterForm, { server: '', character: '' });
          ElementPlus.ElMessage.success('角色已添加');
          await refreshConfig(true);
          await fetchRuntimeSnapshot({ refreshConfigIfChanged: false });
        } else {
          showApiError(data, '添加失败');
        }
      } catch (e) { ElementPlus.ElMessage.error('添加失败: ' + e); }
    }

    async function deleteCharacter(server, character) {
      if (!ensureIdle('执行中不能删除角色，请先终止当前任务')) return;
      try {
        await ElementPlus.ElMessageBox.confirm(
          `确定删除角色 "${server}/${character}" 吗？该角色的任务数据将被删除，此操作不可恢复。`, '删除角色',
          { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' });
        const { ok, data } = await API.request('POST', '/characters/delete', { server, character });
        if (ok) {
          ElementPlus.ElMessage.success('角色已删除');
          await refreshConfig(true);
          await fetchRuntimeSnapshot({ refreshConfigIfChanged: false });
        } else {
          showApiError(data, '删除失败');
        }
      } catch { /* cancelled */ }
    }

    // ── 调度队列方法 ──
    async function persistDispatchQueue(nextQueue) {
      if (!ensureIdle('执行中不能修改调度队列，请先终止当前任务')) return false;
      try {
        const { ok, data } = await API.request('POST', '/dispatch/queue', { queue: nextQueue });
        if (!ok) {
          showApiError(data, '保存调度队列失败');
          await fetchRuntimeSnapshot({ refreshConfigIfChanged: false });
          return false;
        }
        applyRuntimeSnapshotPayload({ dispatch_queue: data.queue });
        return true;
      } catch (e) {
        ElementPlus.ElMessage.error('保存调度队列失败: ' + e);
        await fetchRuntimeSnapshot({ refreshConfigIfChanged: false });
        return false;
      }
    }

    async function addToDispatch(server, name) {
      if (!ensureIdle('执行中不能修改调度队列，请先终止当前任务')) return;
      const exists = dispatchQueue.value.some(c => c.server === server && c.name === name);
      if (!exists) {
        await persistDispatchQueue([...dispatchQueue.value, { server, name }]);
      }
    }

    async function removeFromDispatch(server, name) {
      if (!ensureIdle('执行中不能修改调度队列，请先终止当前任务')) return;
      const nextQueue = dispatchQueue.value.filter(c => !(c.server === server && c.name === name));
      await persistDispatchQueue(nextQueue);
    }

    async function reorderDispatchQueue(fromIndex, toIndex) {
      if (!ensureIdle('执行中不能调整调度队列，请先终止当前任务')) return;
      const q = [...dispatchQueue.value];
      if (fromIndex < 0 || fromIndex >= q.length || toIndex < 0 || toIndex >= q.length) return;
      if (fromIndex === toIndex) return;
      const [item] = q.splice(fromIndex, 1);
      q.splice(toIndex, 0, item);
      await persistDispatchQueue(q);
    }

    async function runAllDispatchTasks() {
      await startSchedulerRun('调度已启动，将按队列顺序自动执行到期任务');
    }

    function stopDispatch() {
      unifiedStop();
    }

    // ── init ──
    async function refreshOverviewPanel() {
      await refreshConfig(true);
      await fetchRuntimeSnapshot({ refreshConfigIfChanged: false });
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
      applyTheme();
      const ok = await checkAuth();
      if (!ok) return;
      setupWebSocket();
      await refreshConfig(true);
      await fetchRuntimeSnapshot({ refreshConfigIfChanged: false });
      setInterval(() => { fetchRuntimeSnapshot({ refreshConfigIfChanged: true }); }, 5000);
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
      dispatchQueue, allTasksSummary, isDispatchRunning,
      executionBusy,
      handleAccountCommand, switchAccount, addAccount, deleteAccount,
      openCharacterDialog, switchCharacter, addCharacter, deleteCharacter,
      addToDispatch, removeFromDispatch, reorderDispatchQueue, runAllDispatchTasks, stopDispatch, unifiedStop,
      overviewSecurityUnlocked, clearOverviewSecurityUnlocked,
      authRequired, loginPassword, submitLogin,
      currentTheme,
      setActiveGroup: path => { activeGroupPath.value = path; },
      refreshOverviewPanel,
      startRun, stopRun, runSingleTask, verifyAccount, resetScheduler,
      openEditModal, enumParamIsMultiple, saveTask, addListItem, removeListItem,
      isTableParam, getTableRows, getTableColumns, getTableColumnLabel, getTableEnumOptions, tableRowsCache,
      saveTasks, saveSettings, clearLogs, reloadTasks,
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
