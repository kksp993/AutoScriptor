from sre_parse import NEGATE
import cv2
from logzero import logger
from AutoScriptor import *
from AutoScriptor.recognition.ocr_rec import ocr, ocr_for_box
from ZmxyOL.nav import *
import traceback

Confirm = (T("确定",box=Box(0,900,720,380)), T("确认",box=Box(0,900,720,380)),T("提交",box=Box(0,900,720,380)))
WRONG_MSG=(T("请认真",box=Box(0,0,720,1280)),T("返回",box=Box(0,0,720,1280)))
RETRY_BTN=(T("返回",box=Box(0,0,720,1280)))
CNT_BTN=(T("继续",box=Box(0,0,720,1280)))
RIGHT_MSG=(T("答对了",box=Box(0,0,720,1280)))
TEST_IDF=(
    T("测试",box=Box(0,0,720,1280)),
    T("多选",box=Box(0,0,720,1280)),
    T("单选",box=Box(0,0,720,1280)),
    T("选项",box=Box(0,0,720,1280)),
    *Confirm
)
NEXT_IDF=(
    T("下一课",box=Box(0,0,720,1280)),
    T("下一",box=Box(0,900,720,380)),
    T("开始学习",box=Box(0,0,720,1280)),
    T("点击学习",box=Box(0,0,720,1280)),
    T("开始",box=Box(0,0,720,1280)),
    T("继续",box=Box(0,0,720,1280)),
)

Choices_Loop ={
    1:[["A"]],
    2:[["A"],["B"],["A","B"]],
    3:[["A"],["B"],["C"],["A","B","C"],["A","B"],["A","C"],["B","C"]],
    4:[["A"],["B"],["C"],["D"],["A","B","C","D"],["A","B","C"],["A","B","D"],["A","C","D"],["B","C","D"],["A","B"],["A","C"],["A","D"],["B","C"],["B","D"],["C","D"]]
}
def test():
    click(T("测试",box=Box(0,0,720,1280)),if_exist=True)
    choices_count = sum(count(locate([T(i,box=Box(0,0,720,1280)) for i in ["A","B","C","D"]])))
    logger.info(f"选择数量: {choices_count}")
    loop = Choices_Loop.get(choices_count,[])
    for choices in loop:
        for i in choices:
            wait_for_appear(Confirm)
            click(T(i,box=Box(0,0,720,1280)),timeout=3)
        sleep(1)
        click(Confirm)
        sleep(1)
        if ui_T(WRONG_MSG) and ui_F(RIGHT_MSG):
            click(RETRY_BTN)
            sleep(2)
            continue
        break
    click(CNT_BTN)
def main_loop():
        bg.add(
            name="学习中",
            identifier=NEXT_IDF,
            callback=lambda: [
                bg.set_signal("Status","学习中"),
                sleep(5)
            ],
            once=False
        )
        bg.add(
            name="测试",
            identifier=TEST_IDF,
            callback=lambda: [
                bg.set_signal("Status","测试"),
                test(),
                bg.set_signal("Status","学习中")
            ],
            once=False
        )
        bg.add(
            name="滑动",
            identifier=T("滑动",box=Box(0,0,720,1280)),
            callback=lambda: [
                bg.set_signal("Status","滑动"),
                sleep(5)
            ],
            once=False
        )
        bg.set_interval(3)
        bg.set_signal("Status","学习中")
        cnt = 0
        while True:
            if bg.signal("Status") == "测试":
                sleep(3)
            elif bg.signal("Status") == "滑动":
                hd = locate(T("滑动",box=Box(0,0,720,1280)),timeout=3)
                swipe(B(hd.center()[0],hd.center()[1]),B(720,hd.center()[1]))
                bg.set_signal("Status","学习中")
            else:
                try:
                    click(NEXT_IDF, timeout=5)
                except Exception as e:
                    click(B(515, 1162))
                    cnt += 1
                    if bg.signal("Status") != "学习中": continue
                    for i in range(5):
                        for j in range(9):
                            click(B(700-i*100,300+j*100,50,50))
                    click(T("返回",box=Box(0,900,720,380)),if_exist=True)
                    if cnt % 5 == 0:
                        swipe(B(250,400),B(525,400)); sleep(1)
                        swipe(B(525,400),B(250,400)); sleep(1)
                        swipe(B(300,200),B(300,1000)); sleep(1)
                        swipe(B(300,1000),B(300,200)); sleep(1)

if __name__ == "__main__":
    try:
        main_loop()
        # print(locate(T("79917",box=Box(0,0,720,1280))))
    except Exception as e:
        traceback.print_exc()
    finally:
        bg.stop()
        exit(0)