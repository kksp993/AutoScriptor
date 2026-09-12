"""
uiscan.py — Screenshot + UI element recognition for Android devices.

Dual-source: dump_hierarchy (accessibility tree) + RapidOCR (text detection).
Outputs annotated screenshot + element list JSON.
"""

import sys
import os
import re
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    add_device_args, connect_device, take_screenshot,
    UIElement, filter_by_size, rects_overlap,
    draw_elements_on_screenshot, save_elements_json, print_elements_summary,
    ocr_image, DEFAULT_OUTPUT_DIR,
)


# ==================== Hierarchy Parsing ====================

def parse_bounds(bounds_str: str) -> Optional[Tuple[int, int, int, int]]:
    """Parse '[left,top][right,bottom]' to (left, top, right, bottom)."""
    m = re.match(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]', bounds_str)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4))


def parse_hierarchy(xml_str: str) -> List[UIElement]:
    """
    Parse dump_hierarchy XML into UIElement list.

    Include nodes where:
      - clickable="true" OR
      - has non-empty text OR
      - has non-empty content-desc OR
      - scrollable="true"

    Exclude nodes where:
      - bounds area is 0
      - enabled="false"
    """
    elements = []
    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError as e:
        print(f"ERROR: XML parse error: {e}", file=sys.stderr)
        return elements

    # Get screen size from root for full-screen filtering
    screen_w, screen_h = 0, 0
    for node in root.iter('node'):
        bounds = parse_bounds(node.get('bounds', ''))
        if bounds:
            _, _, r, b = bounds
            screen_w = max(screen_w, r)
            screen_h = max(screen_h, b)
        break  # first node usually has full screen bounds

    for node in root.iter('node'):
        text = node.get('text', '').strip()
        content_desc = node.get('content-desc', '').strip()
        clickable = node.get('clickable', 'false') == 'true'
        scrollable = node.get('scrollable', 'false') == 'true'
        enabled = node.get('enabled', 'true') == 'true'
        resource_id = node.get('resource-id', '')
        class_name = node.get('class', '')

        # Filter: must meet at least one inclusion criterion
        if not (clickable or text or content_desc or scrollable):
            continue

        # Filter: must be enabled
        if not enabled:
            continue

        # Parse bounds
        bounds = parse_bounds(node.get('bounds', ''))
        if not bounds:
            continue

        left, top, right, bottom = bounds
        width = right - left
        height = bottom - top

        # Filter: zero area
        if width <= 0 or height <= 0:
            continue

        # Filter: full-screen container (within 5px tolerance)
        if (screen_w > 0 and screen_h > 0 and
                left <= 5 and top <= 5 and
                right >= screen_w - 5 and bottom >= screen_h - 5):
            continue

        center_x = left + width // 2
        center_y = top + height // 2

        # Determine display name: prefer text, then content-desc, then short class name
        name = text or content_desc or class_name.split('.')[-1]

        # Simplify control_type from class_name
        control_type = class_name.split('.')[-1] if class_name else "Unknown"

        elements.append(UIElement(
            name=name,
            control_type=control_type,
            coords={"x": center_x, "y": center_y},
            size={"width": width, "height": height},
            resource_id=resource_id,
            class_name=class_name,
            clickable=clickable,
            text=text,
            content_desc=content_desc,
        ))

    return elements


def call_hierarchy_scan(device) -> List[UIElement]:
    """Get UI elements from dump_hierarchy."""
    print("Scanning accessibility tree (dump_hierarchy)...")
    try:
        xml_str = device.dump_hierarchy()
        elements = parse_hierarchy(xml_str)
        print(f"Hierarchy: {len(elements)} elements")
        return elements
    except Exception as e:
        print(f"ERROR: Hierarchy scan failed: {e}", file=sys.stderr)
        return []


# ==================== OCR Scanning ====================

def call_ocr_scan(screenshot_path: str) -> List[UIElement]:
    """Get UI elements from RapidOCR text detection."""
    print("Running OCR text detection...")
    try:
        image = cv2.imread(screenshot_path)
        if image is None:
            print(f"ERROR: Failed to load screenshot: {screenshot_path}", file=sys.stderr)
            return []

        ocr_results = ocr_image(image)
        elements = []
        for item in ocr_results:
            elements.append(UIElement(
                name=item["text"],
                control_type="OCRText",
                coords={"x": item["center_x"], "y": item["center_y"]},
                size={"width": item["width"], "height": item["height"]},
            ))

        print(f"OCR: {len(elements)} text regions")
        return elements

    except Exception as e:
        print(f"ERROR: OCR scan failed: {e}", file=sys.stderr)
        return []


# ==================== Merge ====================

def merge_results(
    hierarchy_elements: List[UIElement],
    ocr_elements: List[UIElement]
) -> List[UIElement]:
    """
    Merge hierarchy and OCR elements.

    Hierarchy elements take priority when overlapping with OCR
    (they have richer metadata: resourceId, className, clickable).
    """
    ocr_to_remove = set()

    for hier_elem in hierarchy_elements:
        hier_rect = hier_elem.get_rect()
        for ocr_idx, ocr_elem in enumerate(ocr_elements):
            ocr_rect = ocr_elem.get_rect()
            if rects_overlap(hier_rect, ocr_rect):
                ocr_to_remove.add(ocr_idx)

    filtered_ocr = [
        elem for idx, elem in enumerate(ocr_elements)
        if idx not in ocr_to_remove
    ]

    merged = hierarchy_elements + filtered_ocr

    print(f"Merged: {len(hierarchy_elements)} hierarchy + {len(filtered_ocr)} OCR = {len(merged)} total")

    return merged


# ==================== Main ====================

def run_uiscan(args):
    """Main uiscan workflow."""
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    base_name = args.name

    # 1. Connect and screenshot
    d = connect_device(args.serial)
    print("Step 1/5: Capturing screenshot...")
    temp_screenshot = str(output_dir / f"{base_name}_raw.png")
    take_screenshot(d, temp_screenshot)

    # 2. Screenshot-only mode
    if args.screenshot_only:
        final_path = str(output_dir / f"{base_name}.png")
        os.replace(temp_screenshot, final_path)
        print(f"Screenshot saved: {final_path}")
        return

    # 3. Run recognition sources
    print("Step 2/5: Running recognition...")
    hierarchy_elements = []
    ocr_elements = []

    if not args.no_hierarchy and not args.no_ocr:
        # Parallel execution
        with ThreadPoolExecutor(max_workers=2) as executor:
            hier_future = executor.submit(call_hierarchy_scan, d)
            ocr_future = executor.submit(call_ocr_scan, temp_screenshot)

            for future in as_completed([hier_future, ocr_future]):
                try:
                    if future == hier_future:
                        hierarchy_elements = future.result()
                    else:
                        ocr_elements = future.result()
                except Exception as e:
                    print(f"ERROR: Recognition task failed: {e}", file=sys.stderr)
    elif not args.no_hierarchy:
        hierarchy_elements = call_hierarchy_scan(d)
    elif not args.no_ocr:
        ocr_elements = call_ocr_scan(temp_screenshot)

    # 4. Filter by size
    print("Step 3/5: Filtering elements...")
    hierarchy_elements = filter_by_size(hierarchy_elements)
    ocr_elements = filter_by_size(ocr_elements)

    # 5. Merge
    print("Step 4/5: Merging results...")
    elements = merge_results(hierarchy_elements, ocr_elements)

    # 6. Draw annotated screenshot
    print("Step 5/5: Saving results...")
    print("\n============ RESULT ============")
    annotated_path = str(output_dir / f"{base_name}.png")
    draw_elements_on_screenshot(temp_screenshot, elements, annotated_path)

    # 7. Save JSON (only if requested)
    if args.save_json:
        elements_path = str(output_dir / f"{base_name}_elements.json")
        save_elements_json(elements, elements_path)

    # 8. Cleanup temp
    try:
        if os.path.exists(temp_screenshot) and temp_screenshot != annotated_path:
            os.remove(temp_screenshot)
    except Exception:
        pass

    # 9. Print summary
    print_elements_summary(elements)


def main():
    parser = argparse.ArgumentParser(
        description='UIScan — Android UI element recognition',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_device_args(parser)
    parser.add_argument('-o', '--output-dir', type=str, default=DEFAULT_OUTPUT_DIR,
                        help=f'Output directory (default: {DEFAULT_OUTPUT_DIR})')
    parser.add_argument('-n', '--name', type=str, default='uiscan_result',
                        help='Output file prefix (default: uiscan_result)')
    parser.add_argument('--screenshot-only', action='store_true',
                        help='Only capture screenshot, skip UI analysis')
    parser.add_argument('--no-ocr', action='store_true',
                        help='Skip OCR, use hierarchy only')
    parser.add_argument('--no-hierarchy', action='store_true',
                        help='Skip hierarchy, use OCR only')
    parser.add_argument('--save-json', action='store_true',
                        help='Save elements to JSON file ({name}_elements.json)')

    args = parser.parse_args()
    run_uiscan(args)


if __name__ == '__main__':
    main()
