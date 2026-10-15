"""swipe.py — Swipe on Android device by coordinates or direction."""

import sys
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import add_device_args, connect_device


def main():
    parser = argparse.ArgumentParser(
        description='Swipe on Android device by coordinates or direction',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='Examples:\n'
               '  python swipe.py 540 1400 540 400\n'
               '  python swipe.py --direction up\n'
               '  python swipe.py --direction down --duration 1.0\n'
    )
    add_device_args(parser)
    parser.add_argument('coords', type=int, nargs='*',
                        help='x1 y1 x2 y2 coordinates')
    parser.add_argument('--direction', type=str, choices=['up', 'down', 'left', 'right'],
                        help='Swipe direction (up/down/left/right)')
    parser.add_argument('--duration', type=float, default=0.5,
                        help='Swipe duration in seconds (default: 0.5)')

    args = parser.parse_args()

    has_coords = len(args.coords) == 4
    has_direction = args.direction is not None

    if has_coords and has_direction:
        parser.error('Cannot use both coordinates and --direction')
    if not has_coords and not has_direction:
        if len(args.coords) > 0 and len(args.coords) != 4:
            parser.error('Coordinates require exactly 4 values: x1 y1 x2 y2')
        parser.error('Must provide (x1 y1 x2 y2) coordinates or --direction')

    d = connect_device(args.serial)

    if has_direction:
        # Direction-based swipe: compute coords from screen size
        w, h = d.window_size()

        direction_map = {
            'up':    (w // 2, int(h * 0.75), w // 2, int(h * 0.25)),
            'down':  (w // 2, int(h * 0.25), w // 2, int(h * 0.75)),
            'left':  (int(w * 0.75), h // 2, int(w * 0.25), h // 2),
            'right': (int(w * 0.25), h // 2, int(w * 0.75), h // 2),
        }

        x1, y1, x2, y2 = direction_map[args.direction]
        d.swipe(x1, y1, x2, y2, duration=args.duration)
        print(f'Swiped {args.direction} from ({x1}, {y1}) to ({x2}, {y2}) in {args.duration}s')

    else:
        x1, y1, x2, y2 = args.coords
        d.swipe(x1, y1, x2, y2, duration=args.duration)
        print(f'Swiped from ({x1}, {y1}) to ({x2}, {y2}) in {args.duration}s')


if __name__ == '__main__':
    main()
