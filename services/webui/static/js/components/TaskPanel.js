const TaskPanel = {
  name: 'TaskPanel',
  props: {
    activeTab: { type: String, default: '' },
    currentTasks: { type: Object, required: true },
    logs: { type: Array, required: true },
    characterName: { type: String, default: '' },
    schedulerStatus: { type: Object, required: true },
    executionBusy: { type: Boolean, default: false },
  },
  emits: [
    'edit-task', 'expanded-change', 'start-run', 'stop-run',
    'save-tasks',
    'clear-logs', 'refresh-config', 'reset-scheduler', 'run-task',
  ],
  template: `
<div class="flex flex-col lg:flex-row gap-5 h-full min-h-0">
  <!-- 左侧：任务树 -->
  <div class="lg:w-1/3 min-w-0 bg-white rounded-xl shadow-md p-5 flex flex-col overflow-hidden min-h-0">
    <p v-if="activeTab==='custom'" class="task-panel-custom-warn mb-3 text-sm leading-relaxed">
      自定义任务目录中的 Python 与主程序同进程运行，可访问本机与自动化环境；来源不可信时代码存在安全风险，请仅放入自己编写的脚本，使用后果自负。
    </p>
    <div class="flex justify-between items-center mb-4 flex-shrink-0">
      <h2 class="text-lg font-semibold text-dark">任务列表</h2>
      <button class="text-primary hover:text-primary/80 text-sm disabled:opacity-50 disabled:pointer-events-none"
              @click="$emit('refresh-config')" :disabled="executionBusy">
        <i class="fa fa-refresh mr-1"></i>刷新
      </button>
    </div>
    <div class="task-panel-tasklist flex-1 min-h-0 min-w-0 overflow-y-auto overflow-x-hidden">
      <task-tree :tree-data="currentTasks" :run-task-disabled="executionBusy"
        @edit-task="(k,d,p)=>$emit('edit-task',k,d,p)"
        @expanded-change="v=>$emit('expanded-change',v)"
        @run-task="p=>$emit('run-task',p)">
      </task-tree>
    </div>
  </div>

  <!-- 右侧：日志 + 控制 -->
  <div class="lg:w-2/3 bg-white rounded-xl shadow-md p-5 flex flex-col overflow-hidden min-h-0">
    <div class="flex flex-col gap-4 flex-1 min-h-0">
      <div class="flex flex-wrap xl:flex-nowrap gap-2.5 items-center min-w-0">
        <button @click="$emit('start-run')" :disabled="executionBusy"
                class="px-4 py-2.5 bg-primary text-white rounded-lg hover:bg-primary/90 transition-colors text-sm font-medium shrink-0 disabled:opacity-50 disabled:pointer-events-none">
          <i class="fa fa-play mr-1.5"></i>开始运行
        </button>
        <button class="px-4 py-2.5 bg-red-500 text-white rounded-lg hover:bg-red-600 transition-colors text-sm font-medium shrink-0" @click="$emit('stop-run')">
          <i class="fa fa-stop mr-1.5"></i>终止执行
        </button>
        <button class="px-4 py-2.5 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition-colors text-sm font-medium shrink-0 disabled:opacity-50 disabled:pointer-events-none"
                @click="$emit('save-tasks')" :disabled="executionBusy">
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
                class="px-3 py-1.5 bg-red-100 text-red-700 rounded text-sm hover:bg-red-200 transition-colors font-medium shrink-0 disabled:opacity-50 disabled:pointer-events-none"
                :disabled="executionBusy"
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
