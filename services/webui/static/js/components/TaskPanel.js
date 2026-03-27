const TaskPanel = {
  name: 'TaskPanel',
  props: {
    currentTasks: { type: Object, required: true },
    logs: { type: Array, required: true },
    characterName: { type: String, default: '' },
    schedulerStatus: { type: Object, required: true },
  },
  emits: [
    'edit-task', 'expanded-change', 'start-run', 'stop-run',
    'verify-account', 'open-add-account', 'save-tasks',
    'clear-logs', 'refresh-config', 'reset-scheduler', 'run-task',
  ],
  template: `
<div class="flex flex-col lg:flex-row gap-5 h-full min-h-0">
  <!-- 左侧：任务树 -->
  <div class="lg:w-1/3 bg-white rounded-xl shadow-md p-5 flex flex-col overflow-hidden min-h-0">
    <div class="flex justify-between items-center mb-4 flex-shrink-0">
      <h2 class="text-lg font-semibold text-dark">任务列表</h2>
      <button class="text-primary hover:text-primary/80 text-sm" @click="$emit('refresh-config')">
        <i class="fa fa-refresh mr-1"></i>刷新
      </button>
    </div>
    <div class="flex-1 overflow-y-auto pr-2 min-h-0">
      <task-tree :tree-data="currentTasks"
        @edit-task="(k,d,p,par)=>$emit('edit-task',k,d,p,par)"
        @expanded-change="v=>$emit('expanded-change',v)"
        @run-task="p=>$emit('run-task',p)">
      </task-tree>
    </div>
  </div>

  <!-- 右侧：日志 + 控制 -->
  <div class="lg:w-2/3 bg-white rounded-xl shadow-md p-5 flex flex-col overflow-hidden min-h-0">
    <div class="flex flex-col gap-4 flex-1 min-h-0">
      <div class="flex flex-wrap xl:flex-nowrap gap-2.5 items-center min-w-0">
        <button @click="$emit('start-run')" class="px-4 py-2.5 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium shrink-0">
          <i class="fa fa-play mr-1.5"></i>开始运行
        </button>
        <button class="px-4 py-2.5 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors text-sm font-medium shrink-0" @click="$emit('stop-run')">
          <i class="fa fa-stop mr-1.5"></i>终止执行
        </button>
        <button class="px-4 py-2.5 bg-secondary/20 text-dark rounded-lg hover:bg-secondary/30 transition-colors text-sm font-medium shrink-0" @click="$emit('verify-account')">
          <i class="fa fa-check mr-1.5"></i>账号验证
        </button>
        <button class="px-4 py-2.5 bg-secondary/20 text-dark rounded-lg hover:bg-secondary/30 transition-colors text-sm font-medium shrink-0" @click="$emit('open-add-account')">
          <i class="fa fa-plus mr-1.5"></i>添加账号
        </button>
        <button class="px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium shrink-0" @click="$emit('save-tasks')">
          <i class="fa fa-save mr-1.5"></i>保存任务
        </button>
        <span v-if="characterName" class="px-3 py-1.5 bg-secondary/10 text-secondary rounded text-sm shrink-0">角色ID：{{ characterName }}</span>
        <span class="px-3 py-1.5 rounded text-sm font-medium shrink-0"
              :style="{ backgroundColor: schedulerStatus.color==='green'?'#dcfce7':schedulerStatus.color==='orange'?'#fef3c7':schedulerStatus.color==='red'?'#fecaca':'#f1f5f9',
                        color: schedulerStatus.color==='green'?'#166534':schedulerStatus.color==='orange'?'#92400e':schedulerStatus.color==='red'?'#991b1b':'#475569' }">
          {{ schedulerStatus.color==='green'?'🟢':schedulerStatus.color==='orange'?'🟡':'🔴' }}
          调度: {{ schedulerStatus.label || '未知' }}
        </span>
        <button v-if="schedulerStatus.state==='error'"
                class="px-3 py-1.5 bg-red-100 text-red-700 rounded text-sm hover:bg-red-200 transition-colors font-medium shrink-0"
                @click="$emit('reset-scheduler')">
          <i class="fa fa-refresh mr-1"></i>恢复调度
        </button>
      </div>
      <div class="flex-1 flex flex-col min-h-0">
        <div class="flex items-center justify-between mb-3 flex-shrink-0">
          <h2 class="text-lg font-semibold text-dark"><i class="fa fa-terminal mr-2 text-primary text-lg"></i>运行日志</h2>
          <button class="text-gray-400 hover:text-gray-600 text-sm" @click="$emit('clear-logs')"><i class="fa fa-eraser mr-1"></i>清除</button>
        </div>
        <div class="log-container flex-1" id="logContainer">
          <div v-for="(log, i) in logs" :key="i" class="log-line" v-html="log.html"></div>
        </div>
      </div>
    </div>
  </div>
</div>`,
};
