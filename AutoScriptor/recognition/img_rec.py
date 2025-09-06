import cv2
import numpy

from AutoScriptor.utils.box import Box

GRAYSCALE_DEFAULT = True

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


def _locateAll_opencv(needleImage, haystackImage, limit=10000, region=None, step=1, confidence=0.9):
    """
    TODO - rewrite this
        faster but more memory-intensive than pure python
        step 2 skips every other row and column = ~3x faster but prone to miss;
            to compensate, the algorithm automatically reduces the confidence
            threshold by 5% (which helps but will not avoid all misses).
        limitations:
          - OpenCV 3.x & python 3.x not tested
          - RGBA images are treated as RBG (ignores alpha channel)
    """
    confidence = float(confidence)

    needleImage = _load_cv2(needleImage, True)
    needleHeight, needleWidth = needleImage.shape[:2]
    haystackImage = _load_cv2(haystackImage, True)
    cv2.imwrite("needleImage.png", needleImage)
    cv2.imwrite("haystackImage.png", haystackImage)
    if region:
        haystackImage = haystackImage[region[1]: region[1] + region[3], region[0]: region[0] + region[2]]
    else:
        region = (0, 0)  # full image; these values used in the yield statement
    if haystackImage.shape[0] < needleImage.shape[0] or haystackImage.shape[1] < needleImage.shape[1]:
        # avoid semi-cryptic OpenCV error below if bad size
        raise ValueError('needle dimension(s) exceed the haystack image or region dimensions')

    if step == 2:
        confidence *= 0.95
        needleImage = needleImage[::step, ::step]
        haystackImage = haystackImage[::step, ::step]
    else:
        step = 1

    # get all matches at once, credit: https://stackoverflow.com/questions/7670112/finding-a-subimage-inside-a-numpy-image/9253805#9253805
    result = cv2.matchTemplate(haystackImage, needleImage, cv2.TM_CCOEFF_NORMED)
    match_indices = numpy.arange(result.size)[(result > confidence).flatten()]
    matches = numpy.unravel_index(match_indices[:limit], result.shape)

    if len(matches[0]) == 0: return

    # use a generator for API consistency:
    matchx = matches[1] * step + region[0]  # vectorized
    matchy = matches[0] * step + region[1]
    
    return [Box(x, y, needleWidth, needleHeight) for x, y in zip(matchx, matchy)]
