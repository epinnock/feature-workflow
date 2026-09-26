# Stage 6 - Production promotion

Production is `main`; a promotion script fast-forwards the tested `stage` sha after its gates.
Any script works if it does these things, in this order, and refuses to continue when one fails:

1. Checks staging health: `/healthz` answers and reports the sha being promoted.
2. Runs the service's smoke gate against staging.
3. Lists every PR in `origin/main..origin/stage` (everything that will ship, not only yours).
4. Lists pending database migrations and applies them from the exact tested sha.
5. Asks a person before pushing (never runs unattended), then fast-forwards `main` to the
   tested `stage` sha. No merge commits, no force pushes.
6. Appends a row to a deploy ledger (service, sha, previous sha, time, who approved).

Plus a **deployment probe** (prints, per service and tier, the sha that is actually serving)
and the per-service **smoke gate** from Stage 5.

```bash
git -C <repo> fetch origin && git -C <repo> log --oneline origin/main..origin/stage   # everything that ships
<promote> <service> --dry-run      # staging health, smoke gate, PR list, pending migrations
<promote> <service>                # asks before pushing; founder approval is Gate B, not a formality
<probe> <service>                  # production healthz == promoted sha
<smoke> <service> <production url>
```

When several services ship together, promote in dependency order (services before the clients
that call them) and keep that order in a registry file the promotion script reads. Never
hand-edit a migration between stage and main. Edge platforms can serve the old version for a
few seconds after deploy; re-probe before declaring failure.

Branch-deployed frontends promote by branch (`main` → production build): confirm the
production deployment id and that the production alias serves the new sha; environment
variables are often baked per deployment. Store-reviewed releases (plugins, mobile apps) are a
separate track with their own review and are not part of the promotion script.

## Record it

- `release.md` in the feature folder from `assets/release-template.md`: what shipped, PRs,
  stage/prod commits, deploy ids, production state (what is dark, shadow, on), smoke/UAT
  results, docs, follow-ups, and the three-line retro.
- A release note in your ops repo's release log (`docs/releases/<YYYY-MM-DD>-<slug>.md`) in
  the house style.
- **Follow-ups into the ledger.** Every flag left dark, PR held, case not run, risk accepted
  "for now" and the 48-hour watch: `followups.py --add <slug> --what "..." --trigger <date or
  event> --owner founder|orchestrator|agent`. Nothing is "left behind" in prose only; the hub's
  "Waiting on" section is where it is found again.
- Docs: the docs-site PR merged and live (check the page), the service README current, the
  operator runbook under `docs/runbooks/<slug>.md` committed; or the plan's "no docs" reason
  repeated in `release.md`.
- Check that the promotion script wrote its deploy-ledger row.
- STATUS.md final line, `plan.md` status "Released <date>", `links.json` "releases" and
  `stage.current`.
- **Retro, three lines** in `release.md`: what the pipeline got wrong or slow, what to change
  in the skill (and commit that change to your copy of the skill now, with the sha in the retro
  line), what to keep doing.
- Project memory / notes: update or add the entry for the feature (what shipped, where the
  folder is, decisions taken, open follow-ups).

## If it goes wrong

A hotfix path exists for a fix that must skip the queue (same gates, shorter queue); roll back
by promoting the previous sha the same way, never by force-pushing `main`. Write the incident
into STATUS.md and, if user-visible, into your incident log.
