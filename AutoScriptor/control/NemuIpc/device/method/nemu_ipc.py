import ctypes
import json
import os
import sys
import time
from functools import wraps
from threading import RLock

import cv2
import numpy as np

from AutoScriptor.control.NemuIpc.base.decorator import cached_property, del_cached_property, has_cached_property
from AutoScriptor.control.NemuIpc.base.utils import ensure_time, random_rectangle_point
from AutoScriptor.logging.logger import logger
from AutoScriptor.control.NemuIpc.device.method.utils import RETRY_TRIES, retry_sleep
from AutoScriptor.control.NemuIpc.device.method.pool import WORKER_POOL
from AutoScriptor.control.NemuIpc.config.deep import deep_get
from AutoScriptor.utils.app_config import cfg
from AutoScriptor.utils.mumu_discovery import resolve_mumu_layout

class RequestHumanTakeover(Exception):
    pass

def random_normal_distribution(a, b, n=5):
    output = np.mean(np.random.uniform(a, b, size=n))
    return output


def random_theta():
    theta = np.random.uniform(0, 2 * np.pi)
    return np.array([np.sin(theta), np.cos(theta)])


def random_rho(dis):
    return random_normal_distribution(-dis, dis)

def insert_swipe(p0, p3, speed=15, min_distance=10):
    """
    Insert way point from start to end.
    First generate a cubic bézier curve

    Args:
        p0: Start point.
        p3: End point.
        speed: Average move speed, pixels per 10ms.
        min_distance:

    Returns:
        list[list[int]]: List of points.

    Examples:
        > insert_swipe((400, 400), (600, 600), speed=20)
        [[400, 400], [406, 406], [416, 415], [429, 428], [444, 442], [462, 459], [481, 478], [504, 500], [527, 522],
        [545, 540], [560, 557], [573, 570], [584, 582], [592, 590], [597, 596], [600, 600]]
    """
    p0 = np.array(p0)
    p3 = np.array(p3)

    # Random control points in Bézier curve
    distance = np.linalg.norm(p3 - p0)
    p1 = 2 / 3 * p0 + 1 / 3 * p3 + random_theta() * random_rho(distance * 0.1)
    p2 = 1 / 3 * p0 + 2 / 3 * p3 + random_theta() * random_rho(distance * 0.1)

    # Random `t` on Bézier curve, sparse in the middle, dense at start and end
    segments = max(int(distance / speed) + 1, 5)
    lower = random_normal_distribution(-85, -60)
    upper = random_normal_distribution(80, 90)
    theta = np.arange(lower + 0., upper + 0.0001, (upper - lower) / segments)
    ts = np.sin(theta / 180 * np.pi)
    ts = np.sign(ts) * abs(ts) ** 0.9
    ts = (ts - min(ts)) / (max(ts) - min(ts))

    # Generate cubic Bézier curve
    points = []
    prev = (-100, -100)
    for t in ts:
        point = p0 * (1 - t) ** 3 + 3 * p1 * t * (1 - t) ** 2 + 3 * p2 * t ** 2 * (1 - t) + p3 * t ** 3
        point = point.astype(int).tolist()
        if np.linalg.norm(np.subtract(point, prev)) < min_distance:
            continue

        points.append(point)
        prev = point

    # Delete nearing points
    if len(points[1:]):
        distance = np.linalg.norm(np.subtract(points[1:], points[0]), axis=1)
        mask = np.append(True, distance > min_distance)
        points = np.array(points)[mask].tolist()
        if len(points) <= 1:
            points = [p0, p3]
    else:
        points = [p0, p3]

    return points

class NemuIpcIncompatible(Exception):
    pass


class NemuIpcError(Exception):
    pass


class NemuIpcFrameStale(NemuIpcError):
    """采集缓冲的尺寸已经过期，重采一次即可，不是故障。

    分辨率在两次采集之间变了（切横竖屏、换 App）时抛出：抛之前缓冲区已经丢
    掉，下一轮会重新探测分辨率并重建。日志按正常重采处理，不当作错误上报。
    """


class CaptureStd:
    """
    Capture stdout and stderr from both python and C library
    https://stackoverflow.com/questions/5081657/how-do-i-prevent-a-c-shared-library-to-print-on-stdout-in-python/17954769

    ```
    with CaptureStd() as capture:
        # String wasn't printed
        print('whatever')
    # But captured in ``capture.stdout``
    print(f'Got stdout: "{capture.stdout}"')
    print(f'Got stderr: "{capture.stderr}"')
    ```
    """

    def __init__(self):
        self.stdout = b''
        self.stderr = b''

    @staticmethod
    def _flush_stream(stream):
        try:
            stream.flush()
        except (AttributeError, OSError, ValueError):
            pass

    def _redirect_stdout(self, to):
        self._flush_stream(sys.stdout)
        os.dup2(to, self.fdout)

    def _redirect_stderr(self, to):
        self._flush_stream(sys.stderr)
        os.dup2(to, self.fderr)

    def __enter__(self):
        self.fdout = sys.stdout.fileno()
        self.fderr = sys.stderr.fileno()
        self.reader_out, self.writer_out = os.pipe()
        self.reader_err, self.writer_err = os.pipe()
        self.old_stdout = os.dup(self.fdout)
        self.old_stderr = os.dup(self.fderr)

        # Redirect the underlying file descriptors without closing/replacing
        # sys.stdout/sys.stderr. Logger handlers may hold those wrappers.
        self._redirect_stdout(to=self.writer_out)
        self._redirect_stderr(to=self.writer_err)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._flush_stream(sys.stdout)
        self._flush_stream(sys.stderr)
        self._redirect_stdout(to=self.old_stdout)
        self._redirect_stderr(to=self.old_stderr)
        os.close(self.old_stdout)
        os.close(self.old_stderr)
        os.close(self.writer_out)
        os.close(self.writer_err)

        self.stdout = self.recvall(self.reader_out)
        self.stderr = self.recvall(self.reader_err)
        os.close(self.reader_out)
        os.close(self.reader_err)

    @staticmethod
    def recvall(reader, length=1024) -> bytes:
        fragments = []
        while 1:
            chunk = os.read(reader, length)
            if chunk:
                fragments.append(chunk)
            else:
                break
        output = b''.join(fragments)
        return output


class CaptureNemuIpc(CaptureStd):
    instance = None

    def is_capturing(self):
        """
        Only capture at the topmost wrapper to avoid nested capturing
        If a capture is ongoing, this instance does nothing
        """
        cls = self.__class__
        return isinstance(cls.instance, cls) and cls.instance != self

    def __enter__(self):
        if self.is_capturing():
            return self

        super().__enter__()
        CaptureNemuIpc.instance = self
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_capturing():
            return

        CaptureNemuIpc.instance = None
        super().__exit__(exc_type, exc_val, exc_tb)

        self.check_stdout()
        self.check_stderr()

    def check_stdout(self):
        if not self.stdout:
            return
        logger.info(f'NemuIpc stdout: {self.stdout}')

    def check_stderr(self):
        if not self.stderr:
            return
        logger.error(f'NemuIpc stderr: {self.stderr}')

        # Calling an old MuMu12 player
        # Tested on 3.4.0
        # b'nemu_capture_display rpc error: 1783\r\n'
        # Tested on 3.7.3
        # b'nemu_capture_display rpc error: 1745\r\n'
        if b'error: 1783' in self.stderr or b'error: 1745' in self.stderr:
            raise NemuIpcIncompatible(
                f'NemuIpc requires MuMu12 version >= 3.8.13, please check your version')
        # contact_id incorrect
        # b'nemu_capture_display cannot find rpc connection\r\n'
        if b'cannot find rpc connection' in self.stderr:
            raise NemuIpcError(self.stderr)
        # Emulator died
        # b'nemu_capture_display rpc error: 1722\r\n'
        # MuMuVMMSVC.exe died
        # b'nemu_capture_display rpc error: 1726\r\n'
        # No idea how to handle yet
        if b'error: 1722' in self.stderr or b'error: 1726' in self.stderr:
            raise NemuIpcError('Emulator instance is probably dead')


def retry(func):
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (NemuIpcImpl):
        """
        init = None
        for _ in range(RETRY_TRIES):
            # Extend timeout on retries
            if func.__name__ == 'screenshot':
                retry_delay = retry_sleep(_)
                if retry_delay > 0:
                    # For screenshot, use incremental timeout starting from base timeout
                    kwargs['timeout'] = 2.0 + retry_delay
            try:
                if callable(init):
                    time.sleep(retry_sleep(_))
                    init()
                return func(self, *args, **kwargs)
            # Expected control flow: the frame was captured at a stale size and
            # the buffer is already dropped, so just capture again.
            except NemuIpcFrameStale as e:
                logger.debug(f'NemuIpc recapture: {e}')
            # Can't handle
            # NemuIpcError
            except NemuIpcError as e:
                # Still retrying, so this is not a failure yet. Only running out
                # of retries is, and that is reported below.
                logger.warning(f'NemuIpc error, retrying: {e}')

                def init():
                    self.reconnect()
            # Unknown, probably a trucked image
            except Exception as e:
                logger.exception(e)

                def init():
                    pass

        logger.critical(f'Retry {func.__name__}() failed')
        raise RequestHumanTakeover

    return retry_wrapper


class NemuIpcImpl:
    def __init__(self, nemu_folder: str, instance_id: int, display_id: int = 0):
        """
        Args:
            nemu_folder: MuMu 安装路径（包含 ``nx_device`` / ``shell`` 的安装根，
                例如 E:/ProgramFiles/MuMuPlayer-12.0 或 C:/Program Files/Netease/MuMu）。
                也可以是子目录（nx_main 等），会自动上溯到安装根。
            instance_id: Emulator instance ID, starting from 0
            display_id: Always 0 if keep app alive was disabled
        """
        self.instance_id: int = instance_id
        self.display_id: int = display_id

        # 自适应解析布局：nx_device/<android系列> 的序号会随 MuMu 升级变化
        # （12.0 = MuMu 5.0/12，15.0 = MuMu 6.0，以后还会加），所以按目录通配
        # + 版本排序找库，不枚举版本号；顺序见 mumu_discovery.candidate_nemu_dll_paths。
        # nemu_connect 需要的是安装根，子目录配置会被 resolve_mumu_layout 上溯修正。
        resolved_layout = resolve_mumu_layout(nemu_folder)
        resolved_root = str(resolved_layout.get("root") or "").strip()
        self.nemu_folder: str = resolved_root or nemu_folder

        list_dll = [str(path) for path in resolved_layout.get("nemu_dll_candidates") or []]
        # 保底：无论解析结果如何，历史已知路径再按原样试一遍——解析期间文件可能
        # 正好在安装器替换的窗口里（is_file 判定失败但随后可加载）。
        for legacy_relative in (
            './shell/sdk/external_renderer_ipc.dll',
            './nx_device/15.0/shell/sdk/external_renderer_ipc.dll',
            './nx_device/12.0/shell/sdk/external_renderer_ipc.dll',
            './nx_main/sdk/external_renderer_ipc.dll',
        ):
            legacy_candidate = os.path.abspath(os.path.join(nemu_folder, legacy_relative))
            if legacy_candidate not in list_dll:
                list_dll.append(legacy_candidate)
        ipc_dll_loaded = ''
        for candidate in list_dll:
            if not os.path.exists(candidate):
                continue
            try:
                self.lib = ctypes.CDLL(candidate)
                ipc_dll_loaded = candidate
                break
            except OSError as e:
                logger.error(e)
                logger.error(f'ipc_dll={candidate} exists, but cannot be loaded')
                continue
        if not ipc_dll_loaded:
            raise NemuIpcIncompatible(
                f'NemuIpc requires MuMu12 version >= 3.8.13, please check your version. '
                f'Could not load external_renderer_ipc.dll from any of: {list_dll}')
        # success
        logger.info(
            f'NemuIpcImpl init, '
            f'nemu_folder={self.nemu_folder}, '
            f'ipc_dll={ipc_dll_loaded}, '
            f'instance_id={instance_id}, '
            f'display_id={display_id}'
        )
        self.connect_id: int = 0
        self.width = 0
        self.height = 0

        # Protects connect/disconnect/reconnect and the reused capture
        # buffer. Held by the *calling* thread only: ``_screenshot`` runs on a
        # worker thread and must never take it (RLock is thread-bound).
        self.io_lock = RLock()

        # Reused capture buffer; re-allocated only when the resolution
        # changes. Avoids the per-frame 3.7MB zero-filled allocation.
        self._pixels_buffer = None
        self._buffer_length = 0

    def connect(self, on_thread=True):
        with self.io_lock:
            if self.connect_id > 0:
                return

            if on_thread:
                connect_id = self.run_func(
                    self.lib.nemu_connect,
                    self.nemu_folder, self.instance_id
                )
            else:
                connect_id = self.lib.nemu_connect(self.nemu_folder, self.instance_id)
            if connect_id == 0:
                raise NemuIpcError(
                    'Connection failed, please check if nemu_folder is correct and emulator is running'
                )

            self.connect_id = connect_id
            # logger.info(f'NemuIpc connected: {self.connect_id}')

    def disconnect(self):
        with self.io_lock:
            if self.connect_id == 0:
                return

            self.run_func(
                self.lib.nemu_disconnect,
                self.connect_id
            )

            self.connect_id = 0

    def reconnect(self):
        with self.io_lock:
            self.disconnect()
            self.connect()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    @staticmethod
    def run_func(func, *args, on_thread=True, timeout=0.5):
        """
        Args:
            func: Sync function to call
            *args:
            on_thread: True to run func on a separated thread
            timeout:

        Raises:
            JobTimeout: If function call timeout
            NemuIpcIncompatible:
            NemuIpcError
        """
        if on_thread:
            # nemu_ipc may timeout sometimes, so we run it on a separated thread
            job = WORKER_POOL.start_thread_soon(func, *args)
            result = job.get_or_kill(timeout)
        else:
            result = func(*args)

        err = False
        if func.__name__ == '_screenshot':
            pass
        elif func.__name__ == 'nemu_connect':
            if result == 0:
                err = True
        else:
            if result > 0:
                err = True
        # Get to actual error message printed in std
        if err:
            logger.warning(f'Failed to call {func.__name__}, result={result}')
            with CaptureNemuIpc():
                func(*args)

        return result

    def get_resolution(self, on_thread=True):
        """
        Get emulator resolution, `self.width` and `self.height` will be set
        """
        if self.connect_id == 0:
            self.connect()

        width_ptr = ctypes.pointer(ctypes.c_int(0))
        height_ptr = ctypes.pointer(ctypes.c_int(0))
        nullptr = ctypes.POINTER(ctypes.c_int)()

        ret = self.run_func(
            self.lib.nemu_capture_display,
            self.connect_id, self.display_id, 0, width_ptr, height_ptr, nullptr,
            on_thread=on_thread
        )
        if ret > 0:
            raise NemuIpcError('nemu_capture_display failed during get_resolution()')
        self.width = width_ptr.contents.value
        self.height = height_ptr.contents.value

    def _screenshot(self):
        # Worker-thread body. The calling thread holds ``io_lock``; never take
        # the lock here, RLock is bound to the thread that acquired it.
        if self.connect_id == 0:
            self.connect(on_thread=False)
        if self.width <= 0 or self.height <= 0:
            self.get_resolution(on_thread=False)

        length = self.width * self.height * 4
        if self._pixels_buffer is None or self._buffer_length != length:
            self._pixels_buffer = (ctypes.c_ubyte * length)()
            self._buffer_length = length

        width_ptr = ctypes.pointer(ctypes.c_int(self.width))
        height_ptr = ctypes.pointer(ctypes.c_int(self.height))

        ret = self.lib.nemu_capture_display(
            self.connect_id, self.display_id, length, width_ptr, height_ptr, self._pixels_buffer,
        )
        if ret > 0:
            # The cached size/buffer may be stale; drop them so @retry
            # re-probes the resolution and rebuilds before retrying.
            self._drop_capture_buffer()
            raise NemuIpcError('nemu_capture_display failed during screenshot()')

        captured_width = width_ptr.contents.value
        captured_height = height_ptr.contents.value
        if (captured_width, captured_height) != (self.width, self.height):
            # Display resolution changed underneath us; do not trust the frame
            # just written at the cached shape. Rebuild on the next retry.
            self._drop_capture_buffer()
            raise NemuIpcFrameStale(
                f'display resolution changed to {captured_width}x{captured_height}'
            )

        # Return the reusable buffer itself (not an ndarray view) so the frame
        # crosses the worker job without a copy.
        return self._pixels_buffer

    def _drop_capture_buffer(self):
        """Discard the cached frame size and buffer so they rebuild on demand."""
        self.width = 0
        self.height = 0
        self._pixels_buffer = None
        self._buffer_length = 0

    @retry
    def screenshot(self, timeout=2.0):
        """
        Args:
            timeout: Timout in seconds to call nemu_ipc
                Will be dynamically extended by `@retry`

        Returns:
            np.ndarray: Image array in BGRA color space, bottom-up.
                The array is a view over the reused capture buffer; consume it
                before the next capture or copy the data you keep.
        """
        with self.io_lock:
            if self.connect_id == 0:
                self.connect()

            pixels_buffer = self.run_func(self._screenshot, timeout=timeout)

            image = np.ctypeslib.as_array(pixels_buffer).reshape((self.height, self.width, 4))
            return image

    def convert_xy(self, x, y):
        """
        Convert classic ADB coordinates to Nemu's
        `self.height` must be updated before calling this method

        Returns:
            int, int
        """
        x, y = int(x), int(y)
        x, y = self.height - y, x
        return x, y

    @retry
    def down(self, x, y):
        """
        Contact down, continuous contact down will be considered as swipe
        """
        if self.connect_id == 0:
            self.connect()
        if self.height == 0:
            self.get_resolution()

        # x, y = self.convert_xy(x, y)
        # print(x, y)
        ret = self.run_func(
            self.lib.nemu_input_event_touch_down,
            self.connect_id, self.display_id, x, y
        )
        if ret > 0:
            raise NemuIpcError('nemu_input_event_touch_down failed')

    @retry
    def up(self):
        """
        Contact up
        """
        if self.connect_id == 0:
            self.connect()

        ret = self.run_func(
            self.lib.nemu_input_event_touch_up,
            self.connect_id, self.display_id
        )
        if ret > 0:
            raise NemuIpcError('nemu_input_event_touch_up failed')

    @retry
    def finger_touch_down(self, finger_id, x, y):
        """
        Press (or move) one numbered finger.

        Args:
            finger_id: Finger number, range 1..10.
            x, y: Screen coordinates (MuMu logical coordinates).
        """
        if self.connect_id == 0:
            self.connect()
        ret = self.run_func(
            self.lib.nemu_input_event_finger_touch_down,
            self.connect_id, self.display_id, int(finger_id), int(x), int(y)
        )
        if ret > 0:
            raise NemuIpcError('nemu_input_event_finger_touch_down failed')

    @retry
    def finger_touch_up(self, finger_id):
        """
        Raise one numbered finger.

        Args:
            finger_id: Finger number, range 1..10.
        """
        if self.connect_id == 0:
            self.connect()
        ret = self.run_func(
            self.lib.nemu_input_event_finger_touch_up,
            self.connect_id, self.display_id, int(finger_id)
        )
        if ret > 0:
            raise NemuIpcError('nemu_input_event_finger_touch_up failed')

    def input_text(self, text: str):
        """Type UTF-8 text through the renderer IPC (no ADB round trip).

        Deliberately not wrapped in @retry: retrying a partially delivered
        text would duplicate input.
        """
        if self.connect_id == 0:
            self.connect()
        encoded = str(text).encode('utf-8')
        ret = self.run_func(
            self.lib.nemu_input_text,
            self.connect_id, len(encoded), encoded
        )
        if ret > 0:
            raise NemuIpcError('nemu_input_text failed')

    @staticmethod
    def serial_to_id(serial: str):
        """
        Predict instance ID from serial
        E.g.
            "127.0.0.1:16384" -> 0
            "127.0.0.1:16416" -> 1
            Port from 16414 to 16418 -> 1

        Returns:
            int: instance_id, or None if failed to predict
        """
        try:
            port = int(serial.split(':')[1])
        except (IndexError, ValueError):
            return None
        index, offset = divmod(port - 16384 + 16, 32)
        offset -= 16
        if 0 <= index < 32 and offset in [-2, -1, 0, 1, 2]:
            return index
        else:
            return None


class NemuIpc():
    # Fallback gesture lock for instances created without ``__init__`` (tests
    # build wrappers via ``__new__``); real instances always replace this with
    # a per-instance lock in ``__init__``.
    _ipc_lock = RLock()

    def __init__(self, serial: str = '127.0.0.1:16416'):
        self.serial = serial
        # Serialises compound gestures (a down..up sequence such as swipe or
        # long-click) so concurrent callers cannot interleave one gesture with
        # another. It intentionally no longer serialises against screenshots:
        # capture protection lives in ``NemuIpcImpl.io_lock`` (per instance),
        # and capture is proven to run concurrently with touch injection.
        self._ipc_lock = RLock()

    @cached_property
    def nemu_ipc(self) -> NemuIpcImpl:
        """
        Initialize a nemu ipc implementation
        """
        # Try existing settings first
        # if self.config.EmulatorInfo_path:
            # if 'MuMuPlayerGlobal' in self.config.EmulatorInfo_path:
            #     logger.info(f'nemu_ipc is not available on MuMuPlayerGlobal, {self.config.EmulatorInfo_path}')
            #     raise RequestHumanTakeover
            #  C:\Program Files\Netease\MuMu Player 12\shell\MuMuPlayer.exe
            # folder = os.path.abspath(os.path.join(self.config.EmulatorInfo_path, '../../'))
        folder = cfg["emulator"]["mumu_folder"]
        # folder = "D:/Program Files/Netease/MuMu"
        index = NemuIpcImpl.serial_to_id(self.serial)
        if index is not None:
            try:
                return NemuIpcImpl(
                    nemu_folder=folder,
                    instance_id=index,
                    display_id=0
                ).__enter__()
            except (NemuIpcIncompatible, NemuIpcError) as e:
                logger.error(e)
                logger.error('Emulator info incorrect')

        logger.error(
            f'Unable to initialize NemuIpc: '
            f'serial={self.serial}, '
            f'mumu_folder={folder}, '
            f'serial_to_id={index}. '
            f'请检查: 1) 模拟器是否已启动  '
            f'2) data/config.json 中 mumu_folder 路径是否正确  '
            f'3) adb_addr 是否与模拟器实例匹配'
        )
        raise NemuIpcError('NemuIpc initialization failed')

    def nemu_ipc_available(self) -> bool:
        if not self.is_mumu_family:
            return False
        if self.nemud_player_version == '':
            # >= 4.0 has no info in getprop
            # Try initializing nemu_ipc for final check
            pass
        else:
            # Having version, probably MuMu6 or MuMu12 version 3.x
            if self.nemud_app_keep_alive == '':
                # Empty property, probably MuMu6 or MuMu12 version < 3.5.6
                return False
        try:
            _ = self.nemu_ipc
        except RequestHumanTakeover:
            return False
        return True

    @staticmethod
    def check_mumu_app_keep_alive_400(file):
        """
        Check app_keep_alive from emulator config if version >= 4.0

        Args:
            file: E:/ProgramFiles/MuMuPlayer-12.0/vms/MuMuPlayer-12.0-1/config/customer_config.json

        Returns:
            bool: If success to read file
        """
        # with E:\ProgramFiles\MuMuPlayer-12.0\shell\MuMuPlayer.exe
        # config is E:\ProgramFiles\MuMuPlayer-12.0\vms\MuMuPlayer-12.0-1\config\customer_config.json
        try:
            with open(file, mode='r', encoding='utf-8') as f:
                s = f.read()
                data = json.loads(s)
        except FileNotFoundError:
            logger.warning(f'Failed to check check_mumu_app_keep_alive, file {file} not exists')
            return False
        value = deep_get(data, keys='customer.app_keptlive', default=None)
        logger.attr('customer.app_keptlive', value)
        if str(value).lower() == 'true':
            # https://mumu.163.com/help/20230802/35047_1102450.html
            logger.critical('Please turn off "Keep alive in the background" in the settings or MuMuPlayer')
            logger.critical('请在MuMu模拟器设置内关闭 "后台挂机时保活运行"')
            raise RequestHumanTakeover
        return True

    def check_mumu_app_keep_alive(self):
        if not self.is_mumu_over_version_400:
            return super().check_mumu_app_keep_alive()

        # Try existing settings first
        if self.config.EmulatorInfo_path:
            index = NemuIpcImpl.serial_to_id(self.serial)
            if index is not None:
                file = os.path.abspath(os.path.join(
                    self.config.EmulatorInfo_path, f'../../vms/MuMuPlayer-12.0-{index}/configs/customer_config.json'))
                if self.check_mumu_app_keep_alive_400(file):
                    return True

        # Search emulator instance
        if self.emulator_instance is None:
            logger.warning('Failed to check check_mumu_app_keep_alive as emulator_instance is None')
            return False
        name = self.emulator_instance.name
        file = self.emulator_instance.mumu_vms_config('customer_config.json')
        if self.check_mumu_app_keep_alive_400(file):
            return True

        return False

    def nemu_ipc_release(self):
        with self._ipc_lock:
            if has_cached_property(self, 'nemu_ipc'):
                self.nemu_ipc.disconnect()
            del_cached_property(self, 'nemu_ipc')
        logger.info('nemu_ipc released')

    def screenshot_nemu_ipc(self):
        impl = self.nemu_ipc
        with impl.io_lock:
            image = impl.screenshot()

            image = cv2.cvtColor(image, cv2.COLOR_BGRA2RGB)
            cv2.flip(image, 0, dst=image)
            return image

    def screenshot_region_nemu_ipc(self, box):
        """Capture and convert only one screen-space region.

        Args:
            box: ``(left, top, width, height)`` or a ``Box`` in the frame's
                screen coordinates (top-down, same convention as clicks).

        Returns:
            np.ndarray: RGB image of the region. The rest of the frame is
            neither colour-converted nor flipped, which keeps tight polling
            loops cheap (see the realtime detection loop it enables).
        """
        left, top, width, height = (int(value) for value in box)
        if width <= 0 or height <= 0:
            raise ValueError(f"screenshot_region_nemu_ipc 区域无效: {box!r}")

        impl = self.nemu_ipc
        with impl.io_lock:
            frame = impl.screenshot()
            frame_height, frame_width = frame.shape[0], frame.shape[1]
            if (
                left < 0 or top < 0
                or left + width > frame_width or top + height > frame_height
            ):
                raise ValueError(
                    f"screenshot_region_nemu_ipc 区域超出 {frame_width}x{frame_height} 帧: {box!r}"
                )
            # The raw buffer is bottom-up: screen rows [top, top+height) live
            # at raw rows [frame_height - top - height, frame_height - top).
            raw_top = frame_height - top - height
            region = frame[raw_top:raw_top + height, left:left + width]
            region = cv2.cvtColor(region, cv2.COLOR_BGRA2RGB)
            return cv2.flip(region, 0, dst=region)

    def click_nemu_ipc(self, x, y, press_s=None, tail_s=None):
        """Tap through the IPC.

        Args:
            press_s: Press duration in seconds. The default keeps the
                historical 0.010-0.020s jitter.
            tail_s: Pause after the release. The default keeps the historical
                ``0.050 - press``; pass ``0`` for a minimal-latency tap.
        """
        with self._ipc_lock:
            press = ensure_time((0.010, 0.020)) if press_s is None else max(0.0, float(press_s))
            tail = max(0.0, 0.050 - press) if tail_s is None else max(0.0, float(tail_s))
            self.nemu_ipc.down(x, y)
            time.sleep(press)
            self.nemu_ipc.up()
            time.sleep(tail)

    def long_click_nemu_ipc(self, x, y, duration=1.0):
        with self._ipc_lock:
            self.nemu_ipc.down(x, y)
            time.sleep(duration)
            self.nemu_ipc.up()
            time.sleep(0.050)

    def swipe_nemu_ipc(self, p1, p2, speed:float=0.1):
        with self._ipc_lock:
            # 生成插值滑动路径
            points = insert_swipe(p0=p1, p3=p2)

            for point in points:
                # 确保坐标为 Python int，避免 ctypes 转换错误
                x = int(point[0])
                y = int(point[1])
                self.nemu_ipc.down(x, y)
                time.sleep(0.010 / speed)

            # 结束触摸
            self.nemu_ipc.up()
            time.sleep(0.050 / speed)

    def swipe_precise_nemu_ipc(self, p1, p2, duration_s: float = 0.5):
        """按固定直线和时间表发送一次完整触摸手势。

        与 ``swipe_nemu_ipc`` 的拟人化轨迹不同，这里不生成随机控制点，
        而是让每个触摸更新点落在线段 ``p1 -> p2`` 上。Nemu IPC 没有
        单独的 move 接口，连续的 touch-down 事件就是移动事件。
        """
        if duration_s <= 0:
            raise ValueError("duration_s 必须大于 0")

        start_x, start_y = int(p1[0]), int(p1[1])
        end_x, end_y = int(p2[0]), int(p2[1])
        # 约每 10ms 一个触摸更新点；至少保留起点和终点两个事件。
        point_count = max(2, min(240, int(round(duration_s * 100)) + 1))
        interval_s = duration_s / (point_count - 1)

        with self._ipc_lock:
            gesture_started = False
            gesture_start_time = time.perf_counter()
            try:
                for point_index in range(point_count):
                    progress = point_index / (point_count - 1)
                    current_x = round(start_x + (end_x - start_x) * progress)
                    current_y = round(start_y + (end_y - start_y) * progress)
                    self.nemu_ipc.down(current_x, current_y)
                    gesture_started = True

                    target_time = gesture_start_time + point_index * interval_s
                    remaining_s = target_time - time.perf_counter()
                    if remaining_s > 0:
                        time.sleep(remaining_s)
            finally:
                if gesture_started:
                    self.nemu_ipc.up()
            time.sleep(0.050)

    def drag_nemu_ipc(self, p1, p2, point_random=(-10, -10, 10, 10), speed:float=0.2):
        with self._ipc_lock:
            p1 = np.array(p1) - random_rectangle_point(point_random)
            p2 = np.array(p2) - random_rectangle_point(point_random)
            points = insert_swipe(p0=p1, p3=p2, speed=20)

            for point in points:
                self.nemu_ipc.down(*point)
                time.sleep(0.010/speed)

            self.nemu_ipc.down(*p2)
            time.sleep(0.140/speed)
            self.nemu_ipc.down(*p2)
            time.sleep(0.140/speed)

            self.nemu_ipc.up()
            time.sleep(0.050/speed)

    def release_touch_nemu_ipc(self):
        with self._ipc_lock:
            if has_cached_property(self, 'nemu_ipc'):
                self.nemu_ipc.up()

    # ------------------------------------------------------- multi-finger API
    #
    # Numbered fingers (1..10) are the IPC's native multi-touch channel.
    # These calls are deliberately lock-free: a realtime loop must be able to
    # press/release its own finger between frame captures without waiting on
    # anything else. Callers own the integrity of their finger sequences and
    # should not mix numbered fingers with the legacy single-contact calls
    # (``click_nemu_ipc``/``long_click_nemu_ipc``), which share one contact.

    def finger_down_nemu_ipc(self, finger_id, x, y):
        """Press numbered finger ``finger_id`` (1..10) at (x, y)."""
        self.nemu_ipc.finger_touch_down(finger_id, x, y)

    def finger_move_nemu_ipc(self, finger_id, x, y):
        """Move an already-pressed finger; same event as a repeated down."""
        self.nemu_ipc.finger_touch_down(finger_id, x, y)

    def finger_up_nemu_ipc(self, finger_id):
        """Raise numbered finger ``finger_id`` (1..10)."""
        self.nemu_ipc.finger_touch_up(finger_id)

    def release_all_fingers_nemu_ipc(self):
        """Best-effort release of fingers 1..10; never raises.

        Used as an exit guard (``finally``) so no finger stays pressed after
        an aborted realtime step. Not every numbered finger is necessarily
        down, so individual failures are expected and only logged at debug.
        """
        if not has_cached_property(self, 'nemu_ipc'):
            return
        for finger_id in range(1, 11):
            try:
                self.nemu_ipc.finger_touch_up(finger_id)
            except (NemuIpcError, RequestHumanTakeover) as error:
                logger.debug(f"释放 finger {finger_id} 失败（通常表示该指未按下）: {error}")

    def input_text_nemu_ipc(self, text):
        """Type text through the renderer IPC (no ADB round trip)."""
        self.nemu_ipc.input_text(text)
