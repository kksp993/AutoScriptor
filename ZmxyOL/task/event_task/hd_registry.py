import functools

HD_TASK_TABLE = {}

def hd_task(identifier: str):
    def decorator(func):
        HD_TASK_TABLE[identifier] = func
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return func(*args, **kwargs)
        return wrapper
    return decorator

