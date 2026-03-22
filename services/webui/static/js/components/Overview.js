const OverviewPanel = {
  name: 'OverviewPanel',
  props: {
    overviewData: { type: Object, required: true },
    characterName: { type: String, default: '' },
  },
  emits: ['verify-account'],
  methods: {
    schedColor(color) {
      return { green: '#22c55e', orange: '#f59e0b', red: '#ef4444' }[color] || '#94a3b8';
    },
  },
  template: `
<div class="space-y-6 overflow-y-auto h-full pb-2">
  <!-- 状态卡片 -->
  <div class="overview-grid">
    <div class="stat-card" style="border-left:4px solid" :style="{ borderColor: schedColor(overviewData.scheduler.color) }">
      <div class="flex items-center gap-2">
        <span class="sched-indicator" :style="{ backgroundColor: schedColor(overviewData.scheduler.color) }"></span>
        <span class="stat-value" :style="{ color: schedColor(overviewData.scheduler.color) }">{{ overviewData.scheduler.label || '未知' }}</span>
      </div>
      <span class="stat-label">调度器状态</span>
    </div>
    <div class="stat-card" style="border-left:4px solid #3b82f6">
      <span class="stat-value text-blue-500">{{ overviewData.stats.enabled }}</span>
      <span class="stat-label">启用任务</span>
    </div>
    <div class="stat-card" style="border-left:4px solid #f59e0b">
      <span class="stat-value text-amber-500">{{ overviewData.stats.pending }}</span>
      <span class="stat-label">待执行</span>
    </div>
    <div class="stat-card" style="border-left:4px solid #22c55e">
      <span class="stat-value text-green-500">{{ overviewData.stats.completed }}</span>
      <span class="stat-label">今日已完成</span>
    </div>
    <div class="stat-card" style="border-left:4px solid #8b5cf6">
      <span class="stat-value text-purple-500">{{ overviewData.stats.total }}</span>
      <span class="stat-label">任务总数</span>
    </div>
  </div>

  <!-- 登录卡片 -->
  <div class="flex justify-center">
    <div class="bg-white rounded-2xl shadow-lg p-8 w-full max-w-md text-center">
      <div v-if="characterName" class="space-y-4">
        <div class="w-20 h-20 rounded-full bg-gradient-to-br from-green-400 to-emerald-600 mx-auto flex items-center justify-center shadow-lg">
          <i class="fa fa-user text-white text-3xl"></i>
        </div>
        <div>
          <div class="text-2xl font-bold text-dark">{{ characterName }}</div>
          <div class="text-sm text-gray-400 mt-1">账号已验证</div>
        </div>
        <div class="inline-flex items-center gap-1.5 px-4 py-1.5 rounded-full bg-green-50 text-green-600 text-sm font-medium">
          <span class="w-2 h-2 rounded-full bg-green-500 animate-pulse"></span>在线
        </div>
      </div>

      <div v-else class="space-y-5">
        <div class="w-20 h-20 rounded-full bg-gradient-to-br from-gray-200 to-gray-300 mx-auto flex items-center justify-center">
          <i class="fa fa-lock text-gray-400 text-3xl"></i>
        </div>
        <div>
          <div class="text-xl font-semibold text-dark">账号未验证</div>
          <div class="text-sm text-gray-400 mt-1">请输入安全密码以解锁全部功能</div>
        </div>
        <el-button type="primary" size="large" round class="w-full" @click="$emit('verify-account')">
          <i class="fa fa-key mr-2"></i>立即验证
        </el-button>
      </div>
    </div>
  </div>
</div>`,
};
