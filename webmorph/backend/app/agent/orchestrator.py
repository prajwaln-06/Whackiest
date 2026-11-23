import asyncio
import base64
import logging
import shutil
import time
from collections import deque
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from playwright.async_api import Error as PlaywrightError

from app.agent import matcher, scout
from app.browser import executor
from app.browser.distiller import Element, Snapshot, distill
from app.browser.session import Browser, BrowserSession, origin
from app.config import Settings
from app.db.store import Store
from app.llm.client import LLM
from app.models.schemas import Approval, AuditEntry, Change, Launch, RunState, Status, Value, WSEvent


log = logging.getLogger(__name__)
TERMINAL = {Status.COMPLETED, Status.FAILED}
WAITING = {Status.AWAITING_USER_FORM, Status.NEEDS_USER_INPUT}


class Conflict(Exception):
    pass


@dataclass(eq=False)
class Subscriber:
    messages: deque
    signal: asyncio.Event
    frame: dict | None = None


@dataclass
class Checkpoint:
    snapshot: Snapshot
    element: Element
    values: dict[str, Value]


def control_identity(element: Element):
    return (element.scope, element["tag"], element["type"], element["role"], element["name"],
            element["id"], element.label, element["href"], element["form_method"])


def foreign_frame(element: Element, snapshot: Snapshot):
    frame_url = element.frame.url
    return element.scope != "main" and frame_url.startswith(("http://", "https://")) and origin(frame_url) != origin(snapshot.url)


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class Run:
    def __init__(self, request: Launch, manager):
        self.manager = manager
        self.id = uuid4().hex
        self.state = RunState(session_id=self.id, status=Status.SCOUTING, url=str(request.url), goal=request.goal)
        self.language = request.language
        self.session = BrowserSession(self.publish)
        self.task: asyncio.Task | None = None
        self.lock = asyncio.Lock()
        self.subscribers: set[Subscriber] = set()
        self.answers: dict[str, Value] = {}
        self.memory: dict[str, dict[str, Value]] = {}
        self.changes: dict[str, Change] = {}
        self.rewrites = {}
        self.seen = set()
        self.offered = set()
        self.files: dict[str, Path] = {}
        self.pending: Checkpoint | None = None
        self.request_takeover = False
        self.takeover_notice = ""
        self.manual_values: dict[str, Value] = {}
        self.last_active = time.monotonic()
        self.work_limit = 0
        self.attempts: dict[tuple, int] = {}
        self.nav_counts: dict[tuple, int] = {}
        self.accepted_origin = None
        self.has_navigated = False
        self.closed = False

    def publish(self, kind: str, payload: dict):
        for sub in self.subscribers:
            if kind == "frame":
                sub.frame = payload
            else:
                sub.messages.append(WSEvent(type=kind, payload=payload))
            sub.signal.set()

    def subscribe(self):
        sub = Subscriber(deque(maxlen=20), asyncio.Event(), self.session.frame)
        sub.messages.append(WSEvent(type="state", payload=self.state.model_dump(mode="json", by_alias=True)))
        sub.signal.set()
        self.subscribers.add(sub)
        return sub

    async def persist(self):
        self.state.revision += 1
        self.publish("state", self.state.model_dump(mode="json", by_alias=True))
        await self.manager.store.save_run(self.state, [change.model_dump(mode="json") for change in self.changes.values()])

    async def state_as(self, status: Status, message=""):
        self.state.status, self.state.message = status, message
        if status != Status.AWAITING_APPROVAL:
            self.state.approval = None
        await self.persist()

    def audit(self, action, label, *, strategy="", verified=None, start=None, detail=""):
        self.state.timeline.append(AuditEntry(
            at=timestamp(), action=action, label=label, strategy=strategy, verified=verified,
            duration_ms=round(1000 * (time.monotonic() - start)) if start is not None else 0, detail=detail,
        ))

    def note_provider(self, notice):
        if notice and notice != self.state.provider_notice:
            self.state.provider_notice = notice

    async def analyze(self, snapshot, targets, *, initial=False):
        new = [target for target in targets if target.spec.key not in self.seen]
        self.seen.update(target.spec.key for target in new)
        if (initial or new) and not snapshot.human:
            brief, rewrites, notice = await scout.analyze(self.manager.llm, snapshot, new, self.state.goal,
                                                           self.language, include_brief=initial)
            if initial:
                self.state.brief = brief
            self.rewrites.update(rewrites)
            self.note_provider(notice)
        for target in targets:
            rewrite = self.rewrites.get(target.spec.key)
            if rewrite:
                target.spec.label = rewrite.label or target.spec.label
                target.spec.hint = rewrite.hint or target.spec.hint

    async def scouted(self):
        start = time.monotonic()
        await self.session.open(self.manager.browser, self.state.url)
        snapshot = await distill(self.session, accessibility=True)
        self.accepted_origin = origin(snapshot.url)
        self.state.url = snapshot.url
        if snapshot.human or self.request_takeover:
            self.state.brief = scout.heuristic_brief(snapshot)
            await self.handover(snapshot.human or "Manual control requested.")
            return
        targets = scout.field_targets(snapshot, self.language)
        await self.analyze(snapshot, targets, initial=True)
        await self.add_suggestions(targets)
        self.offered.update(target.spec.key for target in targets)
        self.state.form = scout.schema(snapshot, targets)
        self.audit("scout", snapshot.title or snapshot.url, verified=True, start=start,
                   detail=f"Mapped {len(targets)} visible fields.")
        await self.state_as(Status.AWAITING_USER_FORM)

    async def add_suggestions(self, targets):
        vault = await self.manager.store.vault()
        for target in targets:
            if target.spec.kind == "checkbox" and target.spec.required:
                target.spec.confirm_explicitly = target.spec.key not in self.answers
            if target.spec.key not in self.answers and not matcher.is_set(target.spec.current):
                matcher.suggest(target, vault, self.memory, self.answers)
            elif target.spec.key in self.answers and target.spec.kind != "file":
                target.spec.suggestion = self.answers[target.spec.key]

    def memory_add(self, target, answer):
        if target.spec.kind in {"file", "radio", "checkbox"} or not matcher.is_set(answer):
            return
        for identity in matcher.identities(target):
            self.memory.setdefault(identity, {})[target.spec.key] = answer

    async def handover(self, reason: str):
        self.request_takeover = False
        self.takeover_notice = reason
        self.pending = None
        with suppress(PlaywrightError):
            self.manual_values = {target.spec.key: target.spec.current for target in
                                  scout.field_targets(await distill(self.session), self.language)}
        self.audit("handover", "Manual browser control", detail=reason)
        await self.state_as(Status.HUMAN_TAKEOVER, reason)
        await self.session.pulse()

    async def accept_manual_changes(self):
        snapshot = await distill(self.session)
        self.accepted_origin = origin(snapshot.url)
        if not snapshot.human:
            for target in scout.field_targets(snapshot, self.language):
                spec = target.spec
                if spec.key not in self.manual_values or self.manual_values[spec.key] == spec.current:
                    continue
                if spec.kind == "file" or matcher.SENSITIVE.search(scout.normalize(spec.original)):
                    self.answers.pop(spec.key, None)
                elif matcher.valid_answer(target, spec.current):
                    self.answers[spec.key] = spec.current
                    self.memory_add(target, spec.current)
                else:
                    self.answers.pop(spec.key, None)
        self.manual_values.clear()
        self.nav_counts.clear()
        self.audit("resume", "Control returned to the pilot")

    async def follow_up(self, snapshot, targets, message=""):
        self.state.form = scout.schema(snapshot, targets)
        self.offered.update(target.spec.key for target in targets)
        self.audit("pause", "Waiting for input", detail=message or f"{len(targets)} fields available.")
        await self.state_as(Status.NEEDS_USER_INPUT, message)

    async def navigation_result(self, previous, element, strategy, started):
        snapshot = await distill(self.session)
        changed = previous.signature() != snapshot.signature() or previous.alerts != snapshot.alerts
        for delay in (0.15, 0.3, 0.5, 0.75, 0.9):
            if changed or self.request_takeover:
                break
            await asyncio.sleep(delay)
            snapshot = await distill(self.session)
            changed = previous.signature() != snapshot.signature() or previous.alerts != snapshot.alerts
        self.audit("click", element.label, strategy=strategy, verified=changed, start=started,
                   detail="Website state changed." if changed else "No transition was observed.")
        self.has_navigated = True
        if changed and not snapshot.alerts and not snapshot.human:
            self.state.transitions += 1
        await self.persist()
        return snapshot, changed

    def validation_targets(self, snapshot, targets):
        invalid = [target for target in targets if target.spec.error]
        for target in targets:
            original = scout.normalize(target.spec.original)
            if len(original) < 3:
                continue
            matched = next((alert for alert in snapshot.alerts if original in scout.normalize(alert)), "")
            if matched:
                target.spec.error = matched
                if target not in invalid:
                    invalid.append(target)
        return invalid

    def record_existing(self, snapshot, targets):
        for target in targets:
            spec = target.spec
            if matcher.SENSITIVE.search(scout.normalize(spec.original)):
                continue
            existing = self.changes.get(spec.key)
            if existing:
                observed = spec.current
                if spec.kind == "file" and not spec.multiple and isinstance(observed, list):
                    observed = next(iter(observed), "")
                if existing.after != observed:
                    existing.after = observed
            elif matcher.is_set(spec.current):
                self.changes[spec.key] = Change(key=spec.key, label=spec.original, before=spec.current,
                                                after=spec.current, step=snapshot.step, url=snapshot.url)

    async def pilot(self, checkpoint: Checkpoint | None = None):
        from_click = False
        changed = False
        snapshot = await distill(self.session, accessibility=not self.seen)
        if checkpoint:
            approved = await self.approved_click(checkpoint, snapshot)
            if approved is None:
                return
            snapshot, changed = approved
            from_click = True
        while not self.closed:
            self.work_limit += 1
            if self.work_limit > 350:
                await self.state_as(Status.FAILED, "This run reached the action limit.")
                return
            self.state.url = snapshot.url
            self.state.form.step = snapshot.step
            self.state.form.url = snapshot.url
            if self.request_takeover or snapshot.human:
                await self.handover(snapshot.human or "Manual control requested.")
                return
            if origin(snapshot.url) != self.accepted_origin:
                await self.handover("The workflow moved to another website. Confirm it in the browser before handing back.")
                return
            confirmation = scout.receipt(snapshot)
            if confirmation and (self.has_navigated or self.takeover_notice):
                self.state.receipt = confirmation
                self.audit("receipt", confirmation.reference or "Website confirmation", verified=True)
                await self.state_as(Status.COMPLETED)
                await self.session.pulse()
                return

            targets = scout.field_targets(snapshot, self.language)
            await self.analyze(snapshot, targets, initial=self.state.brief is None)
            await self.add_suggestions(targets)
            self.record_existing(snapshot, targets)
            invalid = self.validation_targets(snapshot, targets)
            if from_click and (invalid or snapshot.alerts):
                if invalid:
                    await self.follow_up(snapshot, invalid, " ".join(snapshot.alerts) or "The website flagged these answers.")
                else:
                    await self.handover("The website displayed a notice. " + " ".join(snapshot.alerts))
                return
            if from_click and not changed:
                await self.handover("The website did not advance. Review the live page to continue safely.")
                return
            from_click = False

            action = None
            missing = []
            for target in targets:
                spec = target.spec
                desired = matcher.option_value(target, self.answers.get(spec.key, spec.suggestion))
                if desired is None or (desired in ("", []) and not matcher.is_set(spec.current)):
                    if spec.required and (not matcher.is_set(spec.current) or spec.confirm_explicitly):
                        missing.append(target)
                    continue
                if not matcher.valid_answer(target, desired):
                    spec.error = spec.error or "Enter a valid answer to continue."
                    missing.append(target)
                    continue
                expected = desired
                if spec.kind == "file":
                    tokens = desired if isinstance(desired, list) else [desired]
                    paths = [self.files[token] for token in tokens if token in self.files]
                    expected = [path.name for path in paths] if spec.multiple else [path.name for path in paths[:1]]
                    if len(paths) != len(tokens):
                        spec.error = "Upload the file for this run."
                        missing.append(target)
                        continue
                before = spec.current
                if spec.kind == "file" and not spec.multiple and isinstance(before, list):
                    before = before[:1]
                if expected == before and not spec.error:
                    self.memory_add(target, desired)
                    continue
                if action is None:
                    action = (target, desired)
            if action:
                if foreign_frame(action[0].element, snapshot):
                    await self.handover("This field belongs to a different site embedded in the page. Review it in the live browser.")
                    return
                if not await self.fill(snapshot, *action):
                    return
                snapshot = await distill(self.session)
                continue
            if invalid:
                missing.extend(target for target in invalid if target not in missing)
            if missing:
                optional = [t for t in targets if t.spec.key not in self.offered and t not in missing and not t.spec.required
                            and not matcher.is_set(t.spec.current) and not matcher.is_set(t.spec.suggestion)]
                await self.follow_up(snapshot, missing + optional, "The website needs a few more answers.")
                return

            element, approval, notice = await scout.plan(self.manager.llm, snapshot, self.state.goal)
            self.note_provider(notice)
            if self.request_takeover:
                await self.handover("Manual control requested.")
                return
            if not element:
                await self.handover("No unambiguous next action was found. Continue in the live browser.")
                return
            if foreign_frame(element, snapshot):
                await self.handover("The next control belongs to a different site embedded in the page.")
                return
            if approval:
                await self.ask_approval(snapshot, element, targets)
                return
            if self.state.transitions >= self.manager.settings.webmorph_max_steps:
                await self.state_as(Status.FAILED, "This run reached the page transition limit.")
                return
            fingerprint = (snapshot.signature(), control_identity(element), repr([(t.spec.key, t.spec.current) for t in targets]))
            if self.nav_counts.get(fingerprint, 0) >= 1:
                await self.handover("The same page and action repeated without progress. Review the live browser.")
                return
            self.nav_counts[fingerprint] = self.nav_counts.get(fingerprint, 0) + 1
            latest = await distill(self.session)
            if latest.signature() != snapshot.signature():
                snapshot = latest
                continue
            started = time.monotonic()
            try:
                strategy, locator = await executor.prepare_click(self.session, element)
                await executor.click(self.session, locator)
            except executor.ActionError as error:
                self.audit("click", element.label, verified=False, start=started, detail=str(error))
                await self.handover(str(error))
                return
            snapshot, changed = await self.navigation_result(snapshot, element, strategy, started)
            from_click = True

    async def fill(self, snapshot, target, desired):
        spec = target.spec
        fingerprint = (spec.key, repr(desired))
        start = time.monotonic()
        try:
            if self.attempts.get(fingerprint, 0) >= 2:
                raise executor.ActionError("The website repeatedly reset this answer.")
            self.attempts[fingerprint] = self.attempts.get(fingerprint, 0) + 1
            result = await executor.apply(self.session, target, desired, self.files)
            self.audit(result.action, spec.original, strategy=result.strategy, verified=result.verified, start=start,
                       detail="Read back from the website." if result.verified else "The website retained a different value.")
            if not result.verified:
                raise executor.ActionError("The website retained a different value. Check the requested format.")
        except executor.ActionError as error:
            if not self.state.timeline or self.state.timeline[-1].label != spec.original or self.state.timeline[-1].verified is not False:
                self.audit("field", spec.original, verified=False, start=start, detail=str(error))
            spec.error = str(error)
            self.answers.pop(spec.key, None)
            if spec.kind != "file":
                spec.suggestion = desired
            await self.follow_up(snapshot, [target], str(error))
            return False
        if not matcher.SENSITIVE.search(scout.normalize(spec.original)):
            previous = self.changes.get(spec.key)
            self.changes[spec.key] = Change(key=spec.key, label=spec.original, before=previous.before if previous else spec.current,
                                            after=result.value, step=snapshot.step, url=snapshot.url)
        self.memory_add(target, desired)
        await self.persist()
        return True

    async def ask_approval(self, snapshot, element, targets):
        try:
            screenshot = await self.session.page.screenshot(type="jpeg", quality=65, full_page=True, timeout=4500)
        except PlaywrightError:
            screenshot = await self.session.page.screenshot(type="jpeg", quality=65, timeout=2500)
        self.pending = Checkpoint(snapshot, element, {t.spec.key: t.spec.current for t in targets})
        self.state.approval = Approval(
            token=uuid4().hex, button=element.label, screenshot=base64.b64encode(screenshot).decode(),
            changes=list(self.changes.values()),
        )
        self.audit("approval", element.label, detail="Waiting for explicit approval to click.")
        await self.state_as(Status.AWAITING_APPROVAL)

    async def approved_click(self, checkpoint, snapshot):
        targets = scout.field_targets(snapshot, self.language)
        values = {t.spec.key: t.spec.current for t in targets}
        matches = [e for e in snapshot.elements if not e["disabled"] and control_identity(e) == control_identity(checkpoint.element)]
        if snapshot.human or len(matches) != 1 or snapshot.signature() != checkpoint.snapshot.signature() or values != checkpoint.values:
            await self.handover("The website changed after the approval preview. Inspect it before continuing.")
            return None
        element = matches[0]
        started = time.monotonic()
        try:
            strategy, locator = await executor.prepare_click(self.session, element)
            await executor.click(self.session, locator)
        except executor.ActionError as error:
            self.audit("click", element.label, verified=False, start=started, detail=str(error))
            await self.handover(str(error))
            return None
        return await self.navigation_result(snapshot, element, strategy, started)

    def begin(self, operation):
        async def guarded():
            try:
                await operation
            except asyncio.CancelledError:
                raise
            except Exception as error:
                log.exception("Run %s failed", self.id)
                if isinstance(error, PlaywrightError):
                    message = "Chromium could not open or inspect this website. Check the address, connectivity, and browser installation."
                else:
                    message = str(error)[:450] or "An unexpected browser error occurred."
                self.audit("error", "Run stopped", verified=False, detail=message)
                await self.state_as(Status.FAILED, message)
        self.task = asyncio.create_task(guarded())

    async def enter_pilot(self, checkpoint=None):
        if self.task and not self.task.done():
            await self.task
        self.last_active = time.monotonic()
        await self.state_as(Status.EXECUTING)
        self.begin(self.pilot(checkpoint))

    async def close(self):
        self.closed = True
        if self.task and not self.task.done():
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
        await self.session.close()
        for subscriber in self.subscribers:
            subscriber.signal.set()


class Manager:
    def __init__(self, settings: Settings, store: Store, llm: LLM):
        self.settings, self.store, self.llm = settings, store, llm
        self.browser = Browser()
        self.runs: dict[str, Run] = {}
        self.lock = asyncio.Lock()

    async def create(self, request: Launch) -> Run:
        async with self.lock:
            await self.prune()
            if len(self.runs) >= self.settings.webmorph_max_runs:
                for run in list(self.runs.values()):
                    if run.state.status in TERMINAL:
                        await self.remove(run.id)
                        break
            if len(self.runs) >= self.settings.webmorph_max_runs:
                raise Conflict("The local browser run limit is reached. Close an existing run.")
            run = Run(request, self)
            self.runs[run.id] = run
            await run.persist()
            run.begin(run.scouted())
            return run

    async def prune(self):
        cutoff = time.monotonic() - self.settings.webmorph_idle_minutes * 60
        for run in list(self.runs.values()):
            if run.last_active < cutoff and not (run.task and not run.task.done()):
                await self.remove(run.id)

    async def remove(self, identifier: str):
        run = self.runs.pop(identifier, None)
        if run:
            async with run.lock:
                await run.close()
                if run.state.status not in TERMINAL:
                    await run.state_as(Status.FAILED, "The browser session was closed.")
                await asyncio.to_thread(shutil.rmtree, self.settings.data_dir / "uploads" / identifier, True)

    async def close(self):
        for identifier in list(self.runs):
            await self.remove(identifier)
        await self.browser.close()
