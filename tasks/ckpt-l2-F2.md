status: done
updated: 2026-11-17T21:26:21Z
unit: F2 (release files of TND branch worker-gateway, /home/drtnarg/coding/telcoin/tnd-l2-gateway)

## Completed sections
- 0 reading (rules, contract s7, units row, fact sheet s7, AGENTS.md, gen-checksums, CI, history)
- 1 update-scripts.sh: rows after lib/tn-heartbeat.sh row; gateway_changed on setup-gateway.sh|lib/gateway.sh; hint printed when telcoin-gateway.service exists
- 2 versions 2.1.0->2.2.0 in check-node, edit-config, firewall-setup, install-caddy, remove-node, update-scripts, lib/common (_file_version verified 2.2.0 for all 9)
- 4 tools/tests/updater_manifest_test.sh: GATEWAY block (rows after lib/tn-heartbeat.sh, versions, hint 5 cases, 17 checks); run alone rc=0 275 checks 0 failures. lib_skew_test SCRIPTS is its own tn_require_fns list (not the updater list): unchanged
- 5 git grep setup-alerts.sh (non-md, non-tests): MANIFEST:36 ceremony (untouched); check-node/lib/alerts/lib/tn-heartbeat/remove-node/setup-alerts/setup-node: alerts' own text or alerts integration, no script list -> no change; setup-alerts.sh.sha256 -> step 3; update-scripts.sh:288,1107-1110 done. CI (.github/workflows/ci.yml) uses git ls-files '*.sh' globs; .gitattributes only docs/partner pdf; no UI hit -> nothing else to list
- 3 sidecars: bash tools/gen-checksums.sh rc=0 (44). Step changed only sidecars: 8 M (check-node, edit-config, firewall-setup, install-caddy, lib/common, remove-node, update-scripts, ui/requirements.txt) + 2 new (setup-gateway.sh.sha256, lib/gateway.sh.sha256). ui/requirements.txt.sha256 was STALE ON origin/main since dependabot 2813343 (#63) -> CI checksums would fail on any PR/main push without it

## Decisions (evidence)
- Versions: move IN the change. AGENTS.md:833-838 "after you edit any tracked file: 1. Bump its version constant ... 2. gen-checksums and commit sidecars"; history: dc5a023 "chore(release): scripts-v2.1.0 versions and checksums" (2026-11-03) sits in feature PR #59 hardening-followups, bumped only changed files' constants + sidecars; release ceremony b89ada4 (#65) touched only MANIFEST, MANIFEST.asc, RELEASE, install.sh, README/OPERATOR, install_test. New alerts files carried 2.1.0 in their adding commit 2a79b24, before release 2.1.0 existed -> new files at 2.2.0 OK.
- Bump to 2.2.0: check-node.sh, edit-config.sh, firewall-setup.sh, install-caddy.sh, remove-node.sh, update-scripts.sh (SCRIPT_VERSION), lib/common.sh (COMMON_VERSION). New: setup-gateway.sh:90, lib/gateway.sh:52 already 2.2.0 and first assignment.
- Sidecars: in the branch. CI job 'checksums' (.github/workflows/ci.yml:216-240) runs on pull_request, runs gen-checksums and fails on any git status change. AGENTS.md:335 "final chore(release) commit of a change, never a feature commit" = a final chore(release) commit in the PR branch (history: 599929c/cd0b252/af604e9 inside PR #62; ddeea7b "refresh the checksums for the alerts files"). Not a real conflict with gen-checksums.sh:11-13: per-change vs per-commit timing only; CI judges the PR head.
- Hook marker: literal ${TN_ROOT_PREFIX:-}/etc/systemd/system/telcoin-gateway.service (like alerts/p2p-allow hooks; updater does not source lib/common.sh).

## Checks so far
- gates: bash -n 8 files rc0; shellcheck -x --severity=error rc0; warnings in update-scripts.sh 6 = HEAD 6 (pre-existing); check-bash32 rc0; check-perl-interp rc0
- CI checksums emulated on a copy of the tree: gen-checksums produced no diff; sha256sum -c 44/44 ok; no MANIFEST/RELEASE/install.sh change
- full suite bash 5.3.9: 79 files, 0 failed, EXIT=0; bash:3.2 docker (local image, --network none, ro): 79 files, 0 failed, EXIT=0

## Next
- none: hand back sent
- 1 update-scripts.sh rows + hook; 2 version lines; 3 sidecars; 4 updater tests; 5 git grep setup-alerts.sh; checks
