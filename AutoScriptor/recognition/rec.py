from AutoScriptor.recognition.img_rec import imgOnScreen
from AutoScriptor.recognition.ocr_rec import ocr
from AutoScriptor.utils.box import Box


def locate_on_screen(haystack_frame, targets, confidence=0.8, pf_boxes=None, colors=None):
    img_targets, text_targets, box_targets = [], [], []
    img_pf_boxes, text_pf_boxes = [], []
    img_colors, text_colors, box_colors = [], [], []
    ids = []

    for i, target in enumerate(targets):
        if isinstance(target, str):
            text_targets.append(target)
            text_pf_boxes.append(pf_boxes[i])
            text_colors.append(colors[i])
            ids.append("t" + str(len(text_targets) - 1))
        elif isinstance(target, Box):
            box_targets.append(target)
            box_colors.append(colors[i] if colors is not None else None)
            ids.append("b" + str(len(box_targets) - 1))
        else:
            img_targets.append(target)
            img_pf_boxes.append(pf_boxes[i])
            img_colors.append(colors[i])
            ids.append("i" + str(len(img_targets) - 1))

    if (img_targets and text_targets) or box_targets:
        img_boxes = locate_on_screen(haystack_frame, img_targets, confidence, img_pf_boxes, img_colors) if img_targets else []
        text_boxes = locate_on_screen(haystack_frame, text_targets, confidence, text_pf_boxes, text_colors) if text_targets else []
        box_boxes = []
        for j, box in enumerate(box_targets):
            color = box_colors[j]
            if color:
                detected_color = get_box_color(haystack_frame, box)
                box_boxes.append([box] if detected_color == color else None)
            else:
                box_boxes.append([box])
        return [
            img_boxes[int(item[1:])]
            if item[0] == "i"
            else text_boxes[int(item[1:])]
            if item[0] == "t"
            else box_boxes[int(item[1:])]
            for item in ids
        ]

    def get_roi(preferred_box):
        if preferred_box:
            return haystack_frame[
                preferred_box.top:preferred_box.top + preferred_box.height,
                preferred_box.left:preferred_box.left + preferred_box.width,
            ]
        return haystack_frame

    roi_dict = {pf_box: get_roi(pf_box) for pf_box in set(pf_boxes)}
    roi = next(iter(roi_dict.values())) if len(roi_dict) == 1 else haystack_frame

    if isinstance(targets[0], str):
        from AutoScriptor.utils.app_config import cfg as _cfg

        scale = float(_cfg.get("ocr.scale", 1.0))
        res = ocr(roi, targets, confidence, None, scale=scale)
        assert res is not None, "ocr returned None"
    else:
        res = imgOnScreen(roi, targets, confidence=confidence)
        assert res is not None, "imgOnScreen returned None"

    def to_full_frame(box, preferred_box):
        return Box(
            box.left + preferred_box.left,
            box.top + preferred_box.top,
            box.width,
            box.height,
        )

    if len(roi_dict) == 1:
        res = [[to_full_frame(box, pf_boxes[i]) for box in res[i]] for i in range(len(targets))]

    for i, boxes in enumerate(res):
        for box in list(boxes):
            if not box.is_in(pf_boxes[i]):
                boxes.remove(box)
        if not boxes:
            res[i] = None

    for i, boxes in enumerate(res):
        if colors[i] and boxes:
            res_color = [get_box_color(haystack_frame, box) for box in boxes]
            if colors[i] not in res_color:
                res[i] = None
            else:
                res[i] = [boxes[j] for j in range(len(boxes)) if res_color[j] == colors[i]]

    return res


def get_box_color(haystack_frame, box):
    import cv2
    import numpy as np

    roi = haystack_frame[box.top:box.top + box.height, box.left:box.left + box.width]
    if roi.size == 0:
        return "区域无效"

    hsv_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    lower_bound = np.array([0, 50, 50])
    upper_bound = np.array([180, 255, 255])
    mask = cv2.inRange(hsv_roi, lower_bound, upper_bound)

    if mask.any():
        hist = cv2.calcHist([hsv_roi], [0], mask, [180], [0, 180])
        h_main = np.argmax(hist)
        s_main = np.mean(hsv_roi[mask > 0][:, 1])
        v_main = np.mean(hsv_roi[mask > 0][:, 2])
    else:
        h_main = 0
        s_main = 0
        v_main = np.mean(hsv_roi[:, :, 2])

    def get_hsv_color_name(h_value, s_value, v_value):
        if s_value <= 50:
            if v_value <= 50:
                return "黑色"
            if v_value <= 220:
                return "灰色"
            return "白色"
        if (0 <= h_value <= 10) or (156 <= h_value <= 180):
            return "红色"
        if 11 <= h_value <= 25:
            return "橙色"
        if 26 <= h_value <= 34:
            return "黄色"
        if 35 <= h_value <= 77:
            return "绿色"
        if 78 <= h_value <= 99:
            return "青色"
        if 100 <= h_value <= 124:
            return "蓝色"
        if 125 <= h_value <= 155:
            return "紫色"
        return "其他"

    return get_hsv_color_name(h_main, s_main, v_main)
