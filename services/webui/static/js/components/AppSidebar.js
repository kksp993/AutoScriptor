const APP_MENU = [
  {
    group: 'CONTROL',
    items: [
      { id: 'overview',  label: '总览',   icon: 'fa-dashboard' },
      { id: 'scheduler', label: '调度',   icon: 'fa-clock-o' },
    ],
  },
  {
    group: 'TASKS',
    items: [
      { id: 'daily',   label: '每日任务', icon: 'fa-sun-o' },
      { id: 'weekly',  label: '每周任务', icon: 'fa-calendar' },
      { id: 'general', label: '一般任务', icon: 'fa-tasks' },
      { id: 'event',   label: '活动任务', icon: 'fa-star' },
    ],
  },
  {
    group: 'TOOLS',
    items: [
      { id: 'editor',   label: '编辑器', icon: 'fa-pencil-square-o' },
      { id: 'settings', label: '设置',   icon: 'fa-cog' },
    ],
  },
];

const AppSidebar = {
  name: 'AppSidebar',
  props: {
    activeTab:       { type: String,  required: true },
    schedulerStatus: { type: Object,  required: true },
    characterName:   { type: String,  default: '' },
  },
  emits: ['navigate'],
  data() { return { menu: APP_MENU }; },
  computed: {
    schedDot() {
      return {
        green:  '#22c55e',
        orange: '#f59e0b',
        red:    '#ef4444',
      }[this.schedulerStatus.color] || '#94a3b8';
    },
  },
  template: `
<aside class="sidebar flex flex-col">
  <!-- Logo -->
  <div class="sidebar-logo">
    <i class="fa fa-bolt text-primary text-2xl"></i>
    <span class="text-white font-bold text-xl tracking-wide ml-2">AutoScriptor</span>
  </div>

  <!-- Menu groups -->
  <nav class="flex-1 overflow-y-auto py-2">
    <template v-for="group in menu" :key="group.group">
      <div class="sidebar-group-label">{{ group.group }}</div>
      <a v-for="item in group.items" :key="item.id"
         :class="['sidebar-item', activeTab === item.id ? 'sidebar-item-active' : '']"
         @click="$emit('navigate', item.id)">
        <i :class="['fa', item.icon, 'sidebar-icon']"></i>
        <span>{{ item.label }}</span>
      </a>
    </template>
  </nav>

  <!-- 底部状态区 -->
  <div class="sidebar-footer">
    <div class="flex items-center gap-2 mb-2">
      <span class="sidebar-dot" :style="{ backgroundColor: schedDot }"></span>
      <span class="text-gray-300 truncate">{{ schedulerStatus.label || '未知' }}</span>
    </div>
    <div v-if="characterName" class="flex items-center gap-2">
      <i class="fa fa-user text-gray-400 w-4 text-center"></i>
      <span class="text-gray-400 truncate">{{ characterName }}</span>
    </div>
    <div v-else class="flex items-center gap-2">
      <i class="fa fa-lock text-gray-500 w-4 text-center"></i>
      <span class="text-gray-500">未验证</span>
    </div>
  </div>
</aside>`,
};
