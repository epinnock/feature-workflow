# Stage 4 - Security review

Run the built-in `security-review` skill on the feature branch (it reviews the pending
changes on the current branch) and the `code-review` skill at high effort for correctness.
Then go through the list below by hand. It should be **the defects your codebase has actually
shipped**, because a generic review may not weigh them the same way; here is a starting list,
and every incident or near miss adds to it. In practice this stage often finds a feature's
worst defect after the code is already merged to stage (a proxy traversal that reached an
internal admin route; a config store whose writers could change what an AI judge was told to
do). The guarantees written at Gate A and the `guarantee-N` tests in Stage 3 exist so that this
stage confirms rather than discovers.

## Guarantees first

For every row of the plan's "Guarantees" table: the test that proves it (name, file, what it
asserts, that it ran green on the branch), and what you read in the code to confirm the test
is not vacuous (the route, the check, the rule). A guarantee with no test, or a test that
passes for the wrong reason, is a finding, not a footnote.

## The checklist (start here, then make it yours)

1. **Membership on every route.** For each new route: who can call it, what proves it, and
   what an adjacent user's request returns. Test it with a stage account that owns nothing.
   Watch for ids that are derivable (a pair id built from two public ids is not a secret).
2. **No client-asserted identity.** A header or body field that says who the caller is, even
   behind a shared service key, is not identity. Identity comes from a verified session / ID
   token, a verified personal access token, or a signed caller assertion.
3. **Right token type for the job.** Each route says which credential it accepts (session
   token, personal access token, service bearer) and every caller uses that one. A mismatch
   fails quietly: e.g. a revoke route that accepts only session tokens while the client revokes
   with its PAT leaves tokens active after sign-out.
4. **Platform-level features need a platform-level gate.** Project or org roles do not cover
   "staff only". Use a server-checked claim; never an email list in client code.
5. **Secrets and logs.** No secret in a prompt, a PR body, a log line, a report, or a client
   bundle (public env-var prefixes are public by construction). Credential-shaped values are
   redacted before they are written anywhere.
6. **Aggregates leak too.** Counts and lists over all users or projects are cross-tenant data;
   they belong behind the platform gate and must not include per-user identifiers unless the
   viewer is allowed to see those users.
7. **Rules match routes.** A route that reads with an admin SDK bypasses database rules, so the
   route is the only gate; a client read needs a rule. Indexes and rules ship together.
8. **Input handling.** Path params validated (allow-list patterns for ids), no shell command or
   query built from raw strings, upload sizes bounded.
9. **Proxies and allow-lists.** A route that forwards to another service with that service's
   bearer is a new door into every route the service has; check the path allow-list, not only
   the auth on the front.
10. **Config-as-code surfaces.** Anything read at runtime from a place with its own writers
    (prompt registries, config documents, feature flags) is a second deploy path; say who can
    write there and what a hostile write does.
11. **Dependencies.** New packages: why, license, maintenance; pinned.

## Output

`security-review.md`:

```
# Security review - <feature> - <date>
Scope: PR #, commits, files.
Tools: security-review skill (N findings), code-review high (N findings).
## Guarantees
| # | Guarantee | Test | Ran on | Read in code | Held? |
Guarantees held: n/n
## Findings
| # | Severity | Where | What | Fix (commit) or accepted risk |
## Checklist
one line per item above: how it was verified
## Residual risk
what remains, who accepted it (a founder acceptance is a Gate B item, named as such)
```

After writing it, record `links.json` "guarantees": {"held": n, "total": n, "source": ...}.
Findings fixed on the branch go back through Stage 3's checks. A finding the founder must
decide on is an open decision for Gate B, not a silent acceptance.
