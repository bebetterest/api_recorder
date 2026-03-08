# AGENTS.md

## Environment

- Use the conda environment named `api_recorder` for all development, verification, and debugging.
- If dependencies change, update `environment.yml` and keep editable install instructions in both README files in sync.
- Prefer commands that work on macOS first, but avoid platform-specific code when a cross-platform standard library approach is practical.

## Documentation sync

- Any change to CLI behavior, config schema, record schema, or service lifecycle must update:
  - `README.md`
  - `README_cn.md`
  - `docs/architecture.md`
  - `docs/architecture_cn.md`
  - `docs/progress.md`
  - `docs/progress_cn.md`
- `docs/progress*.md` must reflect what is already done, what was verified, and what is still pending.
- English docs are the primary files; Chinese files are parallel translations and must be kept aligned.

## Implementation expectations

- Keep the local proxy generic unless a task explicitly requires vendor-specific protocol mapping.
- Preserve JSONL record field names once shipped; later extensions should add fields instead of renaming existing ones.
- Keep sensitive header redaction enabled by default.
- Treat `config.toml` as the source of truth and use CLI commands to mutate it when possible.

## Verification

- Run `conda run -n api_recorder python -m pytest` after meaningful code changes.
- When background lifecycle behavior changes, verify `init -> start -> status -> stop` if local port binding is permitted in the current environment.
- If sandbox restrictions block runtime verification, note the exact blocked command and error in `docs/progress.md` and `docs/progress_cn.md`.
