import asyncio
import ipaddress
import socket
from contextlib import suppress
from urllib.parse import urlsplit

from playwright.async_api import Error as PlaywrightError, async_playwright

from app.config import FRONTEND_PORTS


WIDTH, HEIGHT = 1280, 800


def origin(url: str) -> tuple[str, str | None, int | None]:
    parts = urlsplit(url)
    return parts.scheme, parts.hostname, parts.port or {"http": 80, "https": 443}.get(parts.scheme)


class Browser:
    def __init__(self):
        self.driver = None
        self.chromium = None
        self.lock = asyncio.Lock()

    async def context(self):
        async with self.lock:
            if not self.chromium or not self.chromium.is_connected():
                self.driver = self.driver or await async_playwright().start()
                try:
                    self.chromium = await self.driver.chromium.launch(headless=True, chromium_sandbox=True)
                except PlaywrightError as error:
                    if "Executable doesn't exist" in str(error):
                        raise RuntimeError("Chromium is missing. Run python -m playwright install chromium.") from error
                    raise
        return await self.chromium.new_context(
            viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=1,
            accept_downloads=False, service_workers="block",
        )

    async def close(self):
        if self.chromium:
            await self.chromium.close()
        if self.driver:
            await self.driver.stop()


class BrowserSession:
    def __init__(self, publish):
        self.publish = publish
        self.context = self.page = self.cdp = None
        self.frame = None
        self.generation = 0
        self.connect_lock = asyncio.Lock()
        self.resolutions: dict[str, asyncio.Task] = {}

    async def public_host(self, host: str) -> bool:
        async def resolve():
            try:
                addresses = await asyncio.wait_for(
                    asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM), 4,
                )
                return bool(addresses) and all(ipaddress.ip_address(item[4][0]).is_global for item in addresses)
            except (OSError, ValueError, TimeoutError):
                return False

        if host not in self.resolutions:
            if len(self.resolutions) >= 256:
                self.resolutions = {key: task for key, task in self.resolutions.items() if not task.done()}
            self.resolutions[host] = asyncio.create_task(resolve())
        return await asyncio.shield(self.resolutions[host])

    async def open(self, browser: Browser, url: str):
        initial = origin(url)
        local_target = not await self.public_host(initial[1])
        if self.is_workspace(initial):
            raise RuntimeError("Choose a target outside the WebMorph workspace and API.")
        self.context = await browser.context()

        async def restrict(route):
            try:
                destination = origin(route.request.url)
            except ValueError:
                await route.abort()
                return
            scheme, host, port = destination
            if scheme not in {"http", "https"} or not host or self.is_workspace(destination):
                await route.abort()
            elif (local_target and destination == initial) or await self.public_host(host):
                await route.continue_()
            else:
                await route.abort()

        await self.context.route("**/*", restrict)
        if hasattr(self.context, "route_web_socket"):
            async def restrict_socket(websocket):
                scheme, host, port = origin(websocket.url)
                destination = ("https" if scheme == "wss" else "http", host, port)
                if not host or self.is_workspace(destination) or not (
                    (local_target and destination == initial) or await self.public_host(host)
                ):
                    await websocket.close()
                    return
                websocket.connect_to_server()
            await self.context.route_web_socket("**/*", restrict_socket)
        self.page = await self.context.new_page()
        await self.attach()
        await self.page.goto(url, wait_until="domcontentloaded", timeout=18000)
        await self.pulse()

    @staticmethod
    def is_workspace(destination):
        _, host, port = destination
        return host in {"localhost", "127.0.0.1", "::1"} and port in (FRONTEND_PORTS | {8000})

    async def attach(self):
        async with self.connect_lock:
            if self.cdp:
                with suppress(PlaywrightError):
                    await self.cdp.detach()
            self.generation += 1
            generation = self.generation
            cdp = await self.context.new_cdp_session(self.page)
            self.cdp = cdp

            async def recv(event):
                with suppress(PlaywrightError):
                    await cdp.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})
                if self.generation == generation:
                    self.frame = {"data": event["data"], "width": WIDTH, "height": HEIGHT}
                    self.publish("frame", self.frame)

            cdp.on("Page.screencastFrame", recv)
            await cdp.send("Page.startScreencast", {
                "format": "jpeg", "quality": 70, "maxWidth": WIDTH, "maxHeight": HEIGHT,
            })

    async def pulse(self):
        with suppress(PlaywrightError):
            shot = await self.cdp.send("Page.captureScreenshot", {"format": "jpeg", "quality": 70})
            self.frame = {"data": shot["data"], "width": WIDTH, "height": HEIGHT}
            self.publish("frame", self.frame)

    async def switch_popup(self) -> bool:
        if not self.context:
            return False
        pages = [page for page in self.context.pages if not page.is_closed()]
        if pages and pages[-1] != self.page:
            self.page = pages[-1]
            await self.attach()
            return True
        return False

    async def input(self, event):
        await self.switch_popup()
        if event.type == "mouse_click":
            await self.page.mouse.click(event.x, event.y)
        elif event.type == "mouse_wheel":
            await self.page.mouse.move(event.x, event.y)
            await self.page.mouse.wheel(event.delta_x, event.delta_y)
        elif event.type == "key_press" and event.key:
            await self.page.keyboard.press(event.key)
        elif event.type == "type_text":
            await self.page.keyboard.insert_text(event.text)

    async def close(self):
        self.generation += 1
        if self.context:
            await self.context.close()
        for task in self.resolutions.values():
            if not task.done():
                task.cancel()
