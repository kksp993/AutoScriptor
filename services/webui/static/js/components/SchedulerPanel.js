const SchedulerPanel = {
  name: 'SchedulerPanel',
  props: {
    overviewData: { type: Object, required: true },
    logs: { type: Array, required: true },
    characterName: { type: String, default: '' },
    schedulerStatus: { type: Object, required: true },
    executionBusy: { type: Boolean, default: false },
    activeCharacter: { type: Object, default: () => ({ server: '', name: '' }) },
    gameProfessionOptions: { type: Array, default: () => [] },
    gameProfessionsByCharacter: { type: Object, default: () => ({}) },
  },
  emits: ['start-run', 'stop-run', 'reset-scheduler', 'clear-logs', 'set-game-profession'],
  computed: {
    /** 当前调度状态的文字说明，告知用户该状态的含义 */
    schedStateHint() {
      const s = this.overviewData.scheduler;
      if (!s) return '';
      if (s.state === 'running') return '调度已激活：将自动监控并执行到期任务';
      if (s.state === 'error') return '调度已暂停：连续失败，请检查日志后点击「恢复调度」';
      return '调度未激活：到期任务不会自动执行，需点击「开始运行」';
    },
    /** 当前角色是否处于「调度模式运行中」状态 */
    isSchedulerRunning() {
      return this.overviewData.scheduler && this.overviewData.scheduler.state === 'running';
    },
  },
  methods: {
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
    taskShortName(path) {
      if (!path) return '';
      const parts = path.split('/');
      return parts[parts.length - 1];
    },
    schedColor(color) {
      return { green: '#22c55e', orange: '#f59e0b', red: '#ef4444' }[color] || '#94a3b8';
    },
    professionFor(server, name) {
      const srv = this.gameProfessionsByCharacter && this.gameProfessionsByCharacter[server];
      const v = srv && srv[name];
      return v || '悟空';
    },
  },
  template: `
<div class="flex flex-col lg:flex-row gap-5 h-full min-h-0">
  <!-- 左侧：调度控制 + 任务队列 -->
  <div class="lg:w-1/3 bg-white rounded-xl shadow-md p-5 flex flex-col overflow-hidden min-h-0">
    <h2 class="sched-section-heading mb-3"><i class="fa fa-clock-o sched-section-icon"></i>调度控制</h2>

    <!-- 状态 + 下次执行 -->
    <div class="bg-gray-50 rounded-lg p-4 mb-4">
      <div class="flex items-center gap-2 mb-1">
        <span class="w-3 h-3 rounded-full shrink-0" :style="{ backgroundColor: schedColor(overviewData.scheduler.color) }"></span>
        <span class="text-sm font-medium" :style="{ color: schedColor(overviewData.scheduler.color) }" :title="schedStateHint">{{ overviewData.scheduler.label || '未知' }}</span>
        <span v-if="characterName" class="ml-auto text-xs px-2.5 py-1 bg-green-50 text-green-700 rounded"><i class="fa fa-user mr-1"></i>{{ characterName }}</span>
        <span v-else class="ml-auto text-xs px-2.5 py-1 bg-red-50 text-red-600 rounded">未验证</span>
      </div>
      <div class="text-xs text-gray-400 mb-2" style="line-height:1.4">{{ schedStateHint }}</div>
      <div v-if="activeCharacter.server && activeCharacter.name && gameProfessionOptions.length" class="flex items-center gap-2 mb-3 px-1">
        <span class="text-xs text-gray-500 shrink-0">职业</span>
        <el-select
          size="small"
          class="flex-1 min-w-0"
          :model-value="professionFor(activeCharacter.server, activeCharacter.name)"
          placeholder="游戏职业"
          filterable
          @change="v => $emit('set-game-profession', activeCharacter.server, activeCharacter.name, v)"
        >
          <el-option v-for="p in gameProfessionOptions" :key="p" :label="p" :value="p"></el-option>
        </el-select>
      </div>
      <div class="text-xs text-gray-500 mt-1 text-center">下次执行（当前角色）</div>
      <div class="text-lg font-semibold text-dark mt-0.5 text-center">
        <template v-if="!isSchedulerRunning">-- --</template>
        <template v-else-if="overviewData.stats && overviewData.stats.pending > 0">即将执行</template>
        <template v-else>{{ overviewData.scheduler.next_execution ? formatTimestamp(overviewData.scheduler.next_execution) : '暂无计划' }}</template>
      </div>
      <div v-if="!isSchedulerRunning" class="text-xs text-gray-400 mt-1 text-center">调度未激活</div>
      <div v-else-if="overviewData.stats && overviewData.stats.pending > 0" class="text-xs text-gray-400 mt-1 text-center">有到期任务等待执行</div>
      <div v-else-if="overviewData.scheduler.next_execution" class="text-xs text-gray-400 mt-1 text-center">
        {{ formatCountdown(overviewData.scheduler.next_execution) }}
      </div>
    </div>

    <!-- 操作：主操作一行，双列网格，左右边与面板 padding 对齐 -->
    <div class="sched-control-actions mb-4">
      <div class="sched-control-row">
        <el-button type="primary" size="large" @click="$emit('start-run')" :disabled="!characterName || executionBusy"><i class="fa fa-play mr-1.5"></i>开始运行</el-button>
        <el-button type="danger" size="large" @click="$emit('stop-run')"><i class="fa fa-stop mr-1.5"></i>终止执行</el-button>
      </div>
      <el-button v-if="overviewData.scheduler.state==='error'" type="danger" size="large" @click="$emit('reset-scheduler')" class="sched-btn-full"><i class="fa fa-refresh mr-1.5"></i>恢复调度</el-button>
    </div>

    <div v-if="overviewData.scheduler.consecutive_errors > 0" class="mb-4 px-3.5 py-2.5 bg-red-50 text-red-700 rounded-lg text-sm">
      <i class="fa fa-warning mr-1"></i>连续失败 {{ overviewData.scheduler.consecutive_errors }} 次
      <span v-if="overviewData.scheduler.state==='error'">，调度已暂停</span>
    </div>

    <!-- 任务队列（节标题：小号，与表格正文区分） -->
    <h3 class="sched-section-heading mb-2 mt-1"><i class="fa fa-list-ol sched-section-icon"></i>任务队列</h3>
    <div class="flex-1 overflow-y-auto pr-1">
      <table class="w-full text-sm">
        <thead class="sticky top-0 bg-white">
          <tr class="text-left text-gray-400 border-b">
            <th class="pb-2 font-medium text-sm">任务</th>
            <th class="pb-2 font-medium text-sm text-center">状态</th>
            <th class="pb-2 font-medium text-sm text-right">时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(t, i) in overviewData.upcoming" :key="i" class="upcoming-row border-b border-gray-50">
            <td class="py-2 pr-1">
              <span class="text-dark text-sm">{{ taskShortName(t.path) }}</span>
            </td>
            <td class="py-2 text-center">
              <span v-if="t.status==='pending'" class="inline-block px-2 py-0.5 text-sm rounded-full bg-amber-100 text-amber-700">待执行</span>
              <span v-else class="inline-block px-2 py-0.5 text-sm rounded-full bg-green-100 text-green-700">待执行</span>
            </td>
            <td class="py-2 text-right text-gray-500 text-sm whitespace-nowrap">{{ t.next_exec_time > 0 ? formatTimestamp(t.next_exec_time) : '立即' }}</td>
          </tr>
          <tr v-if="!overviewData.upcoming.length"><td colspan="3" class="py-6 text-center text-gray-400 text-sm">暂无启用的任务</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <!-- 右侧：运行日志 -->
  <div class="lg:w-2/3 bg-white rounded-xl shadow-md p-5 flex flex-col overflow-hidden min-h-0">
    <div class="flex items-center justify-between mb-3">
      <h2 class="text-lg font-semibold text-dark"><i class="fa fa-terminal mr-2 text-primary text-lg"></i>运行日志</h2>
      <button class="text-gray-400 hover:text-gray-600 text-sm" @click="$emit('clear-logs')"><i class="fa fa-eraser mr-1"></i>清除</button>
    </div>
    <div class="log-container flex-1" id="logContainerScheduler">
      <div v-for="(log, i) in logs" :key="i" class="log-line" v-html="log.html"></div>
    </div>
  </div>
</div>`,
};
