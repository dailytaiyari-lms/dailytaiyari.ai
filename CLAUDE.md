# DailyTaiyari — agent instructions

Before exploring the code, read `project-knowledge/README.md` (index) and then `project-knowledge/overview.md`, `architecture.md`, `known-issues.md`. It maps the whole repo (21 Django apps, 3 frontends, deployment, env vars, undeployed branches) so you only need to open the specific app doc and source files for your task.

- Production = `origin/main`; verify with `git log origin/main -1` — your checkout may be on an older feature branch.
- Never write secrets, tenant UUIDs or credentials into the repo or docs.
- Keep `project-knowledge/` current when you change behaviour.
