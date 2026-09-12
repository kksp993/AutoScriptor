"""input_text.py — Type text into Android device with full Unicode support.

Supports two modes (recommended: use --res-id or --coord):
1. Resource ID mode (--res-id): Directly set text using set_text() (most reliable)
2. Coordinate mode (--coord): Click at coordinates then type text
3. Legacy mode: Just type text (requires focus to be set manually)

Default behavior: Clears existing text before input. Use --append to append instead.
"""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import add_device_args, connect_device


def main():
    parser = argparse.ArgumentParser(
        description='Type text into Android device (supports Chinese/Unicode). '
                    'By default clears existing text; use --append to append.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Recommended Usage (choose one):\n'
               '  # Method 1: Use Resource ID (most reliable)\n'
               '  python input_text.py "hello" --res-id com.example:id/edit_text\n\n'
               '  # Method 2: Use coordinates\n'
               '  python input_text.py "hello" --coord 500 800\n\n'
               '  # Method 3: Legacy (requires manual focus)\n'
               '  python input_text.py "hello"\n\n'
               'Other options:\n'
               '  python input_text.py "more text" --res-id com.example:id/edit --append'
    )
    add_device_args(parser)
    parser.add_argument('text', type=str, help='Text to type')
    parser.add_argument('--res-id', type=str, metavar='ID',
                        help='Resource ID of input field (recommended)')
    parser.add_argument('--coord', type=int, nargs=2, metavar=('X', 'Y'),
                        help='Click coordinates before typing (x y)')
    parser.add_argument('--append', action='store_true',
                        help='Append to existing text instead of clearing (default: clear)')

    args = parser.parse_args()

    d = connect_device(args.serial)

    # Determine if we should clear (default True, --append to disable)
    should_clear = not args.append

    # Method 1: Resource ID mode (recommended)
    if args.res_id:
        element = d(resourceId=args.res_id)
        if not element.exists:
            print(f'ERROR: Element with resourceId="{args.res_id}" not found', file=sys.stderr)
            sys.exit(1)

        if should_clear:
            element.clear_text()
            print('Cleared field')

        if args.append:
            # Append mode: use send_keys to add to existing text
            element.click()
            d.send_keys(args.text)
            print(f'Appended text via resourceId="{args.res_id}": "{args.text}"')
        else:
            # Replace mode: use set_text
            element.set_text(args.text)
            print(f'Set text via resourceId="{args.res_id}": "{args.text}"')
        return

    # Method 2: Coordinate mode
    if args.coord:
        x, y = args.coord
        d.click(x, y)
        print(f'Clicked at ({x}, {y})')

        if should_clear:
            # Select all + delete, with brute-force backspace fallback
            cleared = _try_clear_field(d)
            if cleared:
                print('Cleared field')

        # Use uiautomator2 send_keys for full Unicode support
        d.send_keys(args.text)
        action = "Appended" if args.append else "Typed"
        print(f'{action}: "{args.text}"')
        return

    # Method 3: Legacy mode (requires focus to be set manually)
    if should_clear:
        # Select all + delete, with brute-force backspace fallback
        cleared = _try_clear_field(d)
        if cleared:
            print('Cleared field')

    # Use uiautomator2 send_keys for full Unicode support
    d.send_keys(args.text)
    action = "Appended" if args.append else "Typed"
    print(f'{action}: "{args.text}"')


def _try_clear_field(d, max_attempts: int = 3) -> bool:
    """
    Try to clear text field by selecting all text then deleting it.
    Returns True if likely succeeded, False otherwise.

    Strategy:
    1. First try Ctrl+A (select all) via 'input keycombination' (Android 12+)
       then press Delete to remove selected text.
    2. Fallback: Move cursor to end, then send many backspace keys to brute-force clear.
    """
    try:
        # Strategy 1: Try Ctrl+A select all, then Delete
        # 'input keycombination' requires Android 12+ (API 31+)
        # keycode 113 = CTRL_LEFT, keycode 29 = A
        ret = d.shell('input keycombination 113 29')
        if ret[0] == 0:
            # Ctrl+A succeeded, now delete selected text
            import time
            time.sleep(0.1)
            d.shell('input keyevent 67')  # KEYCODE_DEL (Backspace)
            return True

        # Strategy 2: Fallback for older Android versions
        # Move to end of text, then brute-force backspace
        d.shell('input keyevent 123')  # KEYCODE_MOVE_END
        import time
        time.sleep(0.05)
        # Send a burst of backspace keys to clear (handles up to ~200 chars)
        # Using a single shell call with multiple keyevents for efficiency
        backspace_cmds = ' '.join(['67'] * 50)
        for _ in range(max_attempts):
            d.shell(f'input keyevent {backspace_cmds}')
            time.sleep(0.05)
        return True
    except Exception as e:
        print(f'Warning: Clear field may have failed: {e}', file=sys.stderr)
        return False


if __name__ == '__main__':
    main()