"""screenshot.py — Capture a simple screenshot from an Android device."""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import add_device_args, connect_device, take_screenshot, DEFAULT_OUTPUT_DIR


def main():
    default_output = str(Path(DEFAULT_OUTPUT_DIR) / 'screenshot.png')
    parser = argparse.ArgumentParser(description='Capture screenshot from Android device')
    add_device_args(parser)
    parser.add_argument('-o', '--output', type=str, default=default_output,
                        help=f'Output file path (default: {default_output})')

    args = parser.parse_args()
    d = connect_device(args.serial)
    take_screenshot(d, args.output)


if __name__ == '__main__':
    main()