status: done
unit: GW (devnet-gateway.sh in dg-l2)
updated: 2026-11-17T20:29Z

## Sections
- [x] S1 read rules, contract (1, 3.1, 3.2, 4, 5, 8, 10, 11, 12, A-1/A-5/A-6/A-7), units GW row + DG gates, facts dg-core 2, tnd-caddy 1+4
- [x] S2 read driver style (devnet-firewall.sh, tn_select_indices), lib helpers, config vars, setup-gateway.sh usage
- [x] S3 write devnet-gateway.sh
- [x] S4 gates (bash -n, shellcheck -x, portability)
- [x] S5 dry run (all hosts) + stub runs (order, summary, stop-on-failure, exit 0/1/2)
- [x] S6 hand-back

## Notes
- S2 facts: lib has tn_iap_ssh (already </dev/null + transport retry), tn_internal_ip, tn_gateway_mode/host_index, tn_public_domain, tn_json_done_line/true/str. config GATEWAY_IMAGE still PLACEHOLDER_ in dg-l2 (A-4 digest known). edit-config --json --set same value = no change, no restart. setup-gateway done line: applied:["gateway:x"], booleans literal.
- Design: plan arrays (host, what, kind, cmd) built before any change (IPs via tn_internal_ip with --yes only; dry run prints <internal-ip:INST>, no gcloud); sweep stops at first failure, lists not-run/UNTOUCHED; --status reads all, ro retry on 255; --rpc-edge = rpc-enable then rpc-status assert. Test via scratch dir with symlinked script + wrapper devnet-lib.sh (real lib + stubs).
- S3/S4 (2026-11-17T20:28Z): dg-l2/devnet-gateway.sh written; bash -n 0, shellcheck -x 0 (no finding), portability 0.
- S5 (2026-11-17T20:29Z): dry run all hosts rc 0 (no gcloud/ssh; IPs as <internal-ip:INST>); stub runs: node4+node1 rc 0 (order v1; v4 fw, v4 edit-config, gw4), full rc 0, fail on v4 firewall rc 1 (not run edit-config; UNTOUCHED gw4, obs5), fail on gw4 rc 1, status rc 0 / inactive rc 1 / 255 retry once rc 0, install 255 no extra retry rc 1, rpc-edge dry 0 / yes 0, ip lookup fail rc 1 no ssh, exit 2: placeholder, tag image, rpc-6 target, unknown target, --rpc-edge+target, --status+--rpc-edge, --status+--yes, unknown option. Outputs in scratchpad GW/. Note: dg-l2 config.sh now carries the A-4 digests.
- S6: handed back.
