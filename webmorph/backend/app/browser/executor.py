import asyncio
import json
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Error as PlaywrightError, Locator

from app.agent.scout import Target, normalize
from app.browser.distiller import Element
from app.models.schemas import Value


class ActionError(Exception):
    pass


DOM_STABILITY = r"""
() => new Promise(resolve => {
  let quiet;
  const end = () => { clearTimeout(quiet); clearTimeout(max); observer.disconnect(); resolve(); };
  const observer = new MutationObserver(() => { clearTimeout(quiet); quiet = setTimeout(end, 145); });
  observer.observe(document.documentElement, {subtree: true, childList: true, attributes: true, characterData: true});
  const max = setTimeout(end, 1000);
  quiet = setTimeout(end, 145);
})
"""


async def settle(page, *, after_click=False):
    try:
        async with asyncio.timeout(3.8):
            if after_click:
                await asyncio.sleep(0.22)
                await page.wait_for_load_state("domcontentloaded", timeout=1600)
                # Quiet documents usually need only one short window. SPA mutation bursts reset it.
            await page.evaluate(DOM_STABILITY)
    except (TimeoutError, PlaywrightError):
        pass


@dataclass
class Applied:
    action: str
    strategy: str
    verified: bool
    value: Value = None


def candidates(element: Element):
    scope = element.frame
    if element["wm_id"]:
        yield "DOM index", scope.locator(f'[data-wm-id="{element["wm_id"]}"]'), True
    if element.label:
        yield "Accessible label", scope.get_by_label(element.label, exact=True), False
        roles = {
            "button": "button", "a": "link", "textarea": "textbox", "select": "combobox",
            "checkbox": "checkbox", "radio": "radio", "submit": "button", "text": "textbox",
            "email": "textbox", "tel": "textbox",
        }
        role = element["role"] or roles.get(element["type"]) or roles.get(element["tag"])
        if role:
            yield "Role and name", scope.get_by_role(role, name=element.label, exact=True), False
    for attribute in ("id", "name"):
        if element[attribute]:
            yield f"HTML {attribute}", scope.locator(f'[{attribute}={json.dumps(element[attribute], ensure_ascii=False)}]'), False


async def resolve(element: Element, skip=()) -> tuple[str, Locator]:
    for strategy, locator, primary in candidates(element):
        if strategy in skip:
            continue
        try:
            if await locator.count() != 1 or not await locator.is_visible() or not await locator.is_enabled(timeout=700):
                continue
            if primary and not await locator.evaluate(
                "(el, args) => window.__webmorphIndex?.epoch === args.epoch && el.tagName.toLowerCase() === args.tag "
                "&& (el.getAttribute('name') || '') === args.name",
                {"epoch": element.epoch, "tag": element["tag"], "name": element["name"]}, timeout=700,
            ):
                continue
            return strategy, locator
        except PlaywrightError:
            continue
    raise ActionError("The field or control moved or became unavailable on the website.")


async def highlight(locator: Locator, session, label: str):
    await locator.scroll_into_view_if_needed(timeout=1300)
    await locator.evaluate("""el => {
      const outline = el.style.outline, offset = el.style.outlineOffset;
      el.style.outline = '3px solid #22d3ee'; el.style.outlineOffset = '2px';
      setTimeout(() => {
        if (el.style.outlineOffset === '2px') { el.style.outline = outline; el.style.outlineOffset = offset; }
      }, 650);
    }""", timeout=850)
    if box := await locator.bounding_box(timeout=850):
        session.publish("target", {"label": label, **box})


async def boolean(locator: Locator, custom: bool) -> bool:
    return await locator.get_attribute("aria-checked", timeout=700) == "true" if custom else await locator.is_checked(timeout=800)


async def set_text(locator: Locator, value: str, page, editable=False):
    try:
        await locator.fill(value, timeout=1450)
    except PlaywrightError:
        if not await locator.is_editable(timeout=700):
            raise
        await locator.click(timeout=1050)
        await page.keyboard.press("ControlOrMeta+A")
        await page.keyboard.press("Backspace")
        await page.keyboard.insert_text(value)
    await locator.dispatch_event("change", timeout=850)
    await locator.blur(timeout=850)


async def custom_select(locator, element, choice):
    frame = element.frame
    if element["role"] != "listbox" and await locator.get_attribute("aria-expanded", timeout=700) != "true":
        await locator.click(timeout=1200)
    option = frame.get_by_role("option", name=choice, exact=True)
    if not await option.count():
        option = frame.get_by_text(choice, exact=True)
    if await option.count() != 1:
        raise ActionError("The website did not expose a unique matching dropdown option.")
    await option.click(timeout=1450)
    return option


async def verify_custom(locator, option, answer, choice):
    if await option.count() == 1 and await option.get_attribute("aria-selected", timeout=750) == "true":
        return True
    readback = await locator.evaluate("(el) => el.value || el.getAttribute('aria-valuetext') || el.innerText", timeout=800)
    if normalize(str(readback)) in {normalize(answer), normalize(choice)}:
        return True
    if not await locator.is_visible() or not readback:
        return False
    active = await locator.get_attribute("aria-activedescendant", timeout=750)
    return bool(active and await option.count() == 1 and await option.get_attribute("id", timeout=750) == active)


async def apply(session, target: Target, answer: Value, files: dict[str, Path]) -> Applied:
    spec = target.spec
    element = target.element
    if spec.kind == "radio":
        match = [e for e in target.elements if (e["current_value"] or e.label) == answer]
        if len(match) != 1:
            raise ActionError("Choose a radio option that is still on the website.")
        element = match[0]
    strategies = []
    while True:
        strategy, locator = await resolve(element, strategies)
        strategies.append(strategy)
        try:
            await highlight(locator, session, spec.label)
        except PlaywrightError:
            continue
        break

    action, readback, verified = "fill", answer, False
    try:
        if spec.kind in {"checkbox", "radio"}:
            action = "check"
            expected = answer is True if spec.kind == "checkbox" else True
            custom = element["tag"] != "input"
            if custom:
                if await boolean(locator, True) != expected:
                    await locator.click(timeout=1600)
            else:
                await locator.set_checked(expected, timeout=1800)
            await settle(session.page)
            observed = await boolean(locator, custom)
            verified = observed == expected
            readback = answer if spec.kind == "radio" and observed else observed
        elif spec.kind == "select":
            action = "select"
            await locator.select_option(value=answer, timeout=1700)
            await settle(session.page)
            if spec.multiple:
                readback = await locator.evaluate("(el) => Array.from(el.selectedOptions, item => item.value)", timeout=750)
                verified = set(readback) == set(answer if isinstance(answer, list) else [answer])
            else:
                readback = await locator.input_value(timeout=850)
                verified = readback == answer
        elif spec.kind == "combobox":
            action = "select"
            choice = next((option.label for option in spec.options if option.value == answer), str(answer))
            if element["tag"] == "input" and not spec.options:
                await set_text(locator, str(answer), session.page)
            option = await custom_select(locator, element, choice)
            await settle(session.page)
            verified = await verify_custom(locator, option, str(answer), choice)
        elif spec.kind == "file":
            action = "upload"
            tokens = answer if isinstance(answer, list) else [answer]
            if not tokens or any(token not in files for token in tokens):
                raise ActionError("Upload the file for this run before continuing.")
            paths = [files[token] for token in tokens]
            await locator.set_input_files(paths, timeout=2000)
            await settle(session.page)
            names = await locator.evaluate("(el) => Array.from(el.files, file => file.name)", timeout=850)
            readback = names if spec.multiple else (names[0] if names else "")
            verified = names == [path.name for path in paths]
        else:
            value = "" if answer is None else str(answer)
            if spec.kind in {"range", "color"}:
                await locator.evaluate("""(el, value) => {
                  Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set.call(el, value);
                  el.dispatchEvent(new Event('input', { bubbles: true, composed: true }));
                  el.dispatchEvent(new Event('change', { bubbles: true }));
                }""", value, timeout=950)
            else:
                await set_text(locator, value, session.page)
            await settle(session.page)
            readback = await locator.evaluate("(el) => el.isContentEditable ? el.innerText : el.value", timeout=850)
            verified = readback == value
            if spec.kind == "number" and not verified:
                with suppress(ValueError, TypeError):
                    verified = float(readback) == float(value)
    except PlaywrightError as error:
        raise ActionError("The website did not accept or retain the supplied answer.") from error
    return Applied(action, strategy, verified, readback)


async def prepare_click(session, element: Element):
    strategy, locator = await resolve(element)
    try:
        await highlight(locator, session, element.label)
        handle = await locator.element_handle(timeout=900)
        if handle is None:
            raise ActionError("The website control moved before it could be activated.")
        await handle.click(trial=True, timeout=1450)
    except PlaywrightError as error:
        raise ActionError("The website control is covered, blocked, or no longer available.") from error
    return strategy, handle


async def click(session, handle):
    try:
        # This action has side effects. An ambiguous timeout must never produce a retry.
        await handle.click(timeout=2200)
        await settle(session.page, after_click=True)
        await session.switch_popup()
    except PlaywrightError as error:
        raise ActionError("Click outcome is uncertain. Inspect the live website before proceeding.") from error
    finally:
        with suppress(PlaywrightError):
            await handle.dispose()
