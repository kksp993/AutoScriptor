from AutoScriptor.control.MumuAdaptor.device_facade import get_device_facade


def adb_base_args() -> list[str]:
    return get_device_facade().adb_base_args()


def run_adb(args: list[str], timeout: int = 10):
    return get_device_facade().run_adb(args, timeout=timeout)


def adb_device_ready() -> bool:
    return get_device_facade().adb_device_ready()


def configured_adb_host_port() -> tuple[str, str] | None:
    return get_device_facade().configured_adb_host_port()
