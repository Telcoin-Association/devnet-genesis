# Sources for tasks/pr-bodies/l2-tnd-worker-gateway.md

TND = /home/drtnarg/coding/telcoin/tnd-l2-gateway (branch worker-gateway, 22 commits over origin/main at 6361c9c).
OP = TND/OPERATOR.md (section 4.15 is lines 1623-1969). SG = TND/setup-gateway.sh. T = devnet-genesis/tasks.
Commit bodies: `git log --reverse --format='--- %h %s%n%b' origin/main..HEAD` in TND.
Suite log = T/l2/tnd-suite-20261117T2104Z.log.

## Opening
- worker-gateway: submissions to one node's worker, every other call proxied to a query endpoint: OP:1625-1628; SG:7-10
- scripts had no support (no installer, service, Caddy site, firewall rule, checks): T/challenges-l2.md row 1
- two layouts (same-host; standalone in front of a validator's private IPv4): SG:16-19; commit 912b9b1
- no released image; devnet only today; testnet/mainnet refuse until a release pins a digest: OP:1636, 1658-1659

## What is added
- four actions, each with --json, shape of setup-alerts.sh; exit 0/1/2/3 meanings: commit 17e6776; SG:82-84; OP:1942
- service telcoin-gateway.service, host network, uid 1101, read-only, no capability, --pull=never: commit 912b9b1; OP:1934
- settings in /etc/telcoin/gateway/gateway.meta: OP:1933; commit 912b9b1
- never stops/starts/restarts the node, never edits launch file or .node-meta, never opens a firewall port: SG:78-80; OP:1635
- unchanged inputs change nothing; failure after first write puts previous unit+meta back: commit 912b9b1; OP:1720-1721
- runs on a host with no node, unlike other add-ons: commit 17e6776
- --front caddy default https://<domain>/; --front none 0.0.0.0:8655 plain HTTP, firewall is the operator's: OP:1647-1648; SG:12-14
- probe 8656 and metrics 9655 on 127.0.0.1: OP:1650; SG:58-59
- tn-gateway block + phases gateway-status/check-dns/enable/disable: commit 6b01c10
- block: POST, 2 MB body cap, GET/HEAD probe paths to probe listener, CORS preflight, 405 + Allow for WS and other methods: OP:1724
- gateway-enable on node-less host, no-op when block current and Caddy runs, starts a stopped Caddy: commit 6b01c10; commit ce44d15 ("gateway-enable starting a stopped Caddy"); OP:1705
- rpc-advertise/unadvertise: https://<host>/, no WS URL, node-info.yaml, one guarded restart, no Caddy change: OP:1827-1831; commit 6b01c10
- rpc-advertise refuses unless https://<host>/health answers 200 from the node host: commit ce44d15; OP:1824
- public-RPC site and gateway never on one host: OP:1836; commit 6b01c10
- --gateway-from <ipv4|cidr,...>|none with --enable/--reset: commit 52e71ba; firewall-setup.sh:4337-4338 (flag parse)
- two rules per source (RPC port, health port), every network, after the health-port block: commit 52e71ba; OP:1740
- stored as GATEWAY_ALLOW_FROM, re-applied by every --enable/--reset like SSH/P2P lists: commit 52e71ba; OP:1741
- refused while GATEWAY_UPSTREAM set: none, list leaving out bound host, --reset: commit 2329dfc; OP:1802
- node-less host: --enable applies SSH and with Caddy site 80/443; SSH list kept in gateway.meta: OP:1782-1784; commit 2329dfc
- gateway_upstream sets --http.addr 0.0.0.0 and --healthcheck 0.0.0.0:43174, records previous --healthcheck: OP:1750
- no public-RPC limit flags, no --http.api: OP:1751; commit 684199e
- refused unless ufw active + both rules for every address: OP:1752; commit 684199e
- refused unless default incoming deny/reject and no Anywhere rule to either port: OP:1753; commit ae6918a (tn_gateway_ports_private)
- refused when RPC already on every interface: OP:1754; commit ae6918a
- refused while starting/stopping/awaiting auto-restart: OP:1757; commit ae6918a
- running node restarts after quorum check + epoch wait; stopped stays stopped: OP:1756
- off: --http.addr back to 127.0.0.1, --healthcheck to recorded value: OP:1799
- check-node gateway section (service, image held, 3 listeners, /health, Caddy block, same-host health port; /ready not counted): OP:1865-1866; commit 73c78a1
- check-node upstream section (rules per host, binds vs GATEWAY_UPSTREAM, firewall admitting more, https URL no WS): OP:1868-1869; commit 73c78a1, ae6918a
- gateway-only host skips node sections: OP:1867
- remove-node removes same-host gateway before stopping node, like private alerts: OP:1911
- keeps image + Caddy site and names commands; warns about advertisement: OP:1912-1913
- never removes a standalone gateway; leaves node leftovers on such a host; points at setup-gateway.sh --remove: OP:1914-1915; commit ce44d15; remove-node.sh:1528
- update-scripts: two files join the list; prints --refresh on a host with the gateway's unit, never runs it: commit af0dc90; update-scripts.sh:1115-1118
- update leaves unit, gateway.meta, container as they were: OP:1893
- version constants to 2.2.0; sidecars refreshed incl. two new; ui/requirements.txt.sha256 stale since #63: commit 3c9eb07; SG `readonly SCRIPT_VERSION="2.2.0"`
- docs: OPERATOR 4.15, README table, CHANGELOG entry, AGENTS.md rules: commits 10c2ddc, 320b6fb; README per-script changelog entries and CHANGELOG/scripts-v2.2.0.md release note: commit 6361c9c

## The two shapes (commands)
- same-host commands: OP:1681, 1688-1690, 1709, 1821 (rewritten without ~/telcoin-node-scripts/)
- testnet health add-on adds --healthcheck, elsewhere by hand: OP:1677
- same-host refused on mainnet; standalone only mainnet layout: OP:1642-1643
- standalone example addresses 10.0.0.12 / 10.0.0.20 / gw.example.org: OP:1727
- order matters, validator refuses to listen until firewall admits: OP:1730
- standalone commands: OP:1737, 1747, 1764-1767, 1779, 1821; --network required: OP:1761
- undo commands and order: OP:1790-1797, 1804
- flags grepped present: install-caddy.sh gateway-check-dns, --gateway-domain, --rpc-domain, rpc-advertise, rpc-unadvertise; firewall-setup.sh --gateway-from, --ssh-from; edit-config.sh gateway_upstream; SG --mode/--network/--upstream/--domain/--image/--redirect-queries/--remove/--status (checked with grep -c, all > 0)

## Behaviour for existing operators
- stale-source compare literal; ufw stores /32 bare, CIDR by network address: commit 2329dfc; CHANGELOG (+ "Fix for every operator"); OP:1742
- trigger: re-entering a source in the other spelling; allow skipped as existing, then delete removes the same rule: commit 2329dfc; T/l2/review-R1a.md:24-37 (H2)
- lockout for SSH list: commit 2329dfc; T/challenges-l2.md row 40
- ufw 0.36.2, Ubuntu 24.04 container: port-22 rule added 1.2.3.4/32 removed by delete written bare; reverse also: T/ckpt-l2-FX-A1.md:4-9
- one comparison for SSH, P2P, gateway lists, health-port keep check, fixed SSH range skip: T/ckpt-l2-FX-A1.md:12,15 (fw_src_canon/fw_src_in used by fw_stale_sources, fw_health_keeps, SSH fixed-range skip); commit 2329dfc
- "a list re-entered in the same spelling was never affected": inferred from the mechanism (literal compare matches) — not separately run
- every Caddy writer three blocks; clash check and teardown count three: commit 6b01c10; CHANGELOG ("Nothing changes ... except")
- rpc-disable leaves an rpc-advertise advertisement alone (RPC_ADVERTISED_VIA=gateway): OP:1833; CHANGELOG
- rpc-enable refuses while gateway site or advertisement present: CHANGELOG; OP:1833
- --json --status gains gateway_from; status screen and expected rules two rows per source: CHANGELOG; commit 52e71ba
- Caddyfile with gateway block = public edge, 80/443 survive reset: commit 52e71ba; CHANGELOG
- fixture: ufw calls of host without the key equal a recorded baseline: commit 405af9e
- custom-install scan matched gateway image name, now knows unit/container: commit a1e40d2; CHANGELOG
- edit-config other keys as before incl. restart of stopped node on --set: commit 684199e ("Other keys behave as before"); T/challenges-l2.md row 16 (read from code)
- lib/common.sh sources lib/gateway.sh at the end like lib/alerts.sh: commit 9d71e2f
- update-scripts installs the two files on every host: inferred from commit af0dc90 "join the updater's list" (not run); refresh print only on host with the unit: commit af0dc90

## Image trust
- digest only, tag refused: OP:1655; SG:42
- devnet repository us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway: OP:1656; lib/gateway.sh:56 (GW_DEVNET_IMAGE_REPOS)
- testnet/mainnet pins GW_TESTNET_IMAGE_PIN / GW_MAINNET_IMAGE_PIN, both empty: lib/gateway.sh:60, 62; gw_image_allowed lib/gateway.sh:451-466
- refusal text "this scripts release pins no worker-gateway image for <network>": lib/gateway.sh gw_image_allowed (GW_ERR); OP:1658
- pulls if absent, runs --help, refuses missing flag; service never pulls: OP:1660-1661
- --help under a time limit: commit ce44d15 ("a time limit on the image's --help probe"); review-R1b L9
- node host: network must equal node's; --refresh refuses other: OP:1719, 1891; commit ce44d15
- node-less: eth_chainId must fit; 3 s no answer only warns; --status re-checks: OP:1770-1772; commit ce44d15
- pin change: --refresh without --image moves; --status counts old image: OP:1890, 1895; commit ce44d15
- no CI job builds the image; --version prints tn-worker-gateway 0.1.0, no commit: T/challenges-l2.md rows 2, 29

## How it was tested
- check counts (bash 5.3.9): Suite log lines 790 (caddy_gateway_test 233), 3018 (gateway_check_remove 115), 3046 (gateway_remove 23), 3535 (gateway_setup 475), 3649 (gateway_upstream 109), 3868 (gateway_validator 214)
- file coverage descriptions: commits e603fd5, e4d87e0, 405af9e, 36eedd6, ce44d15 (gateway_remove_test.sh added there)
- 79 test files, 0 failed (bash 5.3.9): Suite log:9964-9965
- suite tree = "ae6918a + uncommitted FX-B and the fixture fix": Suite log:1; ce44d15's file list equals the log's modified list (git show --stat ce44d15)
- later commits: 320b6fb (AGENTS/CHANGELOG/OPERATOR only), 3235451 (mode only), af0dc90 (update-scripts.sh + updater_manifest_test.sh), 3c9eb07 (version lines + sidecars), 6361c9c (CHANGELOG.md, CHANGELOG/scripts-v2.2.0.md, README.md only): git show --stat
- updater test result not in the run: suite log precedes af0dc90 (log at 21:04Z; af0dc90 not in the log's tree)
- fwstub UFW_NORMALIZE=1, default off: T/ckpt-l2-FX-A1.md:21; grep TND/tools/tests/fwstub.sh
- before the fix: 214 checks, 32 fail: T/ckpt-l2-FX-A1.md:22
- bash 3.2: FX-A1:24 (gateway_validator under bash:3.2 exit 0); T/ckpt-l2-FX-A2.md:2 ("bash 3.2.57 run green"); T/ckpt-l2-FX-B.md:3 ("bash3.2 rc 0"); no whole-suite 3.2 log among the files read
- addon_oldlib_test.sh / host_baseline_test.sh adjusted: commits e603fd5, e4d87e0
- smoke scripts need docker, exit 77, not picked up by run.sh: commit 463e7d8 (gateway_smoke 77); commit e4d87e0 (caddy smoke not in run.sh); grep -c 77 in both smoke files > 0
- gateway_smoke: render_args line + unit docker options vs stubs on loopback: commit 463e7d8; T/ckpt-l2-E5.md run 3 output
- "locally built image": E5 does not name the image; T/l2/rh5-report.md:4 names gateway image worker-gateway@sha256:8b887098… for the rehearsal; no released image exists (OP:1659). Digest of the E5 run NOT recorded in E5.
- 43/43 runs 2 and 3; run 1 41/43 (stub Nagle delay, client not reopening), fixed in stub/client only: T/ckpt-l2-E5.md:5-7
- /ready 200 after 7 s: E5 "info: /ready answered 200 after 7s"
- 405 GET and WS, 413 over 1 MiB, metrics, stop exit 0: E5 run 3 check lines
- burst: 600 calls, t_a=0.121 s, a200=211, a429=389, bound=213, 200-token 100/s bucket, b200=50 of 50: E5 run 3 "info: burst" and "ok burst" lines
- limit keyed on forwarded client, not proxy: commit 463e7d8; E5 "198.51.100.8 in the same second: never throttled"
- caddy smoke: caddy validate + serve block vs stubs: commit e4d87e0
- 47/47 on 2.8.4 and on 2.11.9 (caddy:2), Valid configuration, XFF client 203.0.113.9 dropped (upstream saw 127.0.0.2), 3 MB POST 413: T/ckpt-l2-E2.md:5-6
- gw_render_args and write_gateway_block unchanged since the smoke commits: md5 of function bodies at 463e7d8 / e4d87e0 vs HEAD equal (run 2026-11-17)
- ufw 0.36.2 results (/32 bare, CIDR network address, re-add skipped, delete in either spelling): T/ckpt-l2-FX-A1.md:5-8
- rehearsal: 4 validators + RPC node, gw1-4 standalone --front none, gw_validate_inputs + gw_render_args, unit docker options, bridge network: T/l2/rh5-report.md:42-48, 54
- tx forwarded via record URL -> gateway -> worker, block 2; 20/20 in about 1 s; 400/400 in 4.65 s; 8 threads: rh5-report.md:9-11, 110
- ready 11 s after gateway start: rh5-report.md:56
- two earlier rehearsals: genesis and admission: T/l2/rh0-report.md:1, rh3-report.md:1
- not run (systemd, real docker daemon for setup-gateway.sh, ACME, real-host ufw via scripts, macOS bash, mainnet-like standalone e2e, INT/HUP): orchestrator brief; T/l2/review-notes.md ("E1 not covered: docker not installed refusal; signals INT/HUP; macOS /bin/bash"); fixture tests "without root, docker or network" commit e603fd5
- scan_custom_installs reads the real /etc/systemd/system: T/l2/review-notes.md (E4 line)
- CI not run: `git ls-remote --heads origin worker-gateway` empty (branch not pushed) at writing time

## Review
- two reviews, scopes: T/l2/review-R1a.md:1-13; review-R1b.md:1-12
- read at 405af9e (before fix commits): review-R1a.md:7; review-R1b.md:11
- counts High 3, Medium 4, Low 12 (R1a) + High 0, Medium 4, Low 13 (R1b) = 3 / 8 / 25: review-R1a.md:13; review-R1b.md:13
- High titles: review-R1a.md:16, 24, 38
- Medium titles: review-R1a.md:49, 59, 70, 79; review-R1b.md:24, 46, 62, 82
- each High/Medium fixed with a test: T/ckpt-l2-FX-A1.md:13-22 (H1, H2, H3, M3 + tests); FX-A2:2 (M1, M2, M4 "code + tests"); FX-B:3 (M1-M4, tests); commits 2329dfc, ae6918a, ce44d15
- 14 Lows fixed: R1a L2, L3, L5, L11 (FX-A2:2), L6 (FX-A1:20); R1b L2, L3, L5, L6, L7, L8, L9, L10, L12 (FX-B:3)
- 11 open: R1a L1, L7, L8, L9, L10 (FX-A1:27), L4, L12 (FX-A2:3); R1b L1, L4, L11, L13 (not in FX-B's list)

## Limits
- empty pins, devnet only: lib/gateway.sh:60, 62; OP:1636
- no rate-limit flag rendered; defaults: T/challenges-l2.md row 42; rh5-report.md:22
- 100 rps, 32 connections per client IP: OP:1634, 1920; SG:11; burst 200: challenges row 10, E5 "200-token" bucket
- batch of K costs K: OP:1925
- RPC node is one client: OP:1924; challenges row 10
- rehearsal burst: ~210 forwards to one gateway in a second, one 429, 30 s set-aside, 61 re-sent, none lost: rh5-report.md:19-21; challenges row 10
- 429 closes keep-alive without Connection: close; Caddy 502 not verified: challenges row 35; E5:9
- restarting gateway 503 ~11 s, 30 s set-aside: challenges row 44
- loopback redirect warns at every start; plain-http public redirect warns: challenges row 36
- rpc-advertise needs outbound HTTPS, no flag skips: challenges row 45; OP:1825
- same-host refused on mainnet: OP:1642; only testnet add-on adds --healthcheck: OP:1677 (challenges row 21 says "off testnet and devnet"; OP followed)
- standalone wildcard bind guarded by ufw; local readers hard-code loopback (read from code): challenges row 4
- firewall reset on bound validator = four commands; each gateway_upstream change restarts: OP:1805-1814
- older remove-node.sh leaves gateway running: OP:1917; older firewall-setup.sh --reset drops rules while bind stays: review-R1a.md:96 (L10)
- open Lows text: review-R1a.md:87 (L1), 94 (L8), 93 (L7), 95 (L9), 98 (L12), 90 (L4; FX-A2:3 "tn_launch_flag_set refuses"); review-R1b.md L1, L4, L11, L13 (lines 97-198)
- review list function names and lines: edit-config.sh:2834 set_gateway_upstream; lib/common.sh:11325 tn_gateway_from_rules_ok, 11377 tn_gateway_ports_private; firewall-setup.sh:583 fw_src_canon, 619 fw_src_in, 636 fw_stale_sources, 2265 fw_gw_upstream_guard; install-caddy.sh:882 caddy_write_managed; lib/gateway.sh:451 gw_image_allowed, 314 gw_validate_inputs; remove-node.sh:925 rm_leftovers_present, 970 remove_leftovers, 1563 remove_gateway

## Follow-ups
- image CI build + commit in --version: challenges rows 2, 29
- rate-limit option or forwarder passing client: challenges row 42
- setup-observability --json starts a stopped node (read from code): challenges row 37
- stale --healthcheck comments; --enable-health emits bare port: challenges rows 3, 38; T/l2/review-notes.md (E4 stale comments line)
- unknown flags silently ignored (read from code): challenges row 17
