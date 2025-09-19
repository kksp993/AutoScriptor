from AutoScriptor import *
import time

print("=== 测试后台监控和信号系统 ===")

# 测试1：检查后台监控是否启动
print(f"后台监控状态: running={bg.running}")
print(f"当前回调函数: {bg.get_idfs()}")

# 测试2：添加一个简单的监控
def test_callback():
    print("🎯 检测到'决斗场'！")
    bg.set_signal("try_exit", True)

bg.add(
    name="test_monitor",
    identifier=T("决斗场"),
    callback=test_callback,
)

print(f"添加监控后，回调函数: {bg.get_idfs()}")
print(f"后台监控状态: running={bg.running}")

# 测试3：等待信号
print("等待检测到'决斗场'...")
start_time = time.time()
while not bg.signal("try_exit", False):
    current_time = time.time()
    elapsed = current_time - start_time
    print(f"等待中... {elapsed:.1f}秒")
    time.sleep(1)
    
    # 超时保护
    if elapsed > 30:
        print("超时，退出测试")
        break

print("测试完成！")






