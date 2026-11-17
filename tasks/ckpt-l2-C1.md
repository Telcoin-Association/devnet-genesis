status: done
unit: C1 (TND lib/common.sh shared gateway names, contract section 2)

## completed sections
- S0 reading (2026-11-17T19:42:53Z): rules, contract 1/2/5/12, units C1 row + TND gates, facts tnd-template 5-6, tnd-firewall 3, common.sh anchors
- S1 constants, S2 six functions, S3 gateway.sh source block: edited (2026-11-17T19:44:32Z)
- S4 gates all rc 0 (sc-warning set identical to HEAD: 14, SC2034 suppressed in my lines); tests primitives 241/0/6, lib_skew 156/0/0, launch_flags 28/0/0, alerts 288/0/3, run.sh rc 0 (2026-11-17T19:46:57Z)

## plan
- S1 constants block after the add-on safety defaults (after the TN_ALLOY_NATIVE_VERSION line, ~9187), plain assignments like lib/alerts.sh
- S2 functions block (6 functions) just before the "Optional add-on libraries" source block at the end (keeps C2/C3 read ranges almost unshifted)
- S3 guarded gateway.sh source block after the alerts block
- S4 gates (bash -n, shellcheck error/warning, check-bash32, check-perl-interp, check-network-hits) + tests (primitives, lib_skew, launch_flags, alerts) + scratch check

## notes
- ufw_has_allow PORT PROTO matches port/proto only, not the From column: per-source check parses ufw status itself (report as deviation from the brief, not the contract)
- S5 scratch check (bash 5 and bash:3.2 identical output, rc 0), source block tested with/without a dummy lib/gateway.sh in a scratch copy of lib/ (2026-11-17T19:48:09Z)
