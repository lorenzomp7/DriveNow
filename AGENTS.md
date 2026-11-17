# DriveNow

DriveNow is a Python GLOSA speed advisor with a JavaScript/canvas traffic map.
Work on `main_chatgpt` unless the user explicitly selects another branch.

## Development procedures

The project vendors seven procedures from `addyosmani/agent-skills` under
`.agents/skills/`. Before a task, read only the relevant procedure below.
Agents that discover `.agents/skills/` natively can load the same files directly;
otherwise use these paths. Shared checklists are in `.agents/references/`.

| Task | Procedure |
|---|---|
| Define a substantial feature | `.agents/skills/spec-driven-development/SKILL.md` |
| Break a substantial change into tasks | `.agents/skills/planning-and-task-breakdown/SKILL.md` |
| Implement a change across files | `.agents/skills/incremental-implementation/SKILL.md` |
| Change behavior or add regression coverage | `.agents/skills/test-driven-development/SKILL.md` |
| Review changes before completion | `.agents/skills/code-review-and-quality/SKILL.md` |
| Investigate a reproducible failure | `.agents/skills/debugging-and-error-recovery/SKILL.md` |
| Prepare an explicitly requested release | `.agents/skills/shipping-and-launch/SKILL.md` |

User instructions and the actual scope of the task take precedence over these
procedures. Continue within existing authorization; do not add approval gates
for routine reversible work. If asked to do one integration and stop, complete
and verify that integration, publish it, and stop. Do not start another.
Scale planning and verification to the change. Do not create ceremonial plans,
new tests for simple documentation edits, or unrelated refactors. Use tools
available in the current environment; a procedure does not install a tool or
make a slash command available. Do not delegate unless explicitly authorized.

## Project constraints

- Keep the standard-library demo runnable with `python -m drivenow.server`.
  Optional development tools must not become server dependencies.
- Keep the advice engine in `drivenow/glosa.py` independent of UI and simulator.
- Preserve units and the meaning of signal windows, uncertainty and queue data.
  Never treat unknown signal data as a guaranteed green or use recorded future
  data in the forecasting path. Keep oracle experiments explicitly separate.
- For simulation comparisons record seed, scenario, demand, penetration,
  duration, warm-up and completed trips. Do not present one seed as proof.
- Preserve third-party notices. The vendored procedures are pinned and unchanged;
  source revision and SHA-256 hashes are in `.agents/agent-skills.lock.json`.

## Verification

Use the commands applicable to the changed behavior:

- Engine/server: `python -m pytest -q` (SUMO checks may skip without SUMO).
- Browser: install `requirements-ui.txt` and Chromium, then run
  `python tests/browser/check_ui.py`. See `docs/browser-testing.md`.
- Patch hygiene: `git diff --check`.

Report checks actually executed, failures, skips and environment limitations.
Do not describe configured checks as passed checks or a prepared integration as
an active external service. The completion report should state what changed,
what was verified and any remaining setup that depends on user credentials.

## Optional isolated development

Container-use is configured in `.container-use/environment.json`. When this
MCP server is connected and Docker is available, it can provide a separate
container and Git ref for the requested change. See `docs/container-use.md`.
This configuration does not authorize extra agents or automatic merges.
Use `main_chatgpt` as the starting ref, preserve unrelated work, and inspect the
environment diff before applying it. Run the same DriveNow checks inside it.
Do not claim isolation when commands actually ran directly on the host.
