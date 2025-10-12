from AutoScriptor.utils.constant import cfg  # 引入全局配置实例
from ZmxyOL.task.pkg_utils import gather_py_files, sort_py_files, import_modules, sort_tasks, update_order_files, normalize_cfg_tasks_to_cn
from .task_register import register_task


all_py_files = gather_py_files()
sorted_files = sort_py_files(all_py_files)
import_modules(sorted_files)
normalize_cfg_tasks_to_cn()
sort_tasks(cfg['tasks'])
update_order_files(sorted_files)
cfg.save_config()
__all__ = [
    "register_task",
]
