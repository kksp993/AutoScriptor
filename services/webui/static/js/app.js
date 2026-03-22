const { createApp, ref, reactive, computed, nextTick } = Vue;

const app = createApp({
  components: { AppSidebar, OverviewPanel, SchedulerPanel, TaskPanel, SettingsPanel, EditorPanel },
  setup() {
    const configData = reactive({});
    const activeTab = ref('overview');
    const logs = ref([]);
    const characterName = ref('');
    const schedulerStatus = reactive({ state: 'pending', label: '待运行', color: 'green', consecutive_errors: 0 });
    const overviewData = reactive({
      scheduler: { state: 'pending', label: '待运行', color: 'green', consecutive_errors: 0, next_execution: null },
      stats: { total: 0, enabled: 0, pending: 0, completed: 0, disabled: 0 },
      upcoming: [],
      runtime: { initialized: false, has_mixctrl: false, has_mumu: false, has_bg: false, has_vlm: false },
    });

    const editModalVisible = ref(false);
    const editTaskData = ref({});
    const editTaskPath = ref('');
    const editTaskParent = ref(null);
    const editTaskKey = ref('');
    const activeGroupPath = ref('');
    const paramEnumOptions = reactive({});
    /** 任务参数字段名 -> 表单标签（其余键保持英文原名） */
    const PARAM_KEY_LABELS = {
      battle_loop:'战斗循环次数',
      battle_times: '战斗轮数',
      speed_x: '战斗加速',
      has_cd: '关卡有CD',
      battle_weight: '战斗配比',
      difficulty: '难度选择',
      preference: '关卡偏好',
      conquer_TianMo: '天魔挑战',
      method: '完成方式',
      Bingku_WuQi: '冰窟武器',
      Bingku_YiFu: '冰窟防具',
      Bingku_ChiBang: '冰窟翅膀',
      Changgui_WuQi: '常规武器',
      Changgui_YiFu: '常规防具',
      Changgui_ChiBang: '常规翅膀',
    };
    function paramLabel(key) {
      return PARAM_KEY_LABELS[key] || key;
    }
    const addDialogVisible = ref(false);
    const addForm = reactive({ account: '', password: '', character_name: '', security_key: '' });

    // ── 档案管理 ──
    const profiles = ref([]);
    const currentProfile = ref('default');
    const profileDialogVisible = ref(false);
    const newProfileForm = reactive({ name: '', account: '', password: '', character_name: '', security_key: '' });

    // ── 密码保护 ──
    const authRequired = ref(false);
    const loginPassword = ref('');

    // ── 主题（固定浅色） ──
    const currentTheme = ref('light');

    const filteredConfig = computed(() => {
      const clone = { ...configData };
      delete clone.tasks;
      delete clone.encryption;
      delete clone.status;
      return clone;
    });

    const activeTabLabel = computed(() => {
      return { daily: '每日任务', weekly: '每周任务', general: '一般任务', event: '活动任务' }[activeTab.value] || '';
    });

    const pageTitle = computed(() => {
      const map = {
        overview: '总览', scheduler: '调度', editor: '编辑器', settings: '设置',
        daily: '每日任务', weekly: '每周任务', general: '一般任务', event: '活动任务',
      };
      return map[activeTab.value] || '';
    });

    const currentTasks = computed(() => {
      const t = configData.tasks || {};
      if (activeTab.value === 'daily') return t['每日任务'] || {};
      if (activeTab.value === 'weekly') return t['每周任务'] || {};
      if (activeTab.value === 'general') return t['一般任务'] || {};
      if (activeTab.value === 'event') return t['活动任务'] || t['event_task'] || {};
      return {};
    });

    // ── API helpers ──
    const API = {
      async get(url) { return (await fetch('/api' + url)).json(); },
      async post(url, body) {
        return (await fetch('/api' + url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ...body, _timestamp: Date.now() / 1000 }),
        })).json();
      },
      async postRaw(url, body) {
        return fetch('/api' + url, {
          method: 'POST',
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
      let refreshScheduled = null;

      const scheduleRefresh = () => {
        if (refreshScheduled) return;
        refreshScheduled = setTimeout(() => { refreshScheduled = null; refreshConfig(true); }, 5000);
      };

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
        let needRefresh = false;
        for (const line of lines) {
          if (/(所有任务执行完成|任务执行已被中断)/.test(line)) needRefresh = true;
          buffer.push({ html: ansi_up.ansi_to_html(line) });
        }
        if (needRefresh) {
          scheduleRefresh();
          fetchOverview();
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
      if (!characterName.value) {
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
      // 总览/调度：无到期任务时仍应 activate 调度器，以便在下一计划时间自动执行
      if (!tasks.length && !isSchedulerView) {
        ElementPlus.ElMessage.info('暂无待执行的任务');
        return;
      }
      try {
        const res = await API.postRaw('/run', { tasks, activate_scheduler: true });
        const data = await res.json();
        if (res.status === 403) { ElementPlus.ElMessage.warning(data.message || '请先验证账号密码'); return; }
        fetchSchedulerStatus();
        fetchOverview();
        if (res.ok && isSchedulerView && !tasks.length) {
          ElementPlus.ElMessage.success('调度器已启动，到期任务将自动执行');
        }
      } catch (e) { console.error('Run error:', e); }
    }

    async function runSingleTask(taskPath) {
      if (!characterName.value) {
        ElementPlus.ElMessage.warning('请先验证账号密码后再执行任务');
        return;
      }
      const fullPath = (activeTabLabel.value ? activeTabLabel.value + '/' : '') + taskPath;
      try {
        const res = await API.postRaw('/run', { tasks: [fullPath], activate_scheduler: false });
        const data = await res.json();
        if (res.status === 403) { ElementPlus.ElMessage.warning(data.message || '请先验证账号密码'); return; }
        ElementPlus.ElMessage.success('已加入队列: ' + taskPath.split('/').pop());
        fetchSchedulerStatus();
        fetchOverview();
      } catch (e) { ElementPlus.ElMessage.error('执行失败: ' + e); }
    }

    function stopRun() {
      API.post('/stop', {}).catch(e => console.error('Stop error:', e));
    }

    async function verifyAccount() {
      try {
        const { value } = await ElementPlus.ElMessageBox.prompt(
          '请输入安全密码', '账号验证',
          { inputType: 'password', confirmButtonText: '验证', cancelButtonText: '取消' });
        const data = await API.post('/verify', { security_key: value });
        if (data) {
          characterName.value = data.character_name || '';
          if (!configData.game) configData.game = {};
          configData.game.character_name = characterName.value;
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
      editTaskParent.value[editTaskKey.value] = {
        ...editTaskParent.value[editTaskKey.value],
        ...editTaskData.value,
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
        const res = await fetch('/api/refresh');
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
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ password: loginPassword.value }),
        });
        if (res.ok) {
          authRequired.value = false;
          loginPassword.value = '';
          ElementPlus.ElMessage.success('登录成功');
          refreshConfig(true);
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

    // ── init ──
    async function init() {
      await loadTheme();
      const ok = await checkAuth();
      if (!ok) return;
      setupWebSocket();
      refreshConfig(true);
      fetchOverview();
      fetchSchedulerStatus();
      fetchProfiles();
      setInterval(() => { fetchOverview(); fetchSchedulerStatus(); }, 15000);
    }

    async function fetchProfiles() {
      try {
        const data = await API.get('/profiles');
        profiles.value = data.profiles || [];
        currentProfile.value = data.current || 'default';
      } catch (e) { console.error('fetchProfiles', e); }
    }

    async function switchProfile(name) {
      if (name === '__new__') return;
      try {
        const { value: securityKey } = await ElementPlus.ElMessageBox.prompt(
          '请输入安全密码以切换档案', '切换档案',
          { inputType: 'password', confirmButtonText: '切换', cancelButtonText: '取消' });
        if (!securityKey) return;
        const res = await API.postRaw('/profiles/switch', { name, security_key: securityKey });
        const data = await res.json();
        if (res.ok) {
          currentProfile.value = name;
          characterName.value = data.character_name || '';
          ElementPlus.ElMessage.success('已切换到档案: ' + name);
          refreshConfig(true);
        } else {
          ElementPlus.ElMessage.error(data.error || '切换失败');
        }
      } catch { /* 用户取消 */ }
    }

    async function addProfile() {
      if (!newProfileForm.name) { ElementPlus.ElMessage.warning('请输入档案名称'); return; }
      if (!newProfileForm.security_key) { ElementPlus.ElMessage.warning('安全密码不能为空'); return; }
      try {
        const res = await API.postRaw('/profiles/add', { ...newProfileForm });
        const data = await res.json();
        if (res.ok) {
          profiles.value = data.profiles || [];
          profileDialogVisible.value = false;
          Object.assign(newProfileForm, { name: '', account: '', password: '', character_name: '', security_key: '' });
          ElementPlus.ElMessage.success('档案已创建');
        } else {
          ElementPlus.ElMessage.error(data.error || '创建失败');
        }
      } catch (e) { ElementPlus.ElMessage.error('创建失败: ' + e); }
    }

    async function deleteProfile(name) {
      try {
        await ElementPlus.ElMessageBox.confirm(
          `确定删除档案 "${name}" 吗？此操作不可恢复。`, '删除档案',
          { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' });
        const res = await API.postRaw('/profiles/delete', { name });
        const data = await res.json();
        if (res.ok) {
          profiles.value = data.profiles || [];
          currentProfile.value = data.current || 'default';
          ElementPlus.ElMessage.success('档案已删除');
        } else {
          ElementPlus.ElMessage.error(data.error || '删除失败');
        }
      } catch { /* 用户取消 */ }
    }

    // ── Electron 窗口控制 ──
    const isElectron = !!window.electron;
    function minimizeToTray() {
      if (window.electron) window.electron.windowTray();
    }

    return {
      configData, activeTab, logs, characterName, filteredConfig, currentTasks,
      schedulerStatus, overviewData, activeGroupPath, pageTitle,
      editModalVisible, editTaskData, editTaskPath, paramEnumOptions, paramLabel,
      addDialogVisible, addForm,
      profiles, currentProfile, profileDialogVisible, newProfileForm,
      fetchProfiles, switchProfile, addProfile, deleteProfile,
      authRequired, loginPassword, submitLogin,
      currentTheme, applyTheme,
      setActiveGroup: path => { activeGroupPath.value = path; },
      refreshConfig, fetchOverview, fetchSchedulerStatus,
      startRun, stopRun, runSingleTask, verifyAccount, resetScheduler,
      openEditModal, enumParamIsMultiple, saveTask, addListItem, removeListItem,
      saveTasks, saveSettings, clearLogs,
      openAddAccountDialog: () => { addDialogVisible.value = true; },
      submitAddAccount,
      isElectron, minimizeToTray,
      init,
    };
  },
  mounted() { this.init(); },
});

app.component('task-tree', TaskTree);
app.use(ElementPlus);
app.mount('#app');
