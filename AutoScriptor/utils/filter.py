from typing import Callable, Union
import questionary


def fake_fn(x, *args, **kwargs): return x


def _validate(fn: Callable, error_msg: str = "输入不合法", fn_ahead: Callable = None, fn_after: Callable = None):
    # 前后处理默认 fake_fn
    fn_ahead, fn_after = fn_ahead or fake_fn, fn_after or fake_fn

    def wrapper(*args, **kwargs):
        x = args[0] if args else None
        try:
            y = wrapper.fn_ahead(x)
            assert wrapper.fn(y)
            wrapper.fn_after(y)
        except:
            return f"【{y}】：{wrapper.error_msg}"
        return True

    # 绑定属性
    wrapper.fn, wrapper.error_msg, wrapper.fn_ahead, wrapper.fn_after = fn, error_msg, fn_ahead, fn_after

    # 动态组合验证器，支持 and_（与）和 or_（或）组合，并保证链式调用时优先级可控
    def _make_and(this, other):
        def combined_and(*a_, **k_):
            res = this(*a_, **k_)
            if res is not True:
                return res
            return other(*a_, **k_)
        # 在 and 结果上继续支持 and_ 和 or_
        combined_and.and_ = lambda other, this=combined_and: _make_and(this, other)
        combined_and.or_ = lambda other, this=combined_and: _make_or(this, other)
        combined_and.append = lambda ahead=None, after=None: (setattr(combined_and, 'fn_ahead', ahead) if ahead else None) or (setattr(combined_and, 'fn_after', after) if after else None) or combined_and

        return combined_and

    def _make_or(this, other):
        def combined_or(*a_, **k_):
            res1 = this(*a_, **k_)
            if res1 is True:
                return True
            res2 = other(*a_, **k_)
            if res2 is True:
                return True
            # 两者都失败时，返回第一个错误信息
            return res1
        # 在 or 结果上继续支持 and_ 和 or_
        combined_or.and_ = lambda other, this=combined_or: _make_and(this, other)
        combined_or.or_ = lambda other, this=combined_or: _make_or(this, other)
        combined_or.append = lambda ahead=None, after=None: (setattr(combined_or, 'fn_ahead', ahead) if ahead else None) or (setattr(combined_or, 'fn_after', after) if after else None) or combined_or
        return combined_or

    # 对外暴露 and_（与）和 or_（或）组合接口
    wrapper.and_ = lambda other, s=wrapper: _make_and(s, other)
    wrapper.or_ = lambda other, s=wrapper: _make_or(s, other)
    # 更新前后处理
    wrapper.append = lambda ahead=None, after=None: (setattr(wrapper, 'fn_ahead', ahead) if ahead else None) or (setattr(wrapper, 'fn_after', after) if after else None) or wrapper
    return wrapper


AT_LEAST_ONE_VALIDATE = _validate(lambda x: len(x) > 0, "请选择至少1个选项")
DIGIT_VALIDATE = _validate(lambda x: x.isdigit(), "请选择数字")
POINT_2D_VALIDATE = _validate(lambda x: x.count(",") == 1 and x.split(",")[0].strip().isdigit() and x.split(",")[1].strip().isdigit(), "请选择坐标")
BOX_2D_VALIDATE = _validate(lambda x: x.count(",") == 3 and x.split(",")[0].strip().isdigit() and x.split(",")[1].strip().isdigit() and x.split(",")[2].strip().isdigit() and x.split(",")[3].strip().isdigit(), "请选择left,top,width,height")
def N_VALIDATE(n: int): return _validate(lambda x: len(x) == n, f"请选择{n}个选项")
def NO_MORE_THAN_N_VALIDATE(n: int): return _validate(lambda x: len(x) <= n, f"请选择至多{n}个选项")
def BETW_AB_VALIDATE(a: int, b: int): return _validate(lambda x: a <= len(x) <= b, f"请选择{a}到{b}之间的选项")
def DIGIT_BETW_AB_VALIDATE(a: int, b: int): return _validate(lambda x: x.isdigit() and a <= int(x) <= b, f"请选择{a}到{b}之间的数字")


def POINT_2D_BETW_AB_VALIDATE(w_a: int, w_b: int, h_a: int, h_b: int):
    return POINT_2D_VALIDATE \
        .and_(DIGIT_BETW_AB_VALIDATE(w_a, w_b).append(lambda x: x.split(",")[0].strip())) \
        .and_(DIGIT_BETW_AB_VALIDATE(h_a, h_b).append(lambda x: x.split(",")[1].strip()))


def BOX_2D_BETW_AB_VALIDATE(w_a: int, w_b: int, h_a: int, h_b: int):
    # 校验左上角 (x, y) 和右下角 (x+width, y+height) 均在指定范围内
    return BOX_2D_VALIDATE \
        .and_(DIGIT_BETW_AB_VALIDATE(w_a, w_b).append(lambda x: x.split(",")[0].strip())) \
        .and_(DIGIT_BETW_AB_VALIDATE(h_a, h_b).append(lambda x: x.split(",")[1].strip())) \
        .and_(DIGIT_BETW_AB_VALIDATE(w_a, w_b).append(lambda x: str(int(x.split(",")[0].strip()) + int(x.split(",")[2].strip())))) \
        .and_(DIGIT_BETW_AB_VALIDATE(h_a, h_b).append(lambda x: str(int(x.split(",")[1].strip()) + int(x.split(",")[3].strip()))))


def get_selected_columns(avail_cols, pre_checked_cols=[], validate_fn=lambda x: True, n=-1, prompt=None):
    validate_fn = _validate(lambda x: validate_fn(x)) if not hasattr(validate_fn, "and_") else validate_fn
    assert avail_cols, "avail_cols不能为空"
    choices = [questionary.Choice(title=col, value=col, checked=col in pre_checked_cols) for col in avail_cols]
    prompt = prompt or f"请选择{n}个选项:" if n != -1 else "请选择:" if prompt is None else prompt
    return questionary.checkbox(
        prompt, choices=choices, use_search_filter=True, use_jk_keys=False,
        validate=validate_fn.and_(N_VALIDATE(n).or_(lambda x: n == -1))
    ).ask()


def get_multi_select(
    question_dict,
    distinct=True,
    avail_cols=None
):
    assert avail_cols, "avail_cols不能为空"
    selected_dict = {}
    for i, (tag, n) in enumerate(question_dict.items()):
        selected_dict[tag] = get_selected_columns(avail_cols, prompt=f"{i+1}. 请选择{tag}的内容：", n=n)
        avail_cols = [e for e in avail_cols if e not in selected_dict[tag]] if distinct else avail_cols
    return list(selected_dict.values())


if __name__ == "__main__":
    # s = questionary.text(
    #     message="请输入点击坐标(x, y):",
    #     default="0,0",
    #     validate=POINT_2D_BETW_AB_VALIDATE(0, 1280, 0, 720)
    # ).ask()
    # print(s)
    s = questionary.text(
        message="请输入点击Box(x, y, width, height):",
        default="0,0,0,0",
        validate=BOX_2D_BETW_AB_VALIDATE(0, 1280, 0, 720)
        # validate=BOX_2D_VALIDATE
    ).ask()
    print(s)
