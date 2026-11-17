status: done
unit: D2 (remove-node.sh gateway half of contract §6)
updated: 2026-11-17T19:47Z

## Completed sections
- [x] S1 read (2026-11-17T19:43Z): rules, contract §2/§3.3/§6/§12, units D2 row + TND gates, project-context remove-node passages, remove-node.sh ranges 1-48, 286-335, 439-505, 594-730, 900-1035, 1370-1551, 1764-2080
- [x] S2 (2026-11-17T19:45Z) edit remove-node.sh (rm_gateway_present, remove_gateway, leftovers/no-node path, json path, doc comments)
- [x] S3 (2026-11-17T19:45Z) gates: bash -n 0, sc error 0, sc warning rc1 5 warnings = same 5 as HEAD (4 SC2034, 3 SC2115 codes; none in new lines), bash32 0, perl-interp 0, network-hits 0
- [x] S4 (2026-11-17T19:47Z) tests: run.sh lib_skew remove_addons remove host_baseline vpn_selfheal -> 5 files, 0 failed, rc 0 (bash 5.3.9)
- [x] S5 (2026-11-17T19:47Z) harness rc 0: scratchpad/D2/harness.sh, output scratchpad/D2/harness.out (cases A, A2, B, C, D, D2, E, F all as wanted)

## Design notes (S1)
- remove_gateway called next to remove_alerts at: remove_leftovers (~1018), remove_node_unit (~1476), json_remove (~1931).
- Gateway-only host = no node unit and no node leftover once the gateway's own files are discounted:
  /etc/telcoin counts only if it holds an entry other than gateway/; /var/backups/telcoin (tn_backup_file default,
  where gw_enable backs up) does not count alone while a gateway is installed. Such a host gets the pointer
  "sudo bash setup-gateway.sh --remove" (interactive: after "No standard ... detected"; json: warn event before
  the unchanged "no node installed" error); nothing removed.
- Gateway NOT counted alone in rm_leftovers_present (would turn a gateway-only host into a leftovers host).
- .node-meta: removed with keys (interactive DELETE, json scope keys, remove_leftovers); kept for json scope
  service|data, interactive "keys kept", wipe-chain-data-only -> GATEWAY_* / RPC_ADVERTISED_VIA stay in it.
