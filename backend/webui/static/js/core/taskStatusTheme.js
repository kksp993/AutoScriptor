(function (global) {
  const STATUS_THEME = {
    disabled: {
      label: '未启用',
      badgeClass: 'bg-gray-200 text-gray-600',
      nodeFill: '#f1f5f9',
      nodeStroke: '#94a3b8',
      textColor: '#475569',
    },
    pending: {
      label: '待执行',
      badgeClass: 'bg-yellow-200 text-yellow-700',
      nodeFill: '#fef3c7',
      nodeStroke: '#f59e0b',
      textColor: '#92400e',
    },
    scheduled: {
      label: '已完成',
      badgeClass: 'bg-green-200 text-green-700',
      nodeFill: '#dcfce7',
      nodeStroke: '#22c55e',
      textColor: '#166534',
    },
    error: {
      label: '错误',
      badgeClass: 'bg-red-200 text-red-700',
      nodeFill: '#fee2e2',
      nodeStroke: '#ef4444',
      textColor: '#991b1b',
    },
  };

  function getTaskStatus(taskItem) {
    if (!taskItem || !taskItem.on) return 'disabled';
    if (taskItem.error) return 'error';
    if ((taskItem.human_takeover || taskItem.human_takeover_error) && !taskItem._due) return 'error';
    return taskItem._due ? 'pending' : 'scheduled';
  }

  function getTaskTheme(taskItem) {
    return STATUS_THEME[getTaskStatus(taskItem)] || STATUS_THEME.disabled;
  }

  global.TaskStatusTheme = {
    STATUS_THEME,
    getTaskStatus,
    getTaskTheme,
  };
})(window);
