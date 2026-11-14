# Feature & branch status: what is live vs not

> As of 2026-11-14. Prod (`production`) tree == `main` @ 7287616 (2026-11-11). Pre-prod also runs `main`.
> "Live" = in code on main/prod. Whether a *tenant* has a feature enabled is DB state (Tenant.features) — not visible from the repo.
> Whether prod VM compose matches main (new workers running, env set) is **[CHECK on VM]**; the repo can't prove it.

## Live on main / prod (code level)
Courses/subjects/topics/chapters, content (notes/video/PDF) with ffmpeg remux + HLS pipeline, quizzes, legacy + rich mock tests, AI mock-test builder (`mockgen`), analytics, gamification (XP/badges/leaderboard), AI doubt solver + multi-provider LLM layer + platform AI allocations, AI Course/Topic Studio (`coursegen`), Python notebooks/labs + AI lab generator, coding problems (Piston), assignments (creator-controlled), certificates, community (+ moderation, events, course scoping), live classes (Zoom + attendance), job portal, payments (Razorpay/Cashfree/PayU, student pay-to-enrol), marketing (coupons/promo banner), notifications (+ birthday greetings), hackathons (staged rounds + AI studio), tenant landing-page builder, tenant registration config + guardian consent, tenant verified email domains (Azure ARM), hidden/enrolled-only courses, superadmin console (tenants, billing, suspension, AI allocations, leads), marketing site + demo portal.

## NOT deployed (exists only on branches)
| Item | Where | State | Doc |
|---|---|---|---|
| **Learner Intelligence Layer** (LearningEvents, concept taxonomy + LLM item tagging, learner state/mastery, adaptive Practice, AI grading of subjective answers w/ confidence escalation, My Progress, teacher heatmap/insights, response diagnosis, skill facets) | `origin/saksham/learning-layer-2b` (157 commits, 215 files, +52k lines; ~550 tests). User's local `feat/intelligence-foundation` is a strict 13-commit subset → superseded | complete but needs merge with main (real conflict in `core/models.py`, exams migration-graph conflict `0015_*`), new compose services `celery-intelworker` + `celery-beat`, new dep PyYAML, `sync_taxonomy` on web start; opt-in per tenant via feature flags; **non-flagged side effects hit every tenant** (quiz post_save analytics signals removed → mastery counts grow slower; XP awarding moved) | `backend/intelligence.md`, `infra/intelligence-rollout.md` |
| Humanizer (de-AI-ify course drafts via a transformers micro-service container) | `origin/saksham/humanizer-de-ai` (5 commits, Nov 3) | needs product + resource decision | `infra/unmerged-branches.md` |
| Platform LLM fleet last commit (hide included models from tenants + failover) | `origin/feat/platform-llm-fleet` `721c308` | rest already on main; last commit unmerged, 48 behind | `infra/unmerged-branches.md` |
| ~10 fully-merged stale branches (coding-questions, landing-*, payu, zoom, notebooks, job-portal, …) | remote | safe to delete (team decision) | `infra/unmerged-branches.md` |
| ~120 other remote branches (138 total) | remote | not reviewed | — |

## Other undeployed/partial things to know
- `celery-beat` does not exist on main (see `deployment-current.md`); periodic commands rely on cron/manual.
- Wiki claims vs code drift: see `known-issues.md` (docs drift section).
- The current working checkout (`feat/intelligence-foundation`) is 31 commits **behind** main and lacks `hackathons`, tenant email domains, HLS/media worker, piston-init, etc. For "what is in production" always read `origin/main`, not the working tree.

## Recommended order of work (for the CI/CD engagement)
1. Stand up CI on `main` (build/test gates) before merging the large intelligence branch — it makes that merge verifiable (~550 new tests + existing ~335).
2. Merge main→2b, fix conflicts, run tests, deploy dark to pre-prod via the new pipeline, pilot on one tenant, then prod (`infra/intelligence-rollout.md`).
3. Decide humanizer / llm-fleet commit; prune stale branches.
