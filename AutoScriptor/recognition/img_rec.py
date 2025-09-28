import cv2
import numpy

from AutoScriptor.utils.box import Box

GRAYSCALE_DEFAULT = False

def _load_cv2(img, grayscale=None):
    """
    TODO
    """
    # load images if given filename, or convert as needed to opencv
    # Alpha layer just causes failures at this point, so flatten to RGB.
    # RGBA: load with -1 * cv2.CV_LOAD_IMAGE_COLOR to preserve alpha
    # to matchTemplate, need template and image to be the same wrt having alpha
    if grayscale is None:
        grayscale = GRAYSCALE_DEFAULT
    if isinstance(img, str):
        # The function imread loads an image from the specified file and
        # returns it. If the image cannot be read (because of missing
        # file, improper permissions, unsupported or invalid format),
        # the function returns an empty matrix
        # http://docs.opencv.org/3.0-beta/modules/imgcodecs/doc/reading_and_writing_images.html
        if grayscale:
            img_cv = cv2.imread(img, cv2.IMREAD_GRAYSCALE)
        else:
            img_cv = cv2.imread(img, cv2.IMREAD_COLOR)
        if img_cv is None:
            raise IOError(
                "Failed to read %s because file is missing, "
                "has improper permissions, or is an "
                "unsupported or invalid format" % img
            )
    elif isinstance(img, numpy.ndarray):
        # don't try to convert an already-gray image to gray
        if grayscale and len(img.shape) == 3:  # and img.shape[2] == 3:
            img_cv = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        else:
            img_cv = img
    elif hasattr(img, 'convert'):
        # assume its a PIL.Image, convert to cv format
        img_array = numpy.array(img.convert('RGB'))
        img_cv = img_array[:, :, ::-1].copy()  # -1 does RGB -> BGR
        if grayscale:
            img_cv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    else:
        raise TypeError(f'expected an image filename, OpenCV numpy array, or PIL image, got {img} = {type(img)} which is not supported')
    return img_cv

def imgOnScreen(haystack_frame, needle_images, confidence=0.9):
    """
        在屏幕上查找图片
    :param haystack_frame: 屏幕帧
    :param needle_images: 图片列表
    :param confidence: 置信度
    :param grayscale: 灰度值找图
    :return:
    """
    needle_images = [_load_cv2(needle_image) for needle_image in needle_images]
    haystack_frame = _load_cv2(haystack_frame)
    rs = [_locateAll_opencv(needle_image, haystack_frame, confidence=confidence) for needle_image in needle_images]
    
    # 对每个识别结果进行去重处理
    from AutoScriptor.utils.box import Box
    deduplicated_rs = []
    for boxes in rs:
        if boxes:  # 如果有识别结果
            # 使用Box的去重方法，设置合适的阈值
            deduplicated_boxes = Box.merge_overlapping_boxes(
                boxes, 
                overlap_threshold=0.3,  # 重叠面积超过30%认为重复
                distance_threshold=3     # 距离小于3像素认为重复
            )
            deduplicated_rs.append(deduplicated_boxes)
        else:
            deduplicated_rs.append([])
    
    return deduplicated_rs


# 新的基于金字塔的多尺度匹配实现
def _locateAll_opencv(needleImage, haystackImage, limit=10000, region=None, step=2, confidence=0.9, min_scale=0.8, max_scale=1.2):
    """
    下采样模板与图像后，仅匹配三种 scale：min_scale,1.0,max_scale，加速模板匹配。
    返回所有满足阈值的位置框。
    """
    # 加载灰度图并裁剪区域
    needleGray = _load_cv2(needleImage, True)
    haystackGray = _load_cv2(haystackImage, True)
    if region:
        x0, y0, w0, h0 = region
        haystackGray = haystackGray[y0:y0+h0, x0:x0+w0]
    else:
        x0 = y0 = 0
    # 下采样
    ds = max(2, step)
    hay_ds = haystackGray[::ds, ::ds]
    tpl = needleGray
    tpl_ds = tpl[::ds, ::ds]
    tH, tW = tpl.shape[:2]
    tH_ds, tW_ds = tpl_ds.shape[:2]
    # 关键尺度
    scales = [1.0]
    if min_scale != 1.0:
        scales.append(min_scale)
    if max_scale != 1.0 and max_scale != min_scale:
        scales.append(max_scale)
    boxes = []
    for scale in scales:
        w_s = int(tW_ds * scale)
        h_s = int(tH_ds * scale)
        if w_s < 1 or h_s < 1 or w_s > hay_ds.shape[1] or h_s > hay_ds.shape[0]:
            continue
        tpl_s = cv2.resize(tpl_ds, (w_s, h_s), interpolation=cv2.INTER_AREA)
        res = cv2.matchTemplate(hay_ds, tpl_s, cv2.TM_CCOEFF_NORMED)
        ys, xs = numpy.where(res >= confidence)
        for y, x in zip(ys, xs):
            real_x = x * ds + x0
            real_y = y * ds + y0
            boxes.append(Box(real_x, real_y, tW, tH))
            if len(boxes) >= limit:
                return boxes
    return boxes
