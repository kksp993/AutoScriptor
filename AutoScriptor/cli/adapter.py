"""Command catalogue and lazy adapters to the existing device/recognition APIs.

Importing this module never loads OCR, configuration or a device. The catalogue
is shared by parsing, help, execution and Python generation.
"""
from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
import inspect
import logging
import math
import shlex
import shutil
import threading


@dataclass(frozen=True)
class CommandSpec:
    function: str
    module: str = 'AutoScriptor'
    targets: str = 'none'
    arguments: tuple[str, ...] = ()
    options: tuple[str, ...] = ()
    frame_parameter: str = ''
    device: bool = True
    unsafe: bool = False
    description: str = ''


# option -> (Python keyword, value type, number of values). Boolean flags take no value.
OPTIONS = {
    '--timeout': ('timeout', 'float', 1), '--repeat': ('repeat', 'positive-int', 1),
    '--delay': ('delay', 'float', 1), '--interval': ('interval', 'float', 1),
    '--duration': ('duration_s', 'positive-float', 1), '--long-click': ('long_click_duration_s', 'float', 1),
    '--offset': ('offset', 'int', 2), '--resize': ('resize', 'positive-int', 2),
    '--if-exist': ('if_exist', 'true', 0), '--no-stable': ('assure_stable', 'false', 0),
    '--no-save-screenshot': ('save_screenshot', 'false', 0),
    '--no-wait-stable': ('ensure_stable_after_swipe', 'false', 0),
    '--full': ('is_simplify', 'false', 0), '--mode': ('mode', 'mode', 1),
    '--post-process': ('post_process', 'processor', 1),
    '--allow-empty': ('ensure_not_empty', 'false', 0), '--max-retries': ('max_retries', 'positive-int', 1),
    '--ocr-ttl': ('ocr_ttl', 'float', 1), '--box': ('box', 'int', 4),
    '--speed': ('speed', 'positive-float', 1), '--frame-size': ('frame_size', 'positive-int', 2),
    '--recording-size': ('recording_size', 'positive-int', 2), '--start-ms': ('start_ms', 'nonnegative-int', 1),
    '--end-ms': ('end_ms', 'nonnegative-int', 1),
    '--equals': ('color', 'str', 1),
}
_CLICK = ('--timeout', '--repeat', '--delay', '--interval', '--long-click', '--offset', '--resize', '--if-exist', '--no-stable', '--no-save-screenshot')
_SWIPE = ('--duration', '--delay', '--no-wait-stable')
_HERE = 'AutoScriptor.cli.adapter'
COMMANDS = {
    'click': CommandSpec('click', targets='one', options=_CLICK, description='Repeat until --until/--until-gone is satisfied; otherwise click once.'),
    'seq-click': CommandSpec('seq_click', targets='sequence', options=_CLICK, description='Ordered --next transitions; timeout is per step.'),
    'click-all': CommandSpec('click_all', targets='one', options=('--timeout', '--if-exist', '--delay', '--interval', '--offset', '--resize', '--no-stable', '--no-save-screenshot')),
    'locate': CommandSpec('locate', targets='many', options=('--timeout', '--no-stable', '--full'), frame_parameter='screenshot'),
    'match': CommandSpec('match', targets='many', options=('--timeout',), frame_parameter='screenshot'),
    'exists': CommandSpec('ui_T', targets='many', frame_parameter='screenshot'),
    'absent': CommandSpec('ui_F', targets='many', frame_parameter='screenshot'),
    'wait-appear': CommandSpec('wait_for_appear', targets='many', options=('--timeout',)),
    'wait-disappear': CommandSpec('wait_for_disappear', targets='many', options=('--timeout',)),
    'swipe': CommandSpec('swipe', targets='pair', options=_SWIPE),
    'swipe-precise': CommandSpec('swipe_precise', targets='pair', options=_SWIPE),
    'input': CommandSpec('input', targets='optional', arguments=('str',)),
    'key-event': CommandSpec('key_event', arguments=('nonnegative-int',)),
    'sleep': CommandSpec('sleep', arguments=('float',), device=False),
    'get-colors': CommandSpec('get_colors', targets='many', options=('--offset', '--resize')),
    'coloris': CommandSpec('coloris', targets='many', options=('--equals', '--timeout', '--offset', '--resize')),
    'extract-info': CommandSpec('extract_info', targets='many', options=('--mode', '--post-process', '--allow-empty', '--max-retries', '--ocr-ttl', '--no-save-screenshot'), frame_parameter='screenshot_frame'),
    'ocr': CommandSpec('ocr', _HERE, targets='optional', frame_parameter='screenshot_frame'),
    'screenshot': CommandSpec('screenshot', _HERE, arguments=('optional-str',), options=('--box',)),
    'finger-down': CommandSpec('finger_down', arguments=('finger', 'nonnegative-int', 'nonnegative-int')),
    'finger-move': CommandSpec('finger_move', arguments=('finger', 'nonnegative-int', 'nonnegative-int')),
    'finger-up': CommandSpec('finger_up', arguments=('finger',)),
    'multi-finger-down': CommandSpec('multi_finger_down', arguments=('json',)),
    'release-all': CommandSpec('release_all_fingers'),
    'replay': CommandSpec('replay', arguments=('json',), options=('--speed', '--frame-size', '--recording-size', '--start-ms', '--end-ms')),
    'app-launch': CommandSpec('launch_app', arguments=('str',)),
    'app-close': CommandSpec('close_app', arguments=('str',)),
    'app-home': CommandSpec('go_home'),
    'device-connect': CommandSpec('connect_device', _HERE),
    'device-status': CommandSpec('device_status', _HERE, device=False),
    'adb-shell': CommandSpec('adb_shell', _HERE, arguments=('remainder',), options=('--timeout',), unsafe=True),
    'adb-push': CommandSpec('adb_push', _HERE, arguments=('str', 'str'), options=('--timeout',), unsafe=True),
    'adb-pull': CommandSpec('adb_pull', _HERE, arguments=('str', 'str'), options=('--timeout',)),
    'adb-tap': CommandSpec('adb_tap', _HERE, arguments=('nonnegative-int', 'nonnegative-int')),
    'adb-swipe': CommandSpec('adb_swipe', _HERE, arguments=('nonnegative-int',) * 4, options=('--duration',)),
    'adb-input': CommandSpec('adb_input', _HERE, arguments=('str',)),
    'adb-keyevent': CommandSpec('adb_keyevent', _HERE, arguments=('nonnegative-int',)),
    'adb-logcat': CommandSpec('adb_logcat', _HERE, options=('--timeout',)),
    'record-capture': CommandSpec('record_capture', _HERE, arguments=('positive-float',), description='Record for this many seconds within the flow recording.'),
}
_OUTPUT_DIRECTORY: ContextVar[Path | None] = ContextVar('ascli_output_directory', default=None)


def capabilities() -> dict:
    return {
        name: {
            'function': f'{spec.module}.{spec.function}',
            'targets': spec.targets,
            'arguments': list(spec.arguments),
            'options': list(spec.options),
            'frame': bool(spec.frame_parameter),
            'unsafe': spec.unsafe,
            'description': spec.description,
        }
        for name, spec in COMMANDS.items()
    }


def _control():
    from AutoScriptor.core.runtime_context import runtime_ctx
    if not runtime_ctx.has_device_session():
        raise RuntimeError('No active device session; run through the backend or initialize explicitly')
    return runtime_ctx.mixctrl


def connect_device():
    from AutoScriptor.core.runtime_context import runtime_ctx
    runtime_ctx.ensure_device_session(reason='ascli', launch_app=False)
    return runtime_ctx.status_dict()


def device_status():
    from AutoScriptor.core.runtime_context import runtime_ctx
    return runtime_ctx.status_dict()


def _output_path(name: str) -> Path:
    from AutoScriptor.utils.paths import get_logs_root
    root = ((_OUTPUT_DIRECTORY.get() or get_logs_root() / 'ascli' / 'manual') / 'artifacts').resolve()
    candidate = (root / name).resolve()
    if candidate == root or root not in candidate.parents:
        raise ValueError('Artifact paths must stay inside the run directory')
    candidate.parent.mkdir(parents=True, exist_ok=True)
    return candidate


def screenshot(name: str = 'screenshot.png', *, box=None):
    """Save and return one original BGR frame (or a BGR crop)."""
    import cv2
    frame = _control().screenshot()
    if box is not None:
        left, top, width, height = box
        if left < 0 or top < 0 or width <= 0 or height <= 0 or left + width > frame.shape[1] or top + height > frame.shape[0]:
            raise ValueError('Screenshot region lies outside the original frame')
        frame = frame[top:top + height, left:left + width].copy()
    path = _output_path(name)
    if path.suffix.lower() not in ('.png', '.jpg', '.jpeg'):
        raise ValueError('Screenshot output must be PNG or JPEG')
    success, encoded = cv2.imencode(path.suffix, frame)
    if not success:
        raise RuntimeError('Screenshot encoding failed')
    path.write_bytes(encoded.tobytes())
    return frame


def ocr(target=None, *, screenshot_frame=None):
    from AutoScriptor.core.box import Box
    from AutoScriptor.recognition.ocr_rec import ocr_for_box
    frame = screenshot_frame if screenshot_frame is not None else _control().screenshot()
    return ocr_for_box(frame, target.box if target is not None else Box(0, 0, frame.shape[1], frame.shape[0]))


def _adb(arguments, timeout=30):
    from AutoScriptor.control.MumuAdaptor.api.adb.direct import run_adb
    from AutoScriptor.utils.cancel import check_cancel_raise
    check_cancel_raise()
    result = run_adb(list(arguments), timeout=timeout)
    check_cancel_raise()
    if result.returncode:
        raise RuntimeError(f'ADB exited {result.returncode}: {result.stderr or result.stdout}')
    return result.stdout


def adb_shell(*arguments, timeout=30):
    # Quote for Android's remote shell; never invoke a host shell.
    return _adb(['shell', shlex.join(arguments)], timeout)


def adb_push(source, destination, timeout=30):
    """Source is explicitly a backend-host path, not a client path."""
    source = Path(source).resolve(strict=True)
    if not source.is_file():
        raise ValueError('ADB push source must be a file on the backend host')
    return _adb(['push', str(source), destination], timeout)


def adb_pull(source, name, timeout=30):
    destination = _output_path(name)
    _adb(['pull', source, str(destination)], timeout)
    if not destination.is_file():
        raise RuntimeError('ADB pull did not produce the requested file')
    return str(destination)


def adb_tap(horizontal, vertical):
    return adb_shell('input', 'tap', str(horizontal), str(vertical))


def adb_swipe(start_x, start_y, end_x, end_y, *, duration_s=1):
    return adb_shell('input', 'swipe', str(start_x), str(start_y), str(end_x), str(end_y), str(round(duration_s * 1000)))


def adb_input(text):
    return adb_shell('input', 'text', text)


def adb_keyevent(key_code):
    return adb_shell('input', 'keyevent', str(key_code))


def adb_logcat(timeout=30):
    text = _adb(['logcat', '-d', '-t', '1000'], timeout)
    _output_path('logcat.txt').write_text(text, encoding='utf-8')
    return text


def record_capture(seconds):
    from AutoScriptor import sleep
    sleep(seconds)


def _target(target):
    from AutoScriptor import B, I, T, Box
    options = {}
    if target.box is not None:
        region = Box(*target.box)
        options['box'] = region.margin(*target.margin) if target.margin else region
    if target.color is not None:
        options['color'] = target.color
    if target.kind == 'B':
        return B(*target.value, color=target.color)
    return (T if target.kind == 'T' else I)(target.value, **options)


def _targets(targets, grouping):
    converted = [_target(target) for target in targets]
    if grouping == 'all':
        return converted
    if grouping == 'any':
        return tuple(converted)
    return converted[0]


def _prepare_call(command, values):
    """Resolve current exports on each call, including after platform reloads."""
    spec = COMMANDS[command.name]
    function = getattr(import_module(spec.module), spec.function)
    arguments = list(command.arguments)
    options = dict(command.options)
    if command.targets:
        if spec.targets in ('sequence', 'pair'):
            converted = [_target(target) for target in command.targets]
            arguments.extend(converted if spec.targets == 'pair' else [converted])
        else:
            arguments.append(_targets(command.targets, command.grouping))
    if 'post_process' in options:
        processor = options['post_process']
        options['post_process'] = str.strip if processor == 'strip' else getattr(import_module('AutoScriptor'), processor)
    if command.frame:
        options[spec.frame_parameter] = values[command.frame]
    if command.until:
        predicate = getattr(import_module('AutoScriptor'), 'ui_F' if command.until_gone else 'ui_T')
        condition = _targets(command.until, command.until_grouping)
        options['until'] = lambda: predicate(condition)
    inspect.signature(function).bind(*arguments, **options)
    if command.via:
        function = getattr(import_module('AutoScriptor'), f'ctrl_{command.via}')(function)
    return function, arguments, options


def execute_command(command, values):
    """Dispatch a validated command, not arbitrary Python or module paths."""
    function, arguments, options = _prepare_call(command, values)
    return function(*arguments, **options)


def encode_result(value):
    """Keep structured values; do not serialize screenshots as huge JSON arrays."""
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(key): encode_result(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode_result(item) for item in value]
    if hasattr(value, 'shape') and hasattr(value, 'dtype'):
        return {'shape': list(value.shape), 'dtype': str(value.dtype), 'kind': 'frame'}
    if all(hasattr(value, field) for field in ('left', 'top', 'width', 'height')):
        return {field: getattr(value, field) for field in ('left', 'top', 'width', 'height')}
    return repr(value)


class ExecutionAdapter:
    """One run's resources; device ownership stays with RuntimeContext."""
    def __init__(self):
        self.directory = None
        self.control = None
        self.recorder = None
        self.output_token = None
        self.capture_enabled = False
        self.log_handler = None

    def prepare(self, plan, directory, timeout):
        from AutoScriptor.logging.tracer import is_run_capture_enabled, set_run_capture, take_debug_screenshots
        self.directory = directory
        self.output_token = _OUTPUT_DIRECTORY.set(directory)
        self.capture_enabled = is_run_capture_enabled()
        from AutoScriptor.logging.logger import logger
        self.log_handler = logging.FileHandler(directory / 'runtime.log', encoding='utf-8')
        self.log_handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        worker_ident = threading.get_ident()
        self.log_handler.addFilter(lambda record: record.thread == worker_ident)
        logger.addHandler(self.log_handler)
        for command in plan.commands:
            _prepare_call(command, {command.frame: None})
            if command.name == 'adb-push' and not Path(command.arguments[0]).is_file():
                raise ValueError(f'line {command.line}: ADB push source is not a backend-host file')
        if not any(COMMANDS[command.name].device for command in plan.commands):
            return
        from AutoScriptor.core.runtime_context import runtime_ctx
        from AutoScriptor.core.control import clear_action_history
        from AutoScriptor.logging.task_video_recorder import TaskVideoRecorder
        self.control, _mumu = runtime_ctx.ensure_device_session(reason='ascli flow', launch_app=False)
        if shutil.disk_usage(directory).free < 512 * 1024 * 1024:
            raise RuntimeError('At least 512 MiB of free disk space is required for debug evidence')
        # Preserve previous evidence separately rather than attributing it to this run.
        take_debug_screenshots(directory.parent / 'previous_screenshots')
        clear_action_history()
        set_run_capture(True)
        self.recorder = TaskVideoRecorder(f'ascli/{directory.name}', keep_segments=math.ceil(timeout / 165) + 2, retain_all=True)
        self.recorder.start()
        if not self.recorder.is_recording:
            raise RuntimeError('Debug recording could not start; no flow actions were executed')

    def execute(self, command, values):
        if self.recorder is not None and not self.recorder.is_recording:
            raise RuntimeError('Debug recorder stopped before the flow completed')
        return execute_command(command, values)

    def finish(self, error):
        from AutoScriptor.logging.tracer import set_run_capture, take_debug_screenshots
        from AutoScriptor.utils.cancel import suppress_cancel_checks
        warnings = []
        evidence = {'warnings': warnings}
        try:
            with suppress_cancel_checks():
                if self.control is not None:
                    for label, cleanup in (('keys', self.control.release_all_keys), ('fingers', self.control.release_all_fingers), ('capture', lambda: screenshot('final.png'))):
                        try:
                            cleanup()
                        except Exception as cleanup_error:
                            warnings.append(f'Final {label}: {cleanup_error}')
                if self.recorder is not None:
                    video = self.recorder.stop(keep=True)
                    if video:
                        try:
                            shutil.move(str(video), str(self.directory / 'video'))
                        except OSError as move_error:
                            warnings.append(f'Video remains at {video}: {move_error}')
                    evidence['recording'] = self.recorder.recording_status()
                    if not video or not evidence['recording']['complete']:
                        warnings.append('Recording is missing or incomplete')
                if self.control is not None:
                    take_debug_screenshots(self.directory / 'debug_screenshots')
                if error is not None:
                    from AutoScriptor.logging.log_archiver import archive_error
                    evidence['error_archive'] = archive_error(f'ascli_{self.directory.name}', error, self.control, include_run_screenshots=False, video_path=self.directory / 'video', include_runtime_context=self.control is not None)
                    if not evidence['error_archive']:
                        warnings.append('Error archive could not be created; inspect error.log in this run')
        finally:
            set_run_capture(self.capture_enabled)
            if self.log_handler is not None:
                from AutoScriptor.logging.logger import logger
                logger.removeHandler(self.log_handler)
                self.log_handler.close()
            if self.output_token is not None:
                _OUTPUT_DIRECTORY.reset(self.output_token)
        return evidence
