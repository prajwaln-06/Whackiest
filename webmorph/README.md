# WebMorph

WebMorph is a local browser agent for the **Beyond the Browser — Reimagine How We Use the Web** hackathon track. Scout a site, review its requirements, answer an adaptive form, and watch Chromium carry out the workflow. WebMorph pauses for newly required information, human verification, and approval before a final action.

## Setup in three steps

1. Install Python 3.11 or later and Node.js 20.9 or later. Open a terminal in this `webmorph` directory.
2. Optionally copy `.env.example` to `.env` and set `LLM_API_KEY`, `LLM_MODEL`, and, for an OpenAI-compatible provider, `LLM_BASE_URL` including the provider’s API version path. The local fallback works with a blank configuration. A local OpenAI-compatible server may use its base URL alone.
3. Run `powershell -ExecutionPolicy Bypass -File .\start.ps1` on Windows or `bash start.sh` on macOS or Linux. Open the workspace URL printed by the launcher, usually `http://127.0.0.1:3000` and otherwise `http://127.0.0.1:3001`. The launcher installs dependencies and Chromium on first use, starts FastAPI on port 8000 and CivicGrid on port 8001, and stops the services when interrupted.

On minimal Linux installations, Playwright may also need system libraries. After the launcher creates the environment, run `./.venv/bin/python -m playwright install-deps chromium` if Chromium reports missing libraries. Run the launcher as a regular user so Chromium can use its sandbox. The Windows launcher starts the agent through `python -m app.main` with a Proactor event loop and a single Uvicorn process.

## CivicGrid demo walkthrough

1. Open **My Vault**, choose **Load sample persona**, and close the drawer. Select **Launch Demo Portal**, then **Scout website**. The brief surfaces eligibility, the proposal requirement, and the deadline from the site’s fine print. Five fields have vault suggestions. Choose a tax filing schedule and select **Auto-apply to website**.
2. Choose **Startup / Independent Builder**. Enter a public project URL such as `https://example.org/project` and choose **Pre-revenue**. Select **Include a co-applicant** to trigger another follow-up. Enter a co-applicant name and email, then continue.
3. Upload the included `demo_portal/static/sample-proposal.txt` or a PDF or TXT proposal of your own. Choose a delivery method and explicitly check both declarations. Continue, then use the live canvas to click the shape matching the portal’s sample. Select **Hand back to agent**.
4. Read and check the certification. The pilot pauses again before **SUBMIT APPLICATION**. Review the screenshot and field audit, then select **Approve this action**. The portal issues a reference ID. Download the audit JSON from the receipt or from **Run history**.

## How the services fit together

| Service | Responsibility |
| --- | --- |
| `frontend/` | Next.js 15, React, TypeScript, Tailwind, and Lucide power the workspace, accessibility modes, Vault, and live canvas. |
| `backend/` | FastAPI manages concurrent runs. Playwright controls isolated Chromium contexts. CDP streams frames. SQLite persists Vault facts and run audits. |
| `demo_portal/` | CivicGrid is a separate FastAPI site with conditional inputs, a custom combobox, document upload, a human verification puzzle, and a receipt. |

The agent extracts accessibility roles, headings, notices, controls, and options. It applies values through Playwright, verifies readback, then rescans for conditional fields. The planner chooses from indexed controls and the executor performs the chosen action. Explicit approval is scoped to the live control and its captured form values. A changed approval snapshot returns control to the user.

WebMorph is designed for a single user on their own computer. The workspace accepts HTTP and HTTPS targets. Complex widgets, ambiguous navigation, cross-origin transitions, sign-in, and verification can require manual control. Choose the form language before scouting. With an LLM configured, Hindi, Kannada, Spanish, and French can translate arbitrary labels and explanations. Offline translation covers common labels and helper text. Website option values are always preserved. Dictation uses browser speech recognition and depends on browser and microphone support.

Vault facts and audit JSON can contain personal information and are stored locally in `.data`. Document extraction sends extracted text to the configured provider when enabled. Website analysis sends distilled page context and field metadata. The live browser stays in memory while the agent is running. Uploaded form files are isolated by run and cleared when the session closes. Launcher output is in `.run`.

## Development checks

Run `npm run check` and `npm run build` in `frontend/`. Run `python -m compileall -q backend demo_portal` from the repository root. Use the walkthrough to exercise the local fallback, browser stream, conditional forms, human takeover, approval, and receipt end to end.
