from __future__ import annotations

import io
import logging
import os
import sys
import unittest

import AutoScriptor
from AutoScriptor.control.NemuIpc.device.method.nemu_ipc import CaptureStd
from AutoScriptor.utils import logger as logger_module


def _record(message: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="AutoScriptor",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=message,
        args=(),
        exc_info=None,
    )


class LoggerResilienceTest(unittest.TestCase):
    def test_logger_is_available_from_public_autoscriptor_api(self):
        self.assertIn("logger", AutoScriptor.__all__)
        self.assertIs(AutoScriptor.logger, logger_module.logger)

    def test_internal_log_record_uses_first_external_project_caller(self):
        synthetic_internal_path = os.path.join(
            logger_module._AUTOSCRIPTOR_PACKAGE_ROOT,
            "core",
            "synthetic_internal_logger.py",
        )
        synthetic_namespace = {}
        exec(
            compile(
                "def apply_filter(record, caller_filter):\n"
                "    return caller_filter.filter(record)\n",
                synthetic_internal_path,
                "exec",
            ),
            synthetic_namespace,
        )
        record = logging.LogRecord(
            name="AutoScriptor",
            level=logging.INFO,
            pathname=synthetic_internal_path,
            lineno=12,
            msg="internal operation",
            args=(),
            exc_info=None,
        )
        expected_line_number = sys._getframe().f_lineno + 1
        synthetic_namespace["apply_filter"](record, logger_module._ExternalCallerFilter())

        self.assertEqual(os.path.normcase(record.pathname), os.path.normcase(__file__))
        self.assertEqual(record.filename, os.path.basename(__file__))
        self.assertEqual(record.module, os.path.splitext(os.path.basename(__file__))[0])
        self.assertEqual(record.lineno, expected_line_number)
        self.assertEqual(record.funcName, self.test_internal_log_record_uses_first_external_project_caller.__name__)

    def test_external_log_record_keeps_original_caller(self):
        record = _record("external operation")

        logger_module._ExternalCallerFilter().filter(record)

        self.assertEqual(os.path.normcase(record.pathname), os.path.normcase(__file__))
        self.assertEqual(record.lineno, 1)

    def test_safe_stream_handler_rebinds_closed_stream(self):
        closed_stream = io.StringIO()
        closed_stream.close()
        fallback_stream = io.StringIO()
        original_safe_stderr = logger_module._safe_stderr
        logger_module._safe_stderr = lambda: fallback_stream
        try:
            handler = logger_module._SafeStreamHandler(stream=closed_stream)
            handler.setFormatter(logging.Formatter("%(message)s"))
            handler.emit(_record("stream survived"))
        finally:
            logger_module._safe_stderr = original_safe_stderr

        self.assertIn("stream survived", fallback_stream.getvalue())

    @unittest.skipUnless(
        hasattr(logger_module, "_SafeRichHandler"),
        "Rich logger is unavailable in compiled mode",
    )
    def test_safe_rich_handler_rebinds_closed_console(self):
        closed_stream = io.StringIO()
        closed_stream.close()
        fallback_stream = io.StringIO()

        original_console = logger_module._console
        original_make_console = logger_module._make_console
        logger_module._make_console = lambda: logger_module.Console(
            file=fallback_stream,
            force_terminal=False,
            force_jupyter=False,
            color_system=None,
            legacy_windows=False,
        )
        try:
            handler = logger_module._SafeRichHandler(
                console=logger_module.Console(
                    file=closed_stream,
                    force_terminal=False,
                    force_jupyter=False,
                    color_system=None,
                    legacy_windows=False,
                ),
                show_time=False,
                show_path=False,
                markup=False,
            )
            handler.emit(_record("rich survived"))
        finally:
            logger_module._console = original_console
            logger_module._make_console = original_make_console

        self.assertIn("rich survived", fallback_stream.getvalue())

    @unittest.skipUnless(
        hasattr(logger_module, "_SafeRichHandler"),
        "Rich logger is unavailable in compiled mode",
    )
    def test_rich_handler_uses_valid_windows_file_uri(self):
        output_stream = io.StringIO()
        handler = logger_module._SafeRichHandler(
            console=logger_module.Console(
                file=output_stream,
                force_terminal=True,
                force_jupyter=False,
                color_system="truecolor",
                legacy_windows=False,
            ),
            show_time=False,
            show_level=False,
            show_path=True,
            enable_link_path=True,
            markup=False,
        )
        record = logging.LogRecord(
            name="AutoScriptor",
            level=logging.INFO,
            pathname=r"D:\Projects\Auto Scriptor\中文任务.py",
            lineno=27,
            msg="clickable source",
            args=(),
            exc_info=None,
        )

        handler.emit(record)

        rendered_output = output_stream.getvalue()
        expected_uri = "file:///D:/Projects/Auto%20Scriptor/%E4%B8%AD%E6%96%87%E4%BB%BB%E5%8A%A1.py"
        self.assertIn(expected_uri, rendered_output)
        self.assertNotIn(r"file://D:\Projects", rendered_output)
        self.assertIn("\x1b[2m中文任务.py\x1b[0m", rendered_output)
        self.assertNotIn("\x1b[2m%E4%B8%AD%E6%96%87%E4%BB%BB%E5%8A%A1.py\x1b[0m", rendered_output)
        self.assertEqual(record.pathname, r"D:\Projects\Auto Scriptor\中文任务.py")

    def test_rich_link_path_skips_python_pseudo_files(self):
        self.assertIsNone(logger_module._rich_link_path("<frozen importlib._bootstrap>"))


class CaptureStdTest(unittest.TestCase):
    def test_capture_std_preserves_python_stream_objects(self):
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.fileno()
            except Exception:
                self.skipTest("current test runner stream does not expose fileno()")

        original_stdout = sys.stdout
        original_stderr = sys.stderr
        with CaptureStd() as capture:
            print("captured stdout")
            print("captured stderr", file=sys.stderr)

        self.assertIs(sys.stdout, original_stdout)
        self.assertIs(sys.stderr, original_stderr)
        self.assertIn(b"captured stdout", capture.stdout)
        self.assertIn(b"captured stderr", capture.stderr)


if __name__ == "__main__":
    unittest.main()
