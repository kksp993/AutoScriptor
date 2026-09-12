"""tap.py — Tap on Android device by coordinates or by text (OCR-based)."""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import add_device_args, connect_device, take_screenshot, match_text_in_screenshot


def main():
    parser = argparse.ArgumentParser(
        description='Tap on Android device by coordinates or text',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Examples:\n'
               '  python tap.py 540 960\n'
               '  python tap.py --text "收集奖励"\n'
               '  python tap.py 540 960 --long --duration 3.0\n'
    )
    add_device_args(parser)
    parser.add_argument('x', type=int, nargs='?', help='X coordinate')
    parser.add_argument('y', type=int, nargs='?', help='Y coordinate')
    parser.add_argument('--text', type=str, help='Text to find and tap (OCR-based)')
    parser.add_argument('--long', action='store_true', help='Long press mode')
    parser.add_argument('--duration', type=float, default=1.5,
                        help='Long press duration in seconds (default: 1.5)')

    args = parser.parse_args()

    # Validate: must provide coords or --text, not both
    has_coords = args.x is not None and args.y is not None
    has_text = args.text is not None

    if has_coords and has_text:
        parser.error('Cannot use both coordinates and --text')
    if not has_coords and not has_text:
        parser.error('Must provide (x y) coordinates or --text')

    d = connect_device(args.serial)

    if has_text:
        # Text-based tap: screenshot → OCR → tap
        img = take_screenshot(d)
        matches = match_text_in_screenshot(img, args.text, exact_match=False)

        if not matches:
            print(f'ERROR: Text "{args.text}" not found on screen', file=sys.stderr)
            sys.exit(1)

        # Print all matches for AI reference
        if len(matches) > 1:
            print(f'Found {len(matches)} matches for "{args.text}":')
            for i, m in enumerate(matches):
                print(f'  [{i}] "{m["text"]}" at ({m["coords"]["x"]},{m["coords"]["y"]}) conf={m["confidence"]:.2f}')

        # Tap first match
        target = matches[0]
        tx, ty = target["coords"]["x"], target["coords"]["y"]

        if args.long:
            d.long_click(tx, ty, duration=args.duration)
            print(f'Found "{args.text}" at ({tx}, {ty}), long pressed ({args.duration}s)')
        else:
            d.click(tx, ty)
            print(f'Found "{args.text}" at ({tx}, {ty}), tapped')

    else:
        # Coordinate tap
        if args.long:
            d.long_click(args.x, args.y, duration=args.duration)
            print(f'Long pressed at ({args.x}, {args.y}) for {args.duration}s')
        else:
            d.click(args.x, args.y)
            print(f'Tapped at ({args.x}, {args.y})')


if __name__ == '__main__':
    main()
