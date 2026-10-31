"""Read an AFR subscriber article using the account's normal browser login.

Requires Google Chrome and environment variables AFR_USER / AFR_PASSWORD.
Python: content = fetch_afr_article(url)
CLI: python -m services.afr_article --url 'https://www.afr.com/...'
Cookies stay in memory and are discarded when the browser closes.
"""
import argparse
import os
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright, TimeoutError as BrowserTimeout


# AFR currently serves both its standard article template (body under
# <article>) and a feature template (body under <main>, with no <article>).
# Keep the suffix match because the class prefix is generated per build.
_BODY = 'article [class$="-articleBody"], main [class$="-articleBody"]'


def _body_text(page):
    # Read the rendered article only; exclude image captions and related cards.
    return page.locator(_BODY).evaluate_all(r"""bodies => bodies.flatMap(body =>
        Array.from(body.querySelectorAll('p, h2, h3, li')).filter(el =>
            !el.closest('figure, aside, nav, [data-article-body-exclude="true"]') &&
            (el.parentElement === body || el.closest('ul, ol')) &&
            el.getClientRects().length
        ).map(el => el.innerText.trim()).filter(Boolean)
    ).join('\n\n')""")


def fetch_afr_article(url, timeout=60):
    """Return article body text with paragraph breaks, or raise on login failure.

    Uses the subscriber paywall's Log in button. A failed login never returns
    the preview paragraphs as though they were the complete article.
    timeout is the maximum wait in seconds for each page/login stage.
    """
    parsed = urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ('afr.com', 'www.afr.com'):
        raise ValueError('请输入 https://www.afr.com 的文章 URL')
    username = os.environ.get('AFR_USER')
    password = os.environ.get('AFR_PASSWORD')
    if not username or not password:
        raise ValueError('请设置 AFR_USER 和 AFR_PASSWORD 环境变量')

    with sync_playwright() as p:
        browser = p.chromium.launch(channel='chrome', headless=True)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(timeout * 1000)
            page.goto(url, wait_until='domcontentloaded')
            page.locator(_BODY).first.wait_for(state='visible')
            preview = _body_text(page)

            deadline = time.monotonic() + timeout
            login_button = None
            while time.monotonic() < deadline:
                for frame in page.frames:
                    if urlparse(frame.url).hostname != 'buy-au.piano.io':
                        continue
                    try:
                        if frame.get_by_text('Already a subscriber?', exact=False).count():
                            buttons = frame.get_by_role('button', name='Log in', exact=True)
                            for index in range(buttons.count()):
                                candidate = buttons.nth(index)
                                if candidate.is_visible():
                                    login_button = candidate
                                    break
                            if login_button is not None:
                                break
                    except BrowserTimeout:
                        continue
                if login_button is not None:
                    break
                page.wait_for_timeout(500)
            if login_button is None:
                raise RuntimeError('未找到 AFR 订阅者登录入口，未返回可能不完整的正文')
            login_button.click()
            page.locator('#loginEmail').wait_for(state='visible')
            if urlparse(page.url).hostname != 'www.afr.com':
                raise RuntimeError('登录页面已离开 AFR，未提交账号密码')
            page.locator('#loginEmail').fill(username)
            page.locator('#loginPassword').fill(password)
            page.get_by_role('button', name='Log in', exact=True).last.click()
            page.locator('#loginEmail').wait_for(state='hidden')
            page.get_by_role('button', name='Log in', exact=True).first.wait_for(state='hidden')

            # Reload after the site has applied the subscriber session.
            page.goto(url, wait_until='domcontentloaded')
            page.locator(_BODY).first.wait_for(state='visible')
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                content = _body_text(page)
                if len(content) > len(preview) and not page.get_by_role(
                    'button', name='Log in', exact=True
                ).count():
                    return content
                page.wait_for_timeout(500)
            raise RuntimeError('AFR 登录后正文未解锁，请检查账号订阅状态')
        except BrowserTimeout as exc:
            raise RuntimeError('AFR 页面或登录超时，未返回不完整正文') from exc
        finally:
            browser.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='AFR 文章网址')
    args = parser.parse_args()
    print(fetch_afr_article(args.url))
