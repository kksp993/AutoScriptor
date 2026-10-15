"""keyevent.py — Send hardware key events to Android device."""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import add_device_args, connect_device

KEY_MAP = {
    'home': 3,
    'back': 4,
    'dpad_up': 19,
    'dpad_down': 20,
    'dpad_left': 21,
    'dpad_right': 22,
    'volume_up': 24,
    'volume_down': 25,
    'power': 26,
    'tab': 61,
    'space': 62,
    'enter': 66,
    'delete': 67,
    'escape': 111,
    'volume_mute': 164,
    'recent': 187,
}


def main():
    parser = argparse.ArgumentParser(
        description='Send key event to Android device',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Supported key names:\n  ' +
               ', '.join(f'{k} ({v})' for k, v in sorted(KEY_MAP.items(), key=lambda x: x[1]))
    )
    add_device_args(parser)
    parser.add_argument('key', type=str, help='Key name or numeric keycode')

    args = parser.parse_args()

    # Resolve key to keycode
    key_input = args.key.strip().lower()

    if key_input.isdigit():
        keycode = int(key_input)
        key_name = next((k for k, v in KEY_MAP.items() if v == keycode), str(keycode))
    elif key_input in KEY_MAP:
        keycode = KEY_MAP[key_input]
        key_name = key_input
    else:
        print(f'Unknown key: "{args.key}"', file=sys.stderr)
        print(f'Supported keys: {", ".join(sorted(KEY_MAP.keys()))}', file=sys.stderr)
        sys.exit(1)

    d = connect_device(args.serial)
    d.shell(f'input keyevent {keycode}')
    print(f'Sent key: {key_name} (keycode {keycode})')


if __name__ == '__main__':
    main()
