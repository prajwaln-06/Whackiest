import hashlib
import json
import re
from dataclasses import dataclass

from playwright.async_api import Error as PlaywrightError, Frame


INSPECT = r"""
() => {
  const matches = 'input:not([type=hidden]),textarea,select,button,a[href],[role=button],[role=combobox],[role=checkbox],[role=radio],[role=listbox],[contenteditable=true],[role=textbox]';
  const visible = e => {
    if (!e || !e.getClientRects().length || e.closest('[hidden],[aria-hidden=true],[inert]')) return false;
    const style = getComputedStyle(e);
    return style.visibility === 'visible' && style.display !== 'none';
  };
  const tidy = (s, limit = 250) => (s || '').replace(/\s+/g, ' ').trim().slice(0, limit);
  const text = e => tidy(e?.innerText ?? e?.textContent);
  const ids = (e, attr) => (e.getAttribute(attr) || '').split(/\s+/).filter(Boolean)
    .map(id => e.getRootNode().getElementById(id)).filter(Boolean);
  const labelFor = e => {
    const labelled = ids(e, 'aria-labelledby').map(text).join(' ');
    const htmlLabel = Array.from(e.labels || []).map(text).join(' ') || text(e.closest('label'));
    const preceding = e.previousElementSibling;
    const precedingText = e.previousSibling?.nodeType === 3 ? e.previousSibling.textContent : '';
    const guess = text(preceding?.matches('label,span,strong,b') ? preceding : null) || tidy(precedingText, 100);
    const buttonText = e.matches('button,a,[role=button]') ? text(e) :
      e.matches('input[type=button],input[type=submit],input[type=reset],input[type=image]') ? e.value || e.alt : '';
    return tidy(labelled || e.getAttribute('aria-label') || htmlLabel ||
      buttonText || guess || e.getAttribute('title') || e.placeholder);
  };
  const option = e => ({
    label: text(e),
    value: e.tagName === 'OPTION' ? e.value : e.getAttribute('data-value') || e.getAttribute('value') || text(e),
    disabled: e.disabled || e.getAttribute('aria-disabled') === 'true',
  });
  const roots = [document];
  for (const root of roots) for (const node of root.querySelectorAll('*')) if (node.shadowRoot) roots.push(node.shadowRoot);
  const find = selector => roots.flatMap(root => [...root.querySelectorAll(selector)]);
  if (!window.__webmorphIndex) {
    window.__webmorphIndex = {map: new WeakMap(), invalid: new WeakSet(), next: 0, epoch: Math.random().toString(36).slice(2, 9)};
    document.addEventListener('invalid', event => window.__webmorphIndex.invalid.add(event.target), true);
  }
  const memory = window.__webmorphIndex;
  const elements = [];
  const interactive = find(matches).filter(visible);
  for (const e of interactive.slice(0, 240)) {
    if (!memory.map.has(e)) memory.map.set(e, 'wm_' + memory.next++);
    const wmId = memory.map.get(e);
    if (e.getAttribute('data-wm-id') !== wmId) e.setAttribute('data-wm-id', wmId);
    const bounds = e.getBoundingClientRect();
    const tag = e.tagName.toLowerCase();
    const type = e.getAttribute('type') || (tag === 'button' ? e.type : '');
    const role = e.getAttribute('role') || '';
    const label = labelFor(e);
    const fieldset = e.closest('fieldset,[role=radiogroup],[role=group]');
    const groupText = fieldset && (text(fieldset.querySelector(':scope > legend')) || labelFor(fieldset));
    const menus = [...ids(e, 'aria-controls'), ...ids(e, 'aria-owns')];
    const custom = menus.flatMap(m => [...m.querySelectorAll('[role=option],option')]);
    const native = tag === 'select' ? [...e.options] : [];
    const siblings = type === 'radio' && e.name ? interactive.filter(item =>
      item.type === 'radio' && item.name === e.name && item.form === e.form) : [];
    const options = siblings.length
      ? siblings.map(item => ({label: labelFor(item), value: item.value, disabled: item.disabled}))
      : [...new Set([...native, ...custom, ...e.querySelectorAll('[role=option]')])].map(option);
    const described = ids(e, 'aria-describedby').map(text).join(' ');
    const help = described || text(e.parentElement?.querySelector(':scope > small,:scope > .hint,:scope > .help-text'));
    const checked = typeof e.checked === 'boolean' ? e.checked : e.getAttribute('aria-checked') === 'true';
    let value = e.value ?? (e.isContentEditable ? e.innerText : '');
    if (role === 'combobox' && tag !== 'select') {
      const selected = custom.find(item => item.getAttribute('aria-selected') === 'true');
      value = selected && e.getAttribute('aria-expanded') !== 'true' ? option(selected).value : value || text(e);
      if (/^(?:[-–—\s]*(?:select|choose|pick)[^a-z0-9]*|[-–—\s]+)$/i.test(value) || /^(select|choose|pick)\b.*[.…]$/i.test(value)) value = '';
    }
    if (tag === 'select' && e.multiple) value = Array.from(e.selectedOptions, item => item.value);
    if (type === 'password' || e.autocomplete === 'one-time-code' ||
        /\botp\b|one[ _-]time[ _-]code|verification[ _-]code|authenticator[ _-]code/i.test([e.name, e.id, label].join(' '))) value = '';
    if (type === 'file') value = Array.from(e.files || [], file => file.name);
    const parentForm = e.form || e.closest('form');
    const explicitInvalid = e.getAttribute('aria-invalid') === 'true';
    elements.push({
      wm_id: wmId, tag, type, role, name: tidy(e.name), id: e.id, label_text: label,
      aria_label: tidy(e.getAttribute('aria-label')), placeholder: tidy(e.placeholder),
      nearby_help_text: tidy(help, 400), legend: groupText || '', options: options.slice(0, 120),
      current_value: Array.isArray(value) ? value.slice(0, 30) : String(value).slice(0, 1000),
      checked, required: !!(e.required || e.getAttribute('aria-required') === 'true' || fieldset?.getAttribute('aria-required') === 'true' ||
        /(?:\*|[(]required[)])$/i.test(label)),
      disabled: e.matches(':disabled') || e.getAttribute('aria-disabled') === 'true',
      readonly: !!e.readOnly || e.getAttribute('aria-readonly') === 'true',
      visible: true, multiple: !!e.multiple, accept: e.accept || '', autocomplete: e.autocomplete || '',
      minimum: e.min || '', maximum: e.max || '', pattern: e.pattern || '', maxlength: e.maxLength >= 0 ? e.maxLength : null,
      step: e.getAttribute('step') || '', href: e.getAttribute('href') || '', form_key: Array.from(document.forms).indexOf(parentForm),
      form_method: e.getAttribute('formmethod') || parentForm?.getAttribute('method') || '',
      validation: explicitInvalid || (e.validity && !e.validity.valid && (memory.invalid.has(e) ||
        (typeof value === 'string' && value && !['checkbox', 'radio'].includes(type)))) ?
        tidy(ids(e, 'aria-errormessage').map(text).join(' ') || e.validationMessage || help || 'The site marked this value invalid.') : '',
      bbox: {x: bounds.x, y: bounds.y, width: bounds.width, height: bounds.height},
    });
  }
  const headings = find('h1,h2,h3,h4,[role=heading],legend').filter(visible).map(text).filter(Boolean).slice(0, 20);
  const notices = find('p,li,small,[role=alert],[role=status],[role=note],summary,.notice,.alert,.error,[aria-live]').filter(visible)
    .filter(e => !e.matches('nav *,footer *,aside *')).map(e => tidy(e.innerText, 550)).filter(Boolean);
  const priority = /eligib|deadline|required|must |minimum|maximum|document|before you|warning|reference|receipt|verification|certif|consent|step\s+\d/i;
  const unique = [...new Set(notices)];
  const ordered = [...unique.filter(t => priority.test(t)), ...unique.filter(t => !priority.test(t))];
  const alerts = find('[role=alert],[aria-invalid=true],.validation-error,.field-error,.error-message').filter(visible).map(text).filter(Boolean);
  const humanMarker = find('iframe,[data-sitekey],.g-recaptcha,.h-captcha,.cf-turnstile').some(e => {
    const signature = [e.src, e.title, e.className].map(String).join(' ');
    return visible(e) && e.getAttribute('aria-hidden') !== 'true' && /captcha|turnstile|challenge-platform/i.test(signature);
  });
  const bodyText = tidy(document.body?.innerText, 18000);
  const progress = bodyText.match(/\b(?:step|stage|page)\s+(\d+)\s*(?:of|\/)\s*(\d+)\b/i);
  const captchaText = /^(?:(?:human|security|bot)\s+verification(?:\s+(?:puzzle|challenge))?|(?:verify|confirm)\s+(?:that\s+)?you(?:'re| are)\s+(?:a\s+)?human|(?:captcha|robot) challenge)$/i;
  const humanPrompt = unique.some(t => /^(?:please\s+)?(?:verify|confirm)\s+(?:that\s+)?(?:you(?:'re| are)\s+(?:a\s+)?human|you(?:'re| are)\s+not\s+a\s+robot)|^(?:enter|type)\s+(?:the\s+)?(?:verification|security|one.time)\s+code\b/i.test(t));
  return {
    title: document.title, url: location.href, epoch: memory.epoch, elements, headings,
    notices: ordered.join('\n').slice(0, 4000),
    context: bodyText.slice(0, 1600) + (bodyText.length > 2800 ? '\n' + bodyText.slice(-1200) : '\n' + bodyText.slice(1600)),
    alerts: [...new Set(alerts)].slice(0, 12),
    captcha: humanMarker || humanPrompt || headings.some(t => captchaText.test(t)),
    step: progress ? progress[0] : '',
  };
}
"""


@dataclass
class Element:
    frame: Frame
    scope: str
    epoch: str
    data: dict

    def __getitem__(self, item):
        return self.data[item]

    @property
    def label(self) -> str:
        return self["label_text"] or self["aria_label"] or self["name"] or self["id"] or self["placeholder"]


@dataclass
class Snapshot:
    title: str
    url: str
    step: str
    headings: list[str]
    notices: str
    context: str
    alerts: list[str]
    human: str
    elements: list[Element]
    ax: list[str]

    def signature(self) -> str:
        structure = [(e.scope, e["tag"], e["type"], e["role"], e["name"], e.label, e["disabled"]) for e in self.elements]
        material = [self.url, self.step, self.headings, self.human, structure]
        return hashlib.sha256(json.dumps(material).encode()).hexdigest()


async def distill(session, *, accessibility=False) -> Snapshot:
    await session.switch_popup()
    page = session.page
    main = await page.evaluate(INSPECT)
    elements = [Element(page.main_frame, "main", main["epoch"], data) for data in main["elements"]]
    headings, child_notices, alerts = list(main["headings"]), [], list(main["alerts"])
    captcha = main["captcha"]
    for index, frame in enumerate(page.frames[1:9]):
        try:
            frame_element = await frame.frame_element()
            if not await frame_element.is_visible():
                continue
            child = await frame.evaluate(INSPECT)
        except PlaywrightError:
            continue
        scope = f"frame:{index}:{frame.name or frame.url.split('?')[0]}"
        elements.extend(Element(frame, scope, child["epoch"], data) for data in child["elements"][:100])
        headings.extend(child["headings"])
        child_notices.append(child["notices"][:650])
        alerts.extend(child["alerts"])
        captcha = captcha or child["captcha"]
    ax = []
    if accessibility:
        try:
            nodes = (await session.cdp.send("Accessibility.getFullAXTree", {"depth": 10}))["nodes"]
            ax = [
                f'{node["role"]["value"]}: {node["name"]["value"][:140]}'
                for node in nodes if not node.get("ignored") and node.get("name", {}).get("value")
                and node["role"]["value"] in {"heading", "landmark", "textbox", "button", "link", "combobox", "checkbox", "radio", "form"}
            ][:65]
        except PlaywrightError:
            pass
    human = "The website is asking for human verification." if captcha else ""
    for e in elements:
        text = " ".join(str(e[key]) for key in ("label_text", "name", "id", "autocomplete"))
        if e["disabled"]:
            continue
        if e["type"] in {"", "text", "number", "tel", "password"} and re.search(
            r"\botp\b|one[ -]time[ -](?:code|password)|verification[ _-]*code|authenticator[ _-]*code", text, re.I,
        ):
            human = "The website requires a one-time or verification code."
            break
        if e["type"] == "password":
            human = "The website requires a password or sign-in."
            break
    if not human and any(re.fullmatch(r"(?:sign in|log in|log on|account sign.in|authentication)", heading, re.I)
                         for heading in headings) and any(e["type"] in {"", "text", "email", "tel"}
                         and e["tag"] == "input" for e in elements):
        human = "The website requires sign-in."
    return Snapshot(main["title"], main["url"], main["step"], headings[:30],
                    "\n".join([main["notices"], *child_notices]).strip()[:4000], main["context"],
                    list(dict.fromkeys(alerts))[:12], human, elements, ax)
