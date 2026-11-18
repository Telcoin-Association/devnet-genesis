# gen-checksums.sh and AGENTS.md disagree on when .sha256 sidecars change, and main's ui/requirements sidecar is stale

Two rules for the same files contradict each other: `tools/gen-checksums.sh` says to refresh the sidecars after any edit, `AGENTS.md` says only the final `chore(release)` commit refreshes them.
Contributors and bots following either rule meet it; on `main` today a sidecar is stale, so the CI checksums job fails on pull requests until a branch refreshes it.

## What happens

The rule in `tools/gen-checksums.sh`:

```
# drifts from what operators receive. CI runs this and fails if any sidecar is stale
# or missing (see .github/workflows/ci.yml), so AFTER EDITING ANY TRACKED FILE you
# must re-run this and commit the refreshed sidecars.
```

The rule in `AGENTS.md`:

```
- The touched scripts' `.sha256` sidecars are refreshed by the final `chore(release)` commit of a change, never by a feature commit (`tools/gen-checksums.sh`).
```

A change made the second way leaves stale sidecars between its feature commits and its release commit, and CI (by the first rule) fails in between. A change that does not end in a release commit, such as a dependency bump, leaves them stale on `main`.

That is the state of `main` at 2813343: the dependabot bump of `click` (#63) changed `ui/requirements.txt` and not its sidecar. `ui/requirements.txt.sha256` holds `6e7ec83c7908…`, while the file hashes to `970e7eeb2a92…`. Any pull request based on `main` then fails the checksums job until it refreshes that sidecar itself.

## Evidence

- Hashes, checked here: `git -C tn-node-deployment show <ref>:ui/requirements.txt | sha256sum` against `git show <ref>:ui/requirements.txt.sha256`, at `origin/main` (differ) and at PR #68's head (equal, both `970e7eeb2a92…`).
- The same values were found on 2026-11-17 while preparing PR #68's branch (row 46 of the run's challenge list: sidecar `6e7ec8…`, file `970e7e…`).
- That #63 is the change that left it stale, and that the CI job fails on every pull request because of it, are taken from that row; the CI run was not re-read here.

## Where in the code

- `tools/gen-checksums.sh:11-13` and `AGENTS.md:335`: the two rules above, identical at `origin/main` 2813343 (scripts 2.1.0) and at PR #68's head 79fb24e (scripts 2.2.0). The conflict is on both.
- `ui/requirements.txt.sha256`: stale on `main` only; PR #68 refreshes it with the other sidecars.

## What is not known

- Which rule the maintainers mean to keep.
- Whether dependabot pull requests can be made to run `tools/gen-checksums.sh` (or whether CI should exempt them).

## What could be done (suggestions, none tried)

- Pick one rule and state it in both places. If sidecars move only at release, CI's stale-sidecar check could run on release commits and tags only; if they move with every edit, `AGENTS.md:335` should say so.
- Refresh `ui/requirements.txt.sha256` on `main` without waiting for PR #68, so open pull requests stop failing.

## Related

- PR #68 fixes the stale sidecar (row 46) but not the conflicting rule (row 22).
