"""
稳定性测试入口
===============
运行方式:
    cd D:\\Projects\\AutoScriptor
    python -m test.test_stability

测试内容:
    - TaskManager: 单任务成功/失败/重试/取消/参数解析
    - Scheduler: 状态机/到期收集/认证检查/连续失败
    - TaskTree: 叶子判断/分支状态/路径查询/格式化
    - 集成: 调度器完整循环/失败不重复执行
"""

import sys
import os

# 确保项目根目录在 sys.path 中
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def main():
    from services.testing.runner import StabilityTestRunner
    runner = StabilityTestRunner()
    all_passed = runner.run_all()
    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()
