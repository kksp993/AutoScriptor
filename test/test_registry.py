from AutoScriptor.utils.task_registry import task_registry

print("Registered tasks:", task_registry.all_paths())
for path, entry in task_registry.items():
    print(f"  {path}: order={entry['order']}")
