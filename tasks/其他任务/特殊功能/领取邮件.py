"""领取村庄邮件奖励。"""

from time import monotonic

from AutoScriptor import *
from ZmxyOL import *


def _is_single_mail_page() -> bool:
    matches = locate(
        (T("1/1"), T("1 / 1")), assure_stable=False, is_simplify=False,
    ) or []
    for page_boxes in matches:
        for page_box in page_boxes or []:
            # T 是子串匹配；扩大区域读取完整页码，不能把 1/10 当作 1/1。
            page_text = extract_info(
                B(page_box.margin()), ensure_not_empty=False,
                max_retries=1, save_screenshot=False,
            )
            if isinstance(page_text, str) and "".join(page_text.split()) == "1/1":
                return True
    return False


@register_task(
    description="在村庄循环领取邮件，页码为 1/1 后再补领 5 次。",
    debug=True,
    ensure_in="村庄",
)
def task(claim_interval: float = 3, timeout: float = 600):
    """claim_interval 是每次领取后的等待秒数；timeout 是领取循环的总时限。"""
    if claim_interval <= 0 or timeout <= 0:
        raise ValueError("领取间隔和总时限必须大于 0")
    ensure_in("村庄")
    click(T("邮件", box=Box(33, 45, 868, 74).margin()))
    claim_target = T("键领取", box=Box(532, 551, 214, 90).margin())
    single_page_claims = 0
    started_at = monotonic()
    while monotonic() - started_at < timeout:
        single_page = _is_single_mail_page()
        if not single_page:
            single_page_claims = 0
        elif single_page_claims == 5:
            logger.info("邮件仍为 1/1，已补领 5 次，结束领取")
            click(I("邮件-关闭"))
            return

        click(claim_target)
        sleep(claim_interval)
        if single_page:
            single_page_claims += 1
            logger.info("邮件页码为 1/1，补领 %d/5", single_page_claims)

    raise RuntimeError(f"领取邮件超过 {timeout} 秒，未确认 1/1 后完成 5 次补领")
