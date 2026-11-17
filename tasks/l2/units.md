# Launch 2: units, file owners, read lists, gates

Read with `tasks/l2/agent-rules.md` and `tasks/l2-contract.md`. One writer per file. Checkpoint of unit X:
`/home/drtnarg/coding/telcoin/devnet-genesis/tasks/ckpt-l2-X.md`. Scratch of unit X:
`/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/X/`.
"Facts" = files under `/home/drtnarg/coding/telcoin/devnet-genesis/tasks/l2/facts/`. Every unit may read its own
repo's `.claude/project-context.md`.

## tn-node-deployment (TND = /home/drtnarg/coding/telcoin/tnd-l2-gateway)

Gates for every TND unit, on each file it wrote (CI lints take their file list from `git ls-files`, and you may
not `git add`, so pass paths explicitly):
`bash -n F` · `shellcheck -x --severity=error F` (must be clean) and `shellcheck -x --severity=warning F` (report
the count; no new warning in lines you wrote) · `bash tools/check-bash32.sh F` · `bash tools/check-perl-interp.sh F`
· `bash tools/check-network-hits.sh` · the fixture tests named for the unit with `bash tools/tests/run.sh <file>`.
Never touch `MANIFEST`, `MANIFEST.asc`, `RELEASE`, `install.sh`, any `*.sha256` (unit F2 alone refreshes sidecars).
Do not bump a version line unless the row says so.

| Unit | Writes | Contract | Facts | May read (TND, by range) | Depends on |
|---|---|---|---|---|---|
| C1 | `lib/common.sh` | §2 | tnd-template §5-6, tnd-firewall §3 | `lib/common.sh` (grep-first), `lib/alerts.sh` head and tail | none (first) |
| A1 | `lib/gateway.sh` (new) | §1, §2, §3.3, §3.4 | gateway-binary, tnd-template §4-6, gateway-help.txt | `lib/alerts.sh`, `lib/common.sh` (helpers named in the facts) | names of C1 |
| A2 | `setup-gateway.sh` (new) | §2, §3.1, §3.2, §3.3 (signatures) | tnd-template §1-3 | `setup-alerts.sh`, `install-caddy.sh` 2625-2650 (consent pattern) | names of C1, A1 |
| B | `install-caddy.sh` | §2, §4 | tnd-caddy | `install-caddy.sh`, `tools/tests/caddy_test.sh` (read only) | names of C1 |
| C2 | `firewall-setup.sh` | §2, §5 | tnd-firewall | `firewall-setup.sh`, `lib/common.sh` 9430-9660 | names of C1 |
| C3 | `edit-config.sh` | §2, §5 | tnd-node §4-5, §7 | `edit-config.sh`, `lib/common.sh` 9750-10330 | names of C1 |
| D1 | `check-node.sh` | §2, §6 | tnd-template §4 (status), tnd-caddy §2 | `check-node.sh` | names of C1 |
| D2 | `remove-node.sh` | §2, §6 | tnd-template §4 (remove) | `remove-node.sh` | names of C1 |
| E1 | `tools/tests/gateway_setup_test.sh` (new), `tools/tests/addon_oldlib_test.sh` | §3, §7 | tnd-template §8 | A1 + A2 output, `tools/tests/lib.sh`, `alerts_test.sh`, `setup_alerts_test.sh` | A1, A2, C1 |
| E2 | `tools/tests/caddy_gateway_test.sh` (new), `tools/tests/caddy_test.sh` (only what B broke) | §4, §7 | tnd-caddy §7 | B output | B, C1 |
| E3 | `tools/tests/gateway_validator_test.sh` (new); only what C1-C3 broke in `firewall_reset_test.sh`, `p2p_committee_mode_test.sh`, `fwstub.sh`, `edit_config_*_test.sh`, `lib_skew_test.sh`, `primitives_test.sh` | §2, §5, §7 | tnd-firewall §7, tnd-node §8 | C1-C3 output | C1, C2, C3 |
| E4 | `tools/tests/gateway_check_remove_test.sh` (new); only what D1/D2 broke in `check_node_*_test.sh` | §6, §7 | | D1, D2 output | D1, D2, C1 |
| E5 | `tools/tests/gateway_smoke.sh` (new) | §1, §3.3, §7 | gateway-binary, image-probes | `lib/gateway.sh` | A1, IMG |
| F1 | `OPERATOR.md`, `README.md`, `CHANGELOG.md`, `AGENTS.md` | all TND sections | | the finished scripts' usage headers | all code units |
| F2 | `update-scripts.sh`, version lines of the scripts this PR changed, every `*.sha256`, `tools/tests/updater_manifest_test.sh` if it must | §7 | tnd-template §7 | `AGENTS.md` 320-345, `tools/gen-checksums.sh` | everything else (last) |

A unit that starts before C1 has landed must not edit `lib/common.sh`: it uses the names of contract §2 and, to
run its own code early, defines throwaway doubles in its scratch dir.

## telcoin-network (TN = /home/drtnarg/coding/telcoin/tn-l2-img)

| Unit | Does | Output |
|---|---|---|
| IMG | builds node image, gateway image, node-record-api; probes; smoke | `tasks/ckpt-l2-IMG.md`, Facts `image-probes.md`, `gateway-help.txt`, `node-help.txt`, `keytool-help.txt`, `node-record-api-help.txt` |
| RH0 | local run: epoch-0 `committee_peers` rule; node 5's native join config; rpc-6 Open and trusted | `tasks/l2/rh0-report.md` (amends contract §9 through the orchestrator) |

## devnet-genesis (DG = /home/drtnarg/coding/telcoin/dg-l2)

Gates for every DG unit, on each script it wrote: `bash -n F` · `shellcheck -x F` (no new finding in lines you
wrote; report the count before and after) · `bash tasks/check-bash-portability.sh F` (run from DG) · for Python
`python3 -m py_compile F` · the tests named in the row. Units whose file is on the bench path (marked B) also run
the named bench tests from DG, never from the main tree, and must leave them passing unmodified:
`python3 -m unittest discover -s benchmark/tests -p '<pattern>'` (if the suite needs something that is missing
on this host, say exactly what, do not install it).

| Unit | Writes | Contract | Facts | May read | Depends on |
|---|---|---|---|---|---|
| G1 (B) | `config.sh`, `devnet-lib.sh`, `benchmark/config.sh` | §8 | dg-core §1-3, §7 | those files; `common/create-instances.sh` 80-180, `common/reserve-static-ips.sh` | none (first) |
| G2 (B) | `devnet-keygen.sh`, `devnet-genesis-build.sh` | §8, §9 | dg-drivers §1-2, keytool-help.txt, tnd-node §1 | those files; TND `setup-node.sh` 1-190 | G1 |
| N1 (B) | `devnet-network-config.py`, `benchmark/tests/test_network_config.py`, new fixtures under `benchmark/tests/fixtures/network-config/` | §9 | dg-core §6, node-side §4, tnd-node §3 | those files | G1 names |
| N2 (B) | `devnet-network-config.sh` | §8, §9 | dg-core §6 | that file, N1's CLI | G1, N1 |
| Z1 (B) | `devnet-finalize.sh` | §8, §9 | dg-core §5, tnd-node §1-3 | that file; `benchmark/tests/test_finalize_modes.py` (read only); TND `setup-node.sh` ranges for the finalize flags | G1, N1 |
| Z2 | `devnet-postcheck.sh` (new) | §1, §3.2, §8, §10 | gateway-binary §2-3, §6 | `devnet-lib.sh`, `devnet-finalize.sh` 700-830 (check style) | G1 |
| GW | `devnet-gateway.sh` (new) | §3.1, §3.2, §4, §5, §8, §10 | tnd-caddy §1, §4 | `devnet-lib.sh`, `devnet-firewall.sh` (driver style) | G1 |
| PC | `devnet-p2p-committee.sh` (new) | §1, §8, §10 | tnd-firewall §5-6, node-side §3 | `devnet-lib.sh`, `devnet-observability.sh` (sweep style) | G1 |
| FW | `setup-firewall.sh`, `devnet-firewall.sh` | §8, §10 | dg-drivers §3 | those files | G1 |
| SU | `devnet-startup.sh` | §10 | dg-drivers §4 | that file | none |
| SK | `devnet-stake-node5.sh` | §8, §10 | dg-drivers §7 | that file, `devnet-stake-node5.py` (read only) | G1 |
| TX | `devnet-txgen.sh` | §10 | dg-drivers §8 | that file | none |
| TD | `devnet-teardown.sh` | §8, §10 | dg-drivers §5, §10 | that file; `common/setup-load-balancer.sh` (read only) | G1 |
| RS | `devnet-release-sign.sh` | §8, §10 | dg-drivers §6 | that file | G1 |
| OB | `devnet-observability.sh`, `devnet-dashboards.sh` | §4, §8, §10, §13 | dg-drivers §9, tnd-node §6, tnd-caddy §5 | those files; `devnet-admin-secret.sh` (read only); TND `setup-observability.sh` | G1 |
| SH | `tasks/l2-shim/**` (new) | §10, §11 | dg-core §2, §4 | `devnet-lib.sh`, `devnet-deploy.sh`, `benchmark/tests/fixtures/*/fake-gcloud.py` (style only) | G1; finishes after DP |
| DP | `devnet-deploy.sh` | §8, §11 | dg-core §4 | that file | G1; the drivers' CLIs from §10 |
| DOC | `docs/mainnet-simulation-plan.md`, `tasks/runbook-reset-2026-10-30.md` (§7 wording only); and in the MAIN tree the new file `tasks/runbook-l2-2026-11-17.md` | all | all | plan `tasks/l2/plan-approved-2026-11-17.md` | last |

G1's bench proof: before editing, and again after, run from DG
`env -i HOME="$HOME" PATH="$PATH" BENCH_ALLOW_INTERACTIVE=1 bash -c 'set -a; CONFIG_FILE=benchmark/config.sh; source benchmark/config.sh >/dev/null 2>&1; declare -p' | grep -v -E '^declare -[a-zA-Z-]* (BASH|SHLVL|PWD|OLDPWD|_|PPID|EUID|UID|RANDOM|SECONDS|LINENO|FUNCNAME|PIPESTATUS|GROUPS|DIRSTACK|HOSTNAME|HOSTTYPE|MACHTYPE|OSTYPE|IFS|OPTERR|OPTIND|PS4|SHELLOPTS|BASHOPTS|TERM)'`
into two files in its scratch dir (adapt the invocation if the config refuses it, and say how), then `diff` them.
Every differing line is either a new variable of contract §8 that no `benchmark/` script reads (show the grep) or
a defect to fix. The diff goes into the hand-back.
