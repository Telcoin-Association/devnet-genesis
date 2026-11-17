# Figure-check: tasks/pr-bodies/l2-tnd-worker-gateway.md

Checked 2026-11-17 against TND `tnd-l2-gateway` at 6361c9c (22 commits over origin/main), the final evidence
`tasks/l2/tnd-final-6361c9c/` (summary.txt + logs), ckpt-l2-FX-A1/A2/B, review-R1a/R1b, rh5/rh3/rh0 reports.
Abbreviations: SG = setup-gateway.sh, GW = lib/gateway.sh, IC = install-caddy.sh, FW = firewall-setup.sh,
EC = edit-config.sh, OP = OPERATOR.md, FIN = tnd-final-6361c9c.

Totals: checked 113 | ok 87 | wrong -> corrected 9 | reworded 13 (over-strong 5, over-narrow 1, vague/missing -> exact 7) | not re-checked, kept 4 | not traceable, removed 0
Body after the fixes: 144 lines, 3 code blocks (6 fences), the forbidden-word grep finds nothing.

## Opening
1. gateway's role (submissions to one worker, rest proxied) -- SG:3-10 -- ok
2. scripts had no support before -- `git diff --name-status origin/main..HEAD` (all gateway files added) -- ok
3. two layouts -- SG:16-19 -- ok
4. no release; devnet only; testnet/mainnet refuse until pinned -- GW:56-62, 463 -- ok

## What is added
5. four actions, each `--json`; exit 0/1/2/3 meanings -- SG:21-26, 82-85 -- ok
6. telcoin-gateway.service, host network, uid 1101, read-only, no capability, --pull=never -- GW:572 (ExecStart) -- ok
7. settings in /etc/telcoin/gateway/gateway.meta -- GW (20 refs), OP:1703 -- ok
8. never stops/starts/restarts node, never edits launch file or .node-meta -- SG:78-80 -- ok
9. "never opens a firewall port" -- OP:1703 + IC do_gateway_enable (caddy_open_ports): the gateway-enable step setup-gateway runs opens 80/443 -- over-strong -> reworded "opens no firewall port itself (with --front caddy the gateway-enable step it runs opens 80 and 443)"
10. no-op enable; failure after first write puts unit+meta back -- OP:1720-1721, commit 912b9b1 (fixture-tested, not traced) -- ok
11. runs on a host with no node -- IC:3002-3008 caddy_gateway_gate; GW:338 -- ok
12. --front caddy default; --front none on 0.0.0.0:8655; probe 8656 / metrics 9655 on loopback -- SG:47-59, lib/common.sh:9201-9203 (defaults, overridable by --listen/--probe/--metrics-port) -- vague -> exact ("default")
13. tn-gateway block; phases gateway-status/check-dns/enable/disable -- IC grep (6/6/13/7 hits) -- ok
14. block: POST capped 2 MB, GET/HEAD on /health,/ready,/ready/any to probe, CORS preflight, 405 for WS and other methods -- IC:1335-1383 -- ok
15. gateway-enable on node-less host, no-op when current and running, starts stopped Caddy -- OP:1705, IC:3018-3090 -- ok
16. rpc-advertise/unadvertise: https://<host>/, no WS, node-info.yaml, guarded restart, no Caddy change -- IC:3250-3272 (`set "$domain" false`, "No Caddy file is read or written") -- ok
17. rpc-advertise refuses unless https://<host>/health 200 from the node host -- IC:3201-3247 -- ok
18. public-RPC site and gateway never on one host -- IC:2760, 3029 -- ok
19. --gateway-from <ipv4|cidr>[,...]|none with --enable/--reset; needs a node -- FW:2336-2342 -- ok
20. two rules per source, every network, after the health-port block -- FW:2831, OP:1740 (order not traced) -- ok
21. stored as GATEWAY_ALLOW_FROM, re-applied by every --enable/--reset -- FW:517-528, 2831, 2930 -- ok
22. refused while GATEWAY_UPSTREAM set: none, list without a bound host, --reset -- FW:2256-2287 fw_gw_upstream_guard -- ok
23. node-less host: --enable applies SSH and (with Caddy site) 80/443; SSH list in gateway.meta -- OP:1779-1784 -- ok
24. gateway_upstream: --http.addr 0.0.0.0, --healthcheck 0.0.0.0:43174, previous recorded -- EC:2815-2821 (comment), 2934-2936 (port = TN_KUMA_PORT, default 43174) -- ok
25. no public-RPC limit flag, no --http.api -- EC:2829-2830 -- ok
26. refused unless ufw active, both rules per address, default deny/reject, no Anywhere rule -- EC:2822-2826, 2910 -- ok
27. refused when RPC already on every interface -- EC:2916-2922 -- ok
28. refused while starting/stopping/awaiting auto-restart -- EC:3997-4012 -- ok
29. running node restarts after quorum check + epoch wait; stopped stays stopped -- EC:3972-3980, 4049 -- ok
30. off: --http.addr 127.0.0.1, --healthcheck to recorded value -- EC:2830-2832, 2857, 2863, OP:1799 -- ok
31. check-node gateway + upstream sections; /ready shown, not counted -- check-node.sh:2226, OP:1865-1869 -- ok
32. remove-node same-host removal, keeps image + Caddy site, standalone left alone -- OP:1911-1915 (functions exist; not traced) -- ok
33. update-scripts: two files join the list; prints --refresh, never runs it -- update-scripts.sh:1115-1118; updater_manifest_test "gateway hint" checks in FIN suite logs -- ok
34. update leaves unit, gateway.meta, container -- OP:1893 -- ok
35. version constants 2.2.0 in each touched script -- `git grep 2.2.0 HEAD`: 9 scripts (check-node, edit-config, firewall-setup, install-caddy, lib/common, lib/gateway, remove-node, setup-gateway, update-scripts) -- ok
36. sidecars refreshed + two new; ui/requirements.txt.sha256 stale since #63 -- name-status; origin/main 2813343 "bump click ... (#63)"; commit 3c9eb07 -- ok
37. docs list (OP 4.15, README, CHANGELOG, release note, AGENTS.md) -- name-status; OP:1623 "### 4.15 Worker gateway" -- ok

## The two shapes
38. same-host commands in order (check-dns, enable runs gateway-enable itself, status, rpc-advertise once /health answers) -- OP:1676-1712; flags grepped -- ok
39. same-host testnet/devnet only; --healthcheck by add-on on testnet, else by hand -- OP:1677; SG:16-17 -- ok
40. standalone order walked against refusals: --gateway-from before gateway_upstream (EC refuses without rules); --network required on node-less host (GW:338); firewall --enable after setup-gateway (takes network from gateway.meta, OP:1779-1781); rpc-advertise last (IC:3245) -- ok
41. "The undo runs in reverse" -- OP:1790-1797: the undo starts with --remove, not rpc-unadvertise, so it is not the exact reverse; off-before-none order is right (FW guard) -- over-strong -> reworded "The undo, with gateway_upstream=off before the rules go (--gateway-from none is refused while the node is bound)"
42. MANIFEST, MANIFEST.asc, RELEASE, install.sh untouched; 22 commits -- `git diff --stat` empty; `git log --oneline origin/main..HEAD | wc -l` = 22 (body states neither) -- ok

## Behaviour for existing operators
43. main compares stale sources as text for --ssh-from and --p2p-from -- `git show origin/main:firewall-setup.sh` 549-575 (`[[ "$n" == "$s" ]]`), called for ssh and p2p at 2164/2167 -- ok
44. ufw stores /32 bare, CIDR by network address -- FX-A1 step0 -- ok
45. "The trigger is re-entering a source ... in the other spelling" -- FX-A1: delete 10.0.0.9/24 removes the 10.0.0.5/24 rule, so any stale entry stored as the same rule as a kept one triggers it -- over-narrow -> reworded "a stale entry that ufw stores as the same rule as a kept one, most simply a source re-entered in the other spelling"
46. SSH lockout; port-22 rule added /32 removed by bare delete -- FX-A1 step0 ("SSH rule gone") -- ok
47. "the reverse spelling behaved the same" (for a port-22 rule) -- FX-A1: bare-add/`/32`-delete was shown on 10.0.0.7, not on a port-22 rule -- over-strong -> reworded "a rule added bare was removed by a delete written with /32"
48. a list re-entered in the same spelling never affected -- main's literal equality keeps it (read from code) -- ok
49. one comparison serves SSH, P2P, gateway lists, health keep, fixed SSH ranges -- FX-A1 "H2 done" line; FW:583-636 -- ok
50. three Caddy blocks; rpc-disable with RPC_ADVERTISED_VIA=gateway; rpc-enable refuses -- IC:2760-2764, 2911 -- ok
51. --json --status gateway_from; two rows per source; 80/443 survive reset; baseline fixture -- FW:4186, 3713; commit 405af9e -- ok
52. remove-node scan matched the image name, now knows it -- commit a1e40d2 (not traced) -- ok
53. edit-config other keys unchanged incl. restart of a stopped node (read from code) -- EC:3997-4004 ("gateway_upstream only") -- ok
54. lib/common.sh sources lib/gateway.sh at its end like alerts.sh -- tail of lib/common.sh -- ok
55. "update-scripts.sh installs the two new files on every host" -- inferred from the list rows (tested), install not run -- over-strong -> reworded "lists the two new files for every host, so it installs them where no gateway runs too (read from code)"

## Image trust
56. digest only, tag refused -- SG:22, OP:1655 -- ok
57. devnet repository value, GW_DEVNET_IMAGE_REPOS -- GW:56 -- ok
58. pins empty; refusal text -- GW:60, 62, 463 -- ok
59. pulls if absent, --help under a time limit, missing flag refused, service never pulls -- GW:508-534 (timeout 60 when `timeout` exists), 572 -- ok
60. network must equal node's; --refresh refuses another -- GW:328-334; OP:1891 -- ok
61. node-less: eth_chainId must match, 3 s no answer only warns, --status rechecks -- GW:260-298 -- ok
62. pin change: --refresh moves; --status counts old image -- GW:1050-1052; OP:1890, 1895 -- ok
63. no CI job builds the image; --version prints 0.1.0 without commit -- challenges-l2 rows (outside my read list) -- not re-checked, kept

## How it was tested
64. "counts from one run of the whole suite under bash 5.3.9", "all new" -- FIN summary: both shells on the head; the table now also has the extended updater test -- wrong -> corrected
65. bash 5.3.9 counts 475/233/214/115/109/23 -- FIN summary -- ok
66. bash 3.2.57 counts (470+3 skipped, 233, 214, 111+1 skipped, 109, 23; updater 275 / 271+2 skipped) -- FIN summary -- missing -> added as a second column
67. why 3.2 is lower -- suite-bash32.log SKIP lines: 3 + 1 "root reads a 0000 file"; updater 2 = gpg absent, git absent (not root) -- missing -> added, with the numbers
68. "79 test files, 0 failed (bash 5.3.9), on the tree that became the last gateway fix commit" -- FIN: head 6361c9c, both shells 79/0 -- wrong (superseded) -> corrected
69. "updater commit's checks not part of that run" -- FIN includes updater_manifest_test (275 / 271) -- wrong -> removed
70. "no whole-suite run under bash 3.2 is recorded" -- FIN suite-bash32.log, 79/0 -- wrong -> corrected
71. fwstub UFW_NORMALIZE=1, off by default -- tools/tests/fwstub.sh (2 hits); FX-A1 -- ok
72. before the fix: 32 of 214 failed -- FX-A1 -- ok
73. addon_oldlib_test.sh, host_baseline_test.sh adjusted -- name-status M -- ok
74. lints -- FIN "network-hits=0 checksums=0" -- missing -> added ("tools/check-network-hits.sh and the checksum check are clean")
75. smoke scripts need Docker, exit 77, not in run.sh -- headers of both scripts -- ok
76. "against a locally built worker-gateway image" -- FIN: us-docker.pkg.dev/telcoin-network/tn-public/worker-gateway@sha256:8b887098... (rh5 names the same digest prefix) -- wrong -> corrected
77. "43 checks, 43 passed on each of two consecutive runs" -- FIN gateway-smoke.log: one run on head, 43 checks, 0 failures, 0 skipped -- wrong (superseded) -> corrected
78. an earlier run failed 2 (stub delay, client not reopening) -- ckpt-l2-E5 (outside my read list) -- not re-checked, kept as "an earlier run, on an older tree"
79. /ready 200 about 7 s after the stub accepted -- gateway-smoke.log:15-16 -- ok
80. 405 GET and WS, 413 over 1 MiB, metrics, stop exit 0 -- gateway-smoke.log:29-31, 41-45, 48-50 -- ok
81. burst "600 in about 0.12 s, 211 x 200, 389 x 429, bound 213" -- gateway-smoke.log:35: t_a=0.105, a200=210, a429=390, bound=211 -- wrong -> corrected
82. second client 50 of 50 -- gateway-smoke.log:35 (b200=50, b429=0), :40 -- ok
83. limit follows the forwarded client -- gateway-smoke.log:40 -- ok
84. "tools/tests/caddy_gateway_smoke.sh <image>" -- script:14, 27 (TN_SMOKE_CADDY_IMAGE, default caddy:2.8.4; FIN notes an argument is ignored) -- wrong -> corrected
85. 47/47 on Caddy 2.8.4 and 2.11.9 -- FIN caddy logs (caddy:2.8.4 v2.8.4; caddy:2 v2.11.9; 0 failures, 0 skipped) -- ok
86. client X-Forwarded-For 203.0.113.9 dropped, upstream saw the connecting address -- caddy logs 28-33 ('127.0.0.2') -- ok
87. 3 MB POST got 413 -- caddy logs 51-52 (both versions) -- ok
88. "gw_render_args and write_gateway_block are unchanged since those runs" -- moot: FIN runs are on the head, "tracked files modified: 0" -- wrong (superseded) -> replaced
89. ufw paragraph (/32 bare, CIDR network, re-add skipped, delete either spelling) -- FX-A1 step0 -- ok
90. rehearsal setup (4 validators + RPC node, standalone --front none, gw_validate_inputs + gw_render_args, unit Docker options, bridge) -- rh5:36-48 -- ok; scope -- rh5:27-32, 39 -- missing -> added (plain http to private addresses, no Caddy/TLS/ufw, binds written by hand not edit-config.sh, allow_private_forward_targets: true on the RPC node only)
91. block 2; 20/20 in about 1 s; 400/400 in 4.65 s with 8 threads; ready about 11 s -- rh5:11, 56, 110-111 -- ok
92. earlier rehearsals "do not exercise the gateway code" -- rh0:25-29 (tn_network_config_render in lib/common.sh; on origin/main, `git diff origin/main..HEAD -- lib/common.sh` has no line of it) -- vague -> exact
93. not-run list; "macOS bash" -- bash 3.2.57 ran in a Linux container only -- vague -> exact
94. CI had not run -- branch not pushed per sources (no gh call made) -- ok

## Review
95. two reviews, scopes, read before the fix commits (405af9e) -- R1a:1-7, R1b:9-12 -- ok
96. 3 High, 8 Medium, 25 Low -- R1a:13 (3/4/12), R1b:13 (0/4/13) -- ok
97. every High and Medium fixed with a fixture test -- FX-A1 (H1-H3, M3), FX-A2 (M1, M2, M4), FX-B (R1b M1-M4) -- ok
98. High/Medium descriptions -- R1a:16-79, R1b:24-82 titles -- ok
99. 14 Lows fixed, 11 open -- fixed: R1a L6 (FX-A1), L2 L3 L5 L11 (FX-A2), R1b L2 L3 L5 L6 L7 L8 L9 L10 L12 (FX-B) = 14; open: R1a L1 L4 L7 L8 L9 L10 L12, R1b L1 L4 L11 L13 = 11 -- ok

## Limits
100. no image, empty pins, devnet only -- GW:60-62 -- ok
101. no rate-limit flag rendered; 100/s, burst 200, 32 connections; batch of K costs K -- gateway-smoke.log:2 (rendered args), :36; rh5:115; OP:1925 -- ok
102. rehearsal burst: ~210 forwards, one 429, 30 s set-aside, 61 re-sent, none lost -- rh5:19-21, 113 -- ok
103. 429 closes keep-alive without Connection: close; Caddy 502 not verified -- gateway-smoke.log:35 ("reconnects:329") -- ok
104. restarting gateway 503 about 11 s, 30 s set-aside -- rh5:56, 104-106 -- ok
105. loopback / plain-http redirect warnings -- challenges-l2 row 36 (outside my read list) -- not re-checked, kept
106. rpc-advertise needs outbound HTTPS, no flag skips -- IC:3225 -- ok
107. same-host refused on mainnet; testnet add-on adds --healthcheck -- OP:1642, 1677 -- ok
108. standalone wildcard binds guarded by ufw (read from code) -- EC:2815-2833 -- ok
109. "Resetting ... takes four commands" -- FW:517-528, 2831 (--reset re-applies the stored GATEWAY_ALLOW_FROM, so the --gateway-from step restates it); OP:1805-1814 gives four -- over-strong -> reworded "means turning the upstream off around the reset (OPERATOR.md 4.15 gives ...)"
110. older scripts: remove-node leaves it, firewall --reset drops rules -- OP:1917; R1a L10 -- ok
111. open Lows (10 listed + the downgrade bullet = 11); R1b L1 "--status reports it, a second --enable repairs it" -- R1a:87-98, R1b:97-198 -- ok
112. maintainer functions exist in the named files -- grep: EC:2834, common:11325/11377, FW:583/619/636/2265, IC:882, GW:451/314, remove-node:925/970/1563 -- ok

## Follow-ups
113. follow-ups (image CI, rate-limit option, setup-observability starting a stopped node, stale --healthcheck comments, unknown flags ignored) -- challenges-l2 rows (outside my read list) -- not re-checked, kept
