"""Persistent Chrome context. One profile dir per account, never shared."""

from __future__ import annotations

import os
import urllib.request
from pathlib import Path
from typing import Any

from playwright.async_api import BrowserContext, Playwright

from app import egress

ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
]

# Google Payments memuat skrip dialog checkout-nya dari clients2.google.com.
# Sebagian egress (proxy perusahaan / sandbox VM) menolak host itu secara
# kebijakan, sehingga dialog berhenti di "Loading…" selamanya. File yang sama
# disajikan identik lewat host mirror Google Translate; opt-in ini mengambilnya
# dari sana dan menyajikannya ke halaman lewat route intercept lokal.
MIRROR_HOST = "clients2-google-com.translate.goog"


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in ("1", "true", "yes", "on")


async def _mirror_clients2(ctx: BrowserContext) -> None:
    def fetch(url: str) -> tuple[bytes, str]:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.read(), r.headers.get_content_type()

    async def handler(route):  # noqa: ANN001, ANN202
        url = route.request.url
        tail = url.split("clients2.google.com", 1)[1]
        try:
            body, ctype = fetch(f"https://{MIRROR_HOST}{tail}")
            await route.fulfill(status=200, body=body, content_type=ctype)
        except Exception:
            await route.continue_()

    await ctx.route("**://clients2.google.com/**", handler)


async def launch(
    p: Playwright,
    profile_dir: Path,
    *,
    headless: bool = False,
    proxy: dict[str, Any] | None = None,
) -> BrowserContext:
    profile_dir.mkdir(parents=True, exist_ok=True)
    # Egress terbatas (VM / sandbox / proxy perusahaan): Chromium di belakang
    # proxy yang hanya bisa dikonfigurasi dari lingkungan, bukan dari caller.
    # Semua opt-in; tanpa env ini perilaku sama persis seperti sebelumnya.
    if proxy is None:
        proxy = egress.parse(os.environ.get("GAI_BROWSER_PROXY", ""))
    args = list(ARGS)
    if _flag("GAI_NO_SANDBOX"):
        args.append("--no-sandbox")
    ctx = await p.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        channel="chrome",
        headless=headless,
        locale="en-US",
        timezone_id="America/Los_Angeles",
        viewport={"width": 1440, "height": 900},
        proxy=proxy,
        ignore_https_errors=_flag("GAI_IGNORE_CERT_ERRORS"),
        args=args,
    )
    if _flag("GAI_MIRROR_CLIENTS2"):
        await _mirror_clients2(ctx)
    return ctx
