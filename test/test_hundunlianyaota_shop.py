"""混沌炼狱塔的妖魄商铺购买逻辑。

抓过的真实事故（用户原话）：任务「没有错误点击，但是该买的东西都没有买」——

* 功绩 / 6级灵玉「可能因为在同一栏漏跑，只买了其中一个」；
* 「限购 3，但是我们可能划动只买 1 个」。

两个都是几何错误，各自独立：

1. 三列价格按钮的左边是 ``503 / 687 / 872``，而原代码写成
   ``502 / 686 / 939``。第三列的 939 是那一列的**中心**而不是左边，于是第三列读到的
   价格框整体右移 67px、落到卡片外；更早的那版还会用「商品名中心 x + 45」再去比阈值，
   第 1 列的产物直接掉进第 2 列的区间——同一行的两个商品读到同一个价格，取舍整个反掉。
2. 价格框是「商品名中心再往下 220px」。这个偏移只在列表**顶行**成立；商品名落到下面
   几行时价格框跑到屏幕外（``Box(939, 658)`` 之类），读不到价格，整件被静默跳过。

离线用归档帧锁住这两条，避免再改回去。归档在 `logs/` 下（不进版本库），没有就跳过。
"""

import importlib
import unittest
from pathlib import Path

import cv2
import numpy as np

import ZmxyOL  # noqa: F401  导入以注册资源根，否则 ui_map 找不到
from AutoScriptor.core.box import Box
from AutoScriptor.recognition.locate import get_box_color
from AutoScriptor.recognition.ocr_rec import ocr_for_box

shop = importlib.import_module("tasks.每日任务.村庄.混沌炼狱塔")

ROOT = Path(__file__).resolve().parents[1]


class PriceButtonColumnTest(unittest.TestCase):
    """商品名 → 价格按钮的列映射。三列都必须落在自己的按钮上。"""

    # 名称中心 x 的实测值（2026-10-07 实机帧 12_down_2：三列商品的名称中心）
    LABEL_CENTERS = ((523, 503), (753, 687), (937, 872))

    def test_label_center_maps_to_its_own_column(self):
        for center_x, expected_left in self.LABEL_CENTERS:
            with self.subTest(center_x=center_x):
                for center_y in (200, 300, 400):
                    button = shop._price_button_of(Box(center_x - 60, center_y, 120, 30))
                    self.assertEqual(
                        button.left, expected_left,
                        f"名称中心 x={center_x} 应当落在按钮列 {expected_left}",
                    )
                    self.assertEqual(button.width, shop.BUY_BUTTON_SIZE[0])
                    self.assertEqual(button.height, shop.BUY_BUTTON_SIZE[1])

    def test_long_and_short_names_in_the_same_column_agree(self):
        """名称长短只改变左右边界，中心 x 稳定——所以按中心判定才是对的。"""
        long_name = shop._price_button_of(Box(673, 320, 320, 30))    # 呼风唤雨·初(拓印本)残卷
        short_name = shop._price_button_of(Box(520, 320, 40, 30))    # 功绩
        self.assertEqual(long_name.left, shop.BUY_BUTTON_LEFTS[1])
        self.assertEqual(short_name.left, shop.BUY_BUTTON_LEFTS[0])

    def test_button_sits_below_the_label(self):
        """按钮在名称下方一整个卡片高度处，不是压在名称上。"""
        name = Box(523, 200, 120, 30)
        button = shop._price_button_of(name)
        self.assertGreater(button.top, name.top + name.height)
        self.assertEqual(
            button.center()[1],
            name.center()[1] + shop.NAME_TO_BUTTON_CENTER_DY,
        )


class PositiveIntTest(unittest.TestCase):
    """价格/余额的解析：夹带杂质就当作没读到，宁可不买也不猜错价格。"""

    def test_plain_digits(self):
        self.assertEqual(shop._positive_int("5000"), 5000)
        self.assertEqual(shop._positive_int(" 330000 "), 330000)
        self.assertEqual(shop._positive_int("1,000"), 1000)

    def test_rejects_noise(self):
        for noisy in (None, "", "裂岳冥窟", "5000妖魄", "x18000", "0/20", "购买数量：1"):
            with self.subTest(text=noisy):
                self.assertIsNone(shop._positive_int(noisy))


class ArchivedFrameTest(unittest.TestCase):
    """用归档真机帧验证：列映射、粉/灰判别、余额读全。"""

    FRAME = ROOT / "logs" / "hdl_debug" / "12_down_2.png"
    TOP_FRAME = ROOT / "logs" / "hdl_debug" / "50_cal.png"

    @classmethod
    def setUpClass(cls):
        if not cls.FRAME.is_file():
            raise unittest.SkipTest(f"缺少归档帧 {cls.FRAME}")
        cls.frame = cv2.imdecode(np.fromfile(str(cls.FRAME), np.uint8), cv2.IMREAD_COLOR)
        if cls.frame is None:
            raise unittest.SkipTest("归档帧读取失败")

    def _button_for(self, name):
        from AutoScriptor.recognition.locate import locate_on_screen

        hits = locate_on_screen(
            self.frame, [name], 0.8, [shop.SHOP_NAME_AREA], [None],
        )[0]
        self.assertTrue(hits, f"归档帧里没找到 {name}")
        return shop._price_button_of(Box(*hits[0]))

    def test_buyable_and_sold_out_columns_are_distinguished(self):
        """这一帧：列 1 有额度（粉红 50000），列 2/3 已兑完（灰 30000/50000）。"""
        cases = (
            ("禁神乐曲·上", 50000, True),
            ("玄天魔刃神灵丹碎片", 30000, False),
            ("绝代风华之息", 50000, False),
        )
        for name, price, has_quota in cases:
            with self.subTest(name=name):
                button = self._button_for(name)
                self.assertTrue(
                    button.top + button.height <= shop.SHOP_CONTENT_BOTTOM,
                    f"{name} 的按钮应当完整落在内容区里：{button}",
                )
                self.assertEqual(
                    shop._positive_int(ocr_for_box(self.frame, button)), price,
                )
                actual_quota = "红色" in (get_box_color(self.frame, button) or "")
                self.assertEqual(
                    actual_quota, has_quota,
                    f"{name} 的额度判别错误（按钮 {button}，颜色 "
                    f"{get_box_color(self.frame, button)!r}）",
                )

    def test_balance_box_reads_the_whole_number(self):
        """余额框必须读全：旧框只有 82px 宽，330000 会被截成 33000。"""
        read = ocr_for_box(self.frame, shop.BALANCE_BOX)
        self.assertEqual(
            shop._positive_int(read), 330000,
            f"余额读到 {read!r}；框太窄会截断数字，买得起判断会跟着错",
        )

    def test_sold_out_cards_are_recognised_on_the_bottom_screen(self):
        """列表底部那张 6级灵玉 是 2/2（已买满），必须判成「没有额度」。"""
        if not self.TOP_FRAME.is_file():
            raise unittest.SkipTest(f"缺少归档帧 {self.TOP_FRAME}")
        frame = cv2.imdecode(np.fromfile(str(self.TOP_FRAME), np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise unittest.SkipTest("归档帧读取失败")
        from AutoScriptor.recognition.locate import locate_on_screen

        hits = locate_on_screen(frame, ["6级灵玉"], 0.8, [shop.SHOP_NAME_AREA], [None])[0]
        self.assertTrue(hits, "底部帧里没找到 6级灵玉")
        button = shop._price_button_of(Box(*hits[0]))
        self.assertNotIn(
            "红色", get_box_color(frame, button) or "",
            "6级灵玉 已经是 2/2，按钮应当是灰的；判成可买会重复下单",
        )


if __name__ == "__main__":
    unittest.main()
