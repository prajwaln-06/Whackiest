import asyncio
import re
import sys
import tempfile
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from playwright.async_api import Error as PlaywrightError
from pydantic import ValidationError
from pypdf.errors import PdfReadError

from app.agent.matcher import document_text, extract_facts
from app.agent.orchestrator import Conflict, Manager, TERMINAL, WAITING
from app.config import FRONTEND_ORIGINS, settings
from app.db.store import Store
from app.llm.client import LLM
from app.models.schemas import Answers, Consent, InputEvent, Launch, Status, Vault, WSEvent


MAX_UPLOAD = 10 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    store = Store(settings.data_dir / "webmorph.sqlite3")
    await store.open()
    llm = LLM(settings)
    manager = Manager(settings, store, llm)
    app.state.manager = manager

    async def reap():
        while True:
            await asyncio.sleep(45)
            async with manager.lock:
                await manager.prune()

    cleaner = asyncio.create_task(reap())
    try:
        yield
    finally:
        cleaner.cancel()
        with suppress(asyncio.CancelledError):
            await cleaner
        await manager.close()
        await llm.close()
        await store.close()


app = FastAPI(title="WebMorph Local Agent", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)


@app.middleware("http")
async def workspace_request(request, call_next):
    if request.url.path.startswith("/api/") and request.url.path != "/api/health" and request.method != "OPTIONS":
        caller = request.headers.get("origin")
        if request.headers.get("x-webmorph-client") != "workspace" or (caller and caller not in FRONTEND_ORIGINS):
            return JSONResponse({"detail": "Open the local WebMorph workspace to use this endpoint."}, status_code=403)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    return response


app.add_middleware(CORSMiddleware, allow_origins=sorted(FRONTEND_ORIGINS),
                   allow_methods=["GET", "POST", "PUT", "DELETE"], allow_headers=["Content-Type", "X-WebMorph-Client"])
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])


def manager() -> Manager:
    return app.state.manager


def run_for(session_id):
    run = manager().runs.get(session_id)
    if run is None or run.closed:
        raise HTTPException(404, "This browser session has closed. Its audit is available in run history.")
    run.last_active = time.monotonic()
    return run


@app.exception_handler(Conflict)
async def conflict_handler(request, error):
    return JSONResponse({"detail": str(error)}, status_code=409)


@app.get("/api/health")
async def health():
    return {"status": "ok", "provider_configured": manager().llm.client is not None}


@app.post("/api/runs", status_code=201)
async def launch(request: Launch):
    run = await manager().create(request)
    return run.state


@app.get("/api/runs")
async def history():
    return await manager().store.history()


@app.get("/api/runs/{session_id}")
async def state(session_id: str):
    return run_for(session_id).state


@app.delete("/api/runs/{session_id}")
async def close_run(session_id: str):
    async with manager().lock:
        await manager().remove(session_id)
    return {"closed": True}


@app.get("/api/runs/{session_id}/audit")
async def audit(session_id: str):
    data = await manager().store.audit(session_id)
    if data is None:
        raise HTTPException(404, "No audit was found for this run.")
    return JSONResponse(data, headers={"Content-Disposition": f'attachment; filename="webmorph-{data["session_id"]}.json"'})


@app.post("/api/runs/{session_id}/answers")
async def answers(session_id: str, payload: Answers):
    run = run_for(session_id)
    async with run.lock:
        if run.closed or run.state.status not in WAITING:
            raise Conflict("The pilot is not waiting for answers.")
        allowed = {field.key for field in run.state.form.fields}
        if not payload.values.keys() <= allowed:
            raise Conflict("The form changed. Use the current adaptive fields.")
        run.answers.update(payload.values)
        await run.enter_pilot()
    return run.state


@app.post("/api/runs/{session_id}/takeover")
async def takeover(session_id: str):
    run = run_for(session_id)
    async with run.lock:
        if run.closed or run.state.status in TERMINAL:
            raise Conflict("This run has ended.")
        if run.state.status in {Status.SCOUTING, Status.EXECUTING}:
            run.request_takeover = True
        elif run.state.status != Status.HUMAN_TAKEOVER:
            await run.handover("Manual control requested.")
    return run.state


@app.post("/api/runs/{session_id}/resume")
async def resume(session_id: str):
    run = run_for(session_id)
    async with run.lock:
        if run.closed or run.state.status != Status.HUMAN_TAKEOVER:
            raise Conflict("Manual browser control is not active.")
        await run.accept_manual_changes()
        await run.enter_pilot()
    return run.state


@app.post("/api/runs/{session_id}/approve")
async def approve(session_id: str, consent: Consent):
    run = run_for(session_id)
    async with run.lock:
        if (run.closed or run.state.status != Status.AWAITING_APPROVAL or not run.pending
                or not run.state.approval or consent.token != run.state.approval.token):
            raise Conflict("The approval preview has expired. Review the current browser state.")
        checkpoint, run.pending = run.pending, None
        run.audit("consent", checkpoint.element.label, detail="The user approved this specific action.")
        await run.enter_pilot(checkpoint)
    return run.state


def safe_name(raw: str | None) -> str:
    name = re.sub(r"[^\w .()\-]", "_", (raw or "upload").replace("\\", "/").split("/")[-1]).strip(" .")[:155]
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"{kind}{i}" for kind in ("COM", "LPT") for i in range(1, 10))}
    if name.split(".")[0].upper() in reserved:
        name = "_" + name
    return name or "upload"


async def save_upload(upload: UploadFile, path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    try:
        with path.open("xb") as output:
            while chunk := await upload.read(65536):
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise HTTPException(413, "Files must be 10 MB or smaller.")
                output.write(chunk)
        if not size:
            raise HTTPException(422, "Choose a file with content.")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


@app.post("/api/runs/{session_id}/files")
async def upload_file(session_id: str, file: UploadFile = File(...)):
    run = run_for(session_id)
    async with run.lock:
        if run.closed or run.state.status not in WAITING:
            raise Conflict("Return to the adaptive form before uploading.")
        if len(run.files) >= 24:
            raise HTTPException(413, "This run has reached its upload limit.")
        token = uuid4().hex
        path = settings.data_dir / "uploads" / run.id / token / safe_name(file.filename)
        await save_upload(file, path)
        run.files[token] = path
    return {"token": token, "name": path.name}


@app.get("/api/vault")
async def get_vault():
    return await manager().store.vault()


@app.put("/api/vault")
async def put_vault(vault: Vault):
    return await manager().store.save_vault(vault)


@app.post("/api/vault/document")
async def parse_document(file: UploadFile = File(...)):
    name = safe_name(file.filename)
    if Path(name).suffix.casefold() not in {".pdf", ".txt"}:
        raise HTTPException(422, "Choose a PDF or TXT document.")
    with tempfile.TemporaryDirectory(prefix="webmorph-vault-") as directory:
        path = Path(directory) / name
        await save_upload(file, path)
        try:
            text = await asyncio.to_thread(document_text, path)
        except (ValueError, PdfReadError, OSError) as error:
            raise HTTPException(422, "Could not read this document. Use an unlocked PDF or plain-text file.") from error
    facts, notice = await extract_facts(manager().llm, text)
    return {"facts": facts.facts, "notice": notice}


@app.websocket("/ws/{session_id}")
async def websocket(socket: WebSocket, session_id: str):
    run = manager().runs.get(session_id)
    if socket.headers.get("origin") not in FRONTEND_ORIGINS or not run or run.closed:
        await socket.close(code=1008)
        return
    await socket.accept()
    sub = run.subscribe()
    run.last_active = time.monotonic()

    async def send():
        while True:
            await sub.signal.wait()
            sub.signal.clear()
            while sub.messages:
                await socket.send_text(sub.messages.popleft().model_dump_json())
            if sub.frame:
                frame, sub.frame = sub.frame, None
                await socket.send_text(WSEvent(type="frame", payload=frame).model_dump_json())
            if run.closed:
                await socket.close(code=1000)
                return

    async def receive():
        async for text in socket.iter_text():
            if len(text) > 18000:
                continue
            try:
                event = InputEvent.model_validate_json(text)
                async with run.lock:
                    if run.state.status != Status.HUMAN_TAKEOVER or run.closed:
                        continue
                    run.last_active = time.monotonic()
                    await run.session.input(event)
            except (ValidationError, PlaywrightError, ValueError):
                sub.messages.append(WSEvent(type="error", payload={"message": "The browser could not receive that input."}))
                sub.signal.set()

    tasks = {asyncio.create_task(send()), asyncio.create_task(receive())}
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            with suppress(WebSocketDisconnect, RuntimeError):
                task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        run.subscribers.discard(sub)


if __name__ == "__main__":
    # Single-process Uvicorn on a Proactor loop is required by Playwright's Windows subprocess transport.
    if sys.platform == "win32":
        with asyncio.Runner(loop_factory=asyncio.ProactorEventLoop) as runner:
            runner.run(uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8000, ws_max_size=32768)).serve())
    else:
        uvicorn.run(app, host="127.0.0.1", port=8000, ws_max_size=32768)
