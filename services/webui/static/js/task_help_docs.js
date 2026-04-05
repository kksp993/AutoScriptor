/**
 * 任务说明：TaskTree / Overview 依赖全局 getTaskHelpDoc、getTaskHelpParamRows。
 * 可变参数列使用 PARAM_KEY_LABELS；流程文案当前为空（不再由配置接口下发 task_docs）。
 */
(function () {
  const TASK_PATH_TOP_SEGMENTS = new Set([
    '每日任务', '每周任务', '一般任务', '活动任务', '自定义任务', 'event_task',
  ]);

  const PARAM_KEY_LABELS = {
    battle_flow: '战斗招式',
    battle_loop: '战斗循环次数',
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

  /**
   * @param {string} taskKey
   * @param {string} taskPath 可能是整树路径（总览）或当前 Tab 下相对路径（任务页）
   */
  function resolveTaskDocFullPath(taskKey, taskPath) {
    if (!taskPath) return '';
    const seg0 = taskPath.split('/')[0];
    if (TASK_PATH_TOP_SEGMENTS.has(seg0)) return taskPath;
    const p = typeof window.__TASK_HELP_PREFIX__ === 'string' ? window.__TASK_HELP_PREFIX__ : '';
    return p ? `${p}/${taskPath}` : taskPath;
  }

  window.getTaskHelpDoc = function getTaskHelpDoc(taskKey, taskPath) {
    const full = resolveTaskDocFullPath(taskKey, taskPath);
    const docs = window.__TASK_DOCS__;
    const entry = docs && typeof docs === 'object' ? docs[full] : null;
    if (entry && typeof entry === 'object') {
      return {
        flow: entry.flow != null ? String(entry.flow) : '',
        params: entry.params && typeof entry.params === 'object' ? entry.params : {},
      };
    }
    return { flow: '', params: {} };
  };

  window.getTaskHelpParamRows = function getTaskHelpParamRows(taskKey, taskPath, params) {
    if (!params || typeof params !== 'object') return [];
    const full = resolveTaskDocFullPath(taskKey, taskPath);
    const docs = window.__TASK_DOCS__;
    const entry = docs && typeof docs === 'object' ? docs[full] : null;
    const extra = entry && entry.params && typeof entry.params === 'object' ? entry.params : {};
    const rows = [];
    for (const key of Object.keys(params)) {
      if (key === 'param_meta' || key === 'profession') continue;
      const label = paramLabel(key);
      rows.push({
        key: label,
        desc: extra[key] != null && String(extra[key]).trim() ? String(extra[key]) : label,
        value: params[key],
      });
    }
    return rows;
  };
})();
