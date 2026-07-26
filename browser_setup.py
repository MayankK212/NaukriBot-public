"""
Shared Playwright browser launcher.

Local runs open a real Chrome window (Naukri is friendlier to it).
CI runs (GitHub Actions) must be headless — set env HEADLESS=true. In headless
mode we use bundled Chromium with anti-automation flags and a realistic user
agent / viewport to reduce bot detection.

Residential-IP JUGAAD:
    Naukri (Akamai) blocks datacenter IPs. To scrape from GitHub's cloud, route
    all browser traffic through a residential proxy (e.g. your always-on phone
    running a proxy app, reachable over Tailscale). Set these env vars:

        PROXY_SERVER   = http://<phone-tailscale-ip>:<port>   (or socks5://...)
        PROXY_USERNAME = optional
        PROXY_PASSWORD = optional

    When PROXY_SERVER is unset, no proxy is used (normal local/direct run).
"""

import os

_HEADLESS_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def is_headless():
    return os.getenv("HEADLESS", "false").strip().lower() in ("1", "true", "yes")


def proxy_config():
    """Playwright proxy dict from env, or None if PROXY_SERVER is unset."""
    server = (os.getenv("PROXY_SERVER") or "").strip()
    if not server:
        return None
    cfg = {"server": server}
    user = (os.getenv("PROXY_USERNAME") or "").strip()
    pwd = os.getenv("PROXY_PASSWORD") or ""
    if user:
        cfg["username"] = user
        cfg["password"] = pwd
    return cfg


def launch_browser(playwright):
    """Launches a browser appropriate for the environment (proxy-aware).

    Akamai (Naukri) fingerprints HEADLESS Chromium and blocks it even from a
    residential IP. So the reliable path — local AND in CI — is REAL Google
    Chrome, headed. In CI we run it under Xvfb (virtual display) so 'headed'
    works with no monitor. Set HEADLESS=true only as a last resort.
    """
    proxy = proxy_config()
    if proxy:
        print(f"🌐 Routing browser via proxy: {proxy['server']}")

    # CI (GitHub Actions sets CI=true) needs sandbox flags; harmless locally.
    ci_args = (["--no-sandbox", "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled"]
               if os.getenv("CI") else [])

    if is_headless():
        return playwright.chromium.launch(
            headless=True, proxy=proxy,
            args=["--no-sandbox", "--disable-dev-shm-usage",
                  "--disable-blink-features=AutomationControlled"],
        )
    # Real Google Chrome, headed (visible locally, Xvfb in CI). Least detectable.
    return playwright.chromium.launch(
        headless=False, channel="chrome", proxy=proxy, args=ci_args,
    )


def new_context(browser):
    """Creates a context with a realistic fingerprint when headless."""
    if is_headless():
        return browser.new_context(
            user_agent=_HEADLESS_UA,
            viewport={"width": 1366, "height": 768},
            locale="en-IN",
        )
    return browser.new_context()
