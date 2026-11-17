status: done
updated: 2026-11-17T20:54Z
completed:
- step0 real ufw premise: VERIFIED on ubuntu:24.04 container l2ufw-1, ufw 0.36.2 (logs: /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/FX-A1/ufw-exp.log, /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/FX-A1/ufw-exp2.log)
  - IPv4: add 10.0.0.7/32 -> shown 10.0.0.7; add 10.0.0.5/24 -> "WARN: Rule changed after normalization", shown 10.0.0.0/24
  - re-add bare / network spelling -> "Skipping adding existing rule"
  - delete bare removes rule added /32; delete /32 removes rule added bare; delete 10.0.0.9/24 removes 10.0.0.5/24
  - add 1.2.3.4/32 port 22, delete bare -> SSH rule gone (lockout risk REAL); delete 35.235.240.1/20 removes the IAP rule 35.235.240.0/20
  - IPv6: /128 dropped, text compressed+lowercased (2001:DB8:0:0::1/128 -> 2001:db8::1; delete 2001:db8::1 removes it);
    IPv6 CIDR host bits are NOT masked (2001:db8:1::5/64 shown as is; delete 2001:0db8:0001:0000::9/64 = non-existent)
  - delete of non-existent rule: rc 0; leading-zero octet: "ERROR: Bad source address" rc 1
design (decided): fw_src_canon/fw_src_in in firewall-setup.sh next to fw_src_deletable; used by fw_stale_sources (ssh/p2p/gw one function),
  fw_health_keeps, the SSH fixed-range skip, H1 guard. fw_gw_upstream_guard (H1+M3) in fw_preflight(do_reset).
  H3: SSH_ALLOW_FROM in gateway.meta when FW_GW_ONLY. L6 status order. L1 left (needs a new meta key).
  lib/gateway.sh read-only: writes gateway.meta per own key via meta_set (751) -> unknown key kept; --remove deletes meta+dir.

- H2 done: fw_src_canon + fw_src_in (firewall-setup.sh, after fw_src_deletable); fw_stale_sources (ssh/p2p/gw: ONE function), fw_health_keeps, SSH fixed-range (IAP/overlay) skip
- H1+M3 done: fw_gw_upstream_guard RESET, called from fw_preflight "$do_reset" (apply_recommended_firewall passes it)
- H3 done: fw_sources/fw_stale_sources ssh read gateway.meta when FW_GW_ONLY; fw_persist_sources writes it (meta_set/unset FILE); fw_wants_meta_write gw-only = ssh only; fw_meta_lock skips addon_meta_write_begin when FW_GW_ONLY
- L6 done (status screen: Anywhere check before the gateway info line). L1 left (needs a new meta key).
- fwstub.sh: UFW_NORMALIZE=1 switch (default unchanged)
- tests: gateway_validator_test.sh +new sections; after 214 checks 0 fail; before (HEAD firewall-setup.sh, same lib + tests, scratch /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/FX-A1/before) 214 checks 32 fail
- gates done: bash -n 0 x3; shellcheck --severity=error 0 x3; --severity=warning counts 4/0/0 (the 4 in firewall-setup.sh = HEAD's, lines 172/2241/2244/2246 pre-existing); check-bash32 0; check-perl-interp 0; check-network-hits 0
- run.sh 5 files: exit 0 (gateway_validator 214 checks 0 fail); bash:3.2 gateway_validator: exit 0; all 9 fwstub users: exit 0
- reviewer harness h_fw.sh (relocated copies /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/FX-A1/before, /tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/FX-A1/after): S3' 1.2.3.4 rule gone after; S6 --reset refused after; S7 = M4 (other unit)
- container l2ufw-1 removed
left: L1 (old RPC port rules), L7, L8, L9, L10 not touched (reasons in hand-back)
