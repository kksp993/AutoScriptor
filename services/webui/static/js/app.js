const { createApp, ref, reactive, computed, nextTick } = Vue;

const app = createApp({
  components: { AppSidebar, NewsPanel, OverviewPanel, SchedulerPanel, TaskPanel, SettingsPanel, EditorPanel, ErrorArchivesPanel, UpdatePanel, AboutPanel },
  setup() {
    const configData = reactive({});
    const activeTab = ref('news');
    const logs = ref([]);
    const characterName = ref('');
    const schedulerStatus = reactive({ state: 'pending', label: '待运行', color: 'green', consecutive_errors: 0 });
    const overviewData = reactive({
      scheduler: { state: 'pending', label: '待运行', color: 'green', consecutive_errors: 0, next_execution: null },
      stats: { total: 0, enabled: 0, pending: 0, completed: 0, disabled: 0 },
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

    // ── 调度队列 ──
    const dispatchQueue = ref([]);
    const allTasksSummary = reactive({});
    const isDispatchRunning = ref(false);
    const dispatchProgress = reactive({ current: 0, total: 0, currentChar: '' });
    const _dispatchAbort = ref(false);

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
      return clone;
    });

    /** 用于拼接任务路径前缀；一般任务页内同时含「一般任务」「活动任务」两棵顶层树，前缀由树路径自带，故 general 为空。 */
    const activeTabLabel = computed(() => {
      return { daily: '每日任务', weekly: '每周任务', general: '', custom: '自定义任务' }[activeTab.value] || '';
    });

    const pageTitle = computed(() => {
      const map = {
        news: '资讯', overview: '总览', scheduler: '调度', editor: '编辑器',
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

    const characterDisplayName = computed(() => {
      if (activeCharacter.server && activeCharacter.name) {
        return activeCharacter.server + ' / ' + activeCharacter.name;
      }
      return characterName.value || '';
    });

    const charactersList = computed(() => {
      const list = [];
      for (const [srv, chars] of Object.entries(charactersTree)) {
        const names = Array.isArray(chars) ? chars : Object.keys(chars);
        for (const charName of names) {
          list.push({ server: srv, name: charName, label: srv + ' / ' + charName });
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
      const now = Date.now() / 1000;
      const tasks = [];

      if (activeTab.value === 'overview' || activeTab.value === 'scheduler') {
        function traverseAll(data, path = '') {
          for (const [key, item] of Object.entries(data)) {
            if (!item || typeof item !== 'object') continue;
            if (item.hasOwnProperty('on')) {
              if (item.on && item.next_exec_time < now) tasks.push(path + key);
            } else { traverseAll(item, path + key + '/'); }
          }
        }
        traverseAll(configData.tasks || {});
      } else {
        const base = (activeTabLabel.value ? activeTabLabel.value + '/' : '') +
                     (activeGroupPath.value ? activeGroupPath.value + '/' : '');
        function traverse(data, path = '') {
          for (const [key, item] of Object.entries(data)) {
            if (item.hasOwnProperty('on')) {
              if (item.on && item.next_exec_time < now) tasks.push(base + path + key);
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
        if (res.status === 400) { ElementPlus.ElMessage.error(data.message || '角色切换失败'); return; }
        if (res.status === 403) {
          if (data && data.need_credential_unlock) await fetchCredentialStatus();
          ElementPlus.ElMessage.warning((data && data.message) || '请先验证安全密码后再执行任务');
          return;
        }
        fetchSchedulerStatus();
        fetchOverview();
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
      const fullPath = (activeTabLabel.value ? activeTabLabel.value + '/' : '') + taskPath;
      try {
        const res = await API.postRaw('/run', { tasks: [fullPath], activate_scheduler: false, ...runCharacterPayload() });
        const data = await res.json();
        if (res.status === 400) { ElementPlus.ElMessage.error(data.message || '角色切换失败'); return; }
        if (res.status === 403) {
          if (data && data.need_credential_unlock) await fetchCredentialStatus();
          ElementPlus.ElMessage.warning((data && data.message) || '请先验证安全密码后再执行任务');
          return;
        }
        ElementPlus.ElMessage.success('已加入队列: ' + taskPath.split('/').pop());
        fetchSchedulerStatus();
        fetchOverview();
      } catch (e) { ElementPlus.ElMessage.error('执行失败: ' + e); }
    }

    async function unifiedStop() {
      _dispatchAbort.value = true;
      isDispatchRunning.value = false;
      dispatchProgress.current = 0;
      dispatchProgress.total = 0;
      dispatchProgress.currentChar = '';
      try {
        await API.post('/stop', {});
      } catch (e) {
        console.error('Stop error:', e);
      }
      await fetchSchedulerStatus();
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

    function openEditModal(key, data, path, parent) {
      const cloned = JSON.parse(JSON.stringify(data));
      if (cloned.params && typeof cloned.params === 'object') {
        delete cloned.params.profession;
      }
      if (cloned.param_meta && typeof cloned.param_meta === 'object') {
        delete cloned.param_meta.profession;
      }
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
      const paths = Object.values(meta).map(_enumMetaPath).filter(Boolean);
      if (paths.length) {
        API.post('/enum-options', { paths }).then(map => {
          Object.entries(meta).forEach(([pk, ep]) => {
            const p = _enumMetaPath(ep);
            if (p) paramEnumOptions[pk] = map[p] || [];
          });
          editModalVisible.value = true;
        }).catch(() => { editModalVisible.value = true; });
      } else { editModalVisible.value = true; }
    }

    function saveTask() {
      if (!(editTaskParent.value && editTaskKey.value)) return;
      const payload = { ...editTaskData.value };
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
      if (!newAccountForm.name) { ElementPlus.ElMessage.warning('请输入账号名称'); return; }
      if (!newAccountForm.security_key) { ElementPlus.ElMessage.warning('安全密码不能为空'); return; }
      try {
        const res = await API.postRaw('/accounts/add', { ...newAccountForm });
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
          fetchAccounts();
        } else {
          ElementPlus.ElMessage.error(data.error || '删除失败');
        }
      } catch { /* cancelled */ }
    }

    // ── 调度队列方法 ──
    async function fetchAllTasksSummary() {
      try {
        const data = await API.get('/characters/all_tasks_summary');
        if (data && data.characters) {
          Object.keys(allTasksSummary).forEach(k => delete allTasksSummary[k]);
          Object.assign(allTasksSummary, data.characters);
        }
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
      isDispatchRunning.value = true;
      _dispatchAbort.value = false;
      const queue = [...dispatchQueue.value];
      dispatchProgress.total = queue.length;

      for (let i = 0; i < queue.length; i++) {
        if (_dispatchAbort.value) break;
        const char = queue[i];
        dispatchProgress.current = i + 1;
        dispatchProgress.currentChar = char.server + '/' + char.name;

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

          const now = Date.now() / 1000;
          const tasks = [];
          function traverseAll(data, path = '') {
            for (const [key, item] of Object.entries(data)) {
              if (!item || typeof item !== 'object') continue;
              if (item.hasOwnProperty('on')) {
                if (item.on && item.next_exec_time < now) tasks.push(path + key);
              } else { traverseAll(item, path + key + '/'); }
            }
          }
          traverseAll(configData.tasks || {});

          if (!tasks.length) {
            await fetchAllTasksSummary();
            continue;
          }

          const runRes = await API.postRaw('/run', {
            tasks,
            activate_scheduler: false,
            server: char.server,
            character: char.name,
          });
          const runData = await runRes.json().catch(() => ({}));
          if (!runRes.ok) {
            ElementPlus.ElMessage.error(runData.message || ('执行失败: ' + char.name));
            continue;
          }

          await _waitForTaskCompletion();
          await fetchAllTasksSummary();

        } catch (e) {
          console.error('dispatch run error for', char.name, e);
          ElementPlus.ElMessage.error('执行角色任务失败: ' + char.name);
        }
      }

      isDispatchRunning.value = false;
      dispatchProgress.current = 0;
      dispatchProgress.total = 0;
      dispatchProgress.currentChar = '';
      if (!_dispatchAbort.value) {
        ElementPlus.ElMessage.success('所有角色任务执行完毕');
      }
      await fetchAllTasksSummary();
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

    async function init() {
      await loadTheme();
      const ok = await checkAuth();
      if (!ok) return;
      setupWebSocket();
      await refreshConfig(true);
      await fetchCredentialStatus();
      fetchOverview();
      fetchSchedulerStatus();
      fetchAccounts();
      loadDispatchQueue();
      fetchAllTasksSummary();
      setInterval(() => { fetchOverview(); fetchSchedulerStatus(); }, 15000);
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
      dispatchQueue, allTasksSummary, isDispatchRunning, dispatchProgress,
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
      saveTasks, saveSettings, clearLogs,
      openAddAccountDialog: () => { addDialogVisible.value = true; },
      submitAddAccount,
      isElectron, minimizeToTray,
      pendingEditorImportUrl, goToEditorWithImage, onEditorImported,
      init,
    };
  },
  mounted() { this.init(); },
});

app.component('task-tree', TaskTree);
app.use(ElementPlus);
app.mount('#app');
