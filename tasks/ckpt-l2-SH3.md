status: done
updated: 2026-11-17T21:41Z

# unit SH3 checkpoint (shim steps 15..20 + fresh 1..20 run; dg-l2/tasks/l2-shim/)
## Completed sections
- a. four checks vs real tnd-l2-gateway: (1) unit `StandardOutput=append:/var/log/telcoin/telcoin.log` +
  `-error.log` = lib/common.sh:3831-3832,3858-3859: fake matches. (2) gateway fence `# >>> tn-gateway >>>` /
  `# <<< tn-gateway <<<` = lib/common.sh:9204-9205: matches; added the missing stamp line `# tn-gateway block v1`
  (install-caddy.sh:169,1340). (3) obs log flags: real lib/observability.sh:146 also adds
  `--log.file.max-size 100 --log.file.max-files 5`: emulator corrected. (4) "Not restarting": real text is
  `Not restarting: the committee could lose its quorum ...` (lib/observability.sh:1148), emulator corrected;
  "Added --healthcheck" = setup-observability.sh:598 prefix: matches. json_event emits
  {"event":"warn","msg":...} with no spaces: driver globs (devnet-observability.sh:259,387,391) match. No finding.
- b. steps 15..20 on the SH2 state (class a, all added to fakes.py/run.sh): 15 CLEAN (install-caddy.sh rpc-enable /
  rpc-status / gateway-status / status / enable --password-stdin; restarts the node once, SUSPECT if stopped);
  16 CLEAN, 64/64 POSTCHECK ok (node JSON-RPC on 8545 from loopback/internal IP with bind + ufw GATEWAY_ALLOW_FROM
  model: refused rc 7 / dropped rc 28; ss binds from the launch line, bare --healthcheck = 127.0.0.1; gateway metrics
  9655; operator-side https curl answering per Caddy block owner); 17 CLEAN (ui/install-ui.sh fake + flags, systemctl
  list-unit-files, UI on 127.0.0.1:8080); 18/19 STUBBED at the driver boundary (run.sh replaces devnet-contracts.sh
  and devnet-txgen.sh in the snapshot by a recorder, calls.log tool=stub; preflight needs TN_CONTRACTS_DIR and
  TXGEN_CONTRACTS_DIR = any existing dir); 20 CLEAN after adding plain `ufw status`, /usr/sbin rewrite + fake nft,
  firewall-setup --p2p-committee on|off|sync|status, tn-p2p-allow-sync check|status (PAS contract.md:524), and a
  chain whose head rises 1/s (settle 2 s was too short at 1 per 2 s).
## Findings (class b)
- none yet
- c. FRESH RUN 1..20 CLEAN (state .../scratchpad/SH3/fresh, output .../SH3/fresh.out): deploy exit 0, step 20 reached,
  findings.log empty, sentinel 0, real-gcloud logs 0, shim crashes 0, 64/64 POSTCHECK ok. Remote (ssh/scp) per step and
  host: 5: observer-5=3,rpc-6=3,validator-1=3,validator-2=3,validator-3=3,validator-4=3; 7: observer-5=3,rpc-6=2,validator-1=3,validator-2=3,validator-3=3,validator-4=3; 9: obs=5; 10: observer-5=9,rpc-6=9,validator-1=9,validator-2=9,validator-3=9,validator-4=9; 11: gateway-4=2,observer-5=2,rpc-6=2,validator-1=2,validator-2=2,validator-3=2,validator-4=2; 12: observer-5=5,rpc-6=3,validator-1=5,validator-2=3,validator-3=5,validator-4=3; 13: gateway-4=1,observer-5=1,validator-1=1,validator-2=1,validator-3=1,validator-4=2; 14: observer-5=74,rpc-6=74,validator-1=74,validator-2=74,validator-3=74,validator-4=74; 15: rpc-6=3; 16: gateway-4=1,observer-5=1,rpc-6=1,validator-1=1,validator-2=1,validator-3=1,validator-4=1; 17: observer-5=4,rpc-6=4,validator-1=4,validator-2=4,validator-3=4,validator-4=1; 20: validator-1=13,validator-2=13,validator-3=13,validator-4=13
  Order checks (analyse.py in .../SH3/): (1) yes, starts before 14 only setup-node finalize (step 10, all six) and the
  obs installer on hosts 1,3,5 (step 12), each stopped in the same step; all six inactive at end of 13. (2) yes, gateway-4
  got only firewall --json --enable, setup-gateway --enable/--status, the postcheck probe. (3) yes, remote-detail #415
  firewall --gateway-from < #417 edit-config gateway_upstream < #419 setup-gateway --enable (all step 13). (4) yes,
  rpc-enable #2032 step 15 after the last step-14 line #2029. (5) yes, v1 on,check,status | v2 ... | v4 in order.
  (6) yes, none of 7 fake secret values in calls.log, remote-detail.log, findings.log or deploy-output.log.
- gates: py_compile fakes.py 0; bash -n + shellcheck -x run.sh and bin/_dispatch 0; git status: only tasks/l2-shim/
  (fakes.py +490/-9, run.sh +8) from this unit. README "What is faked" not updated (budget).
## Next / resume
- nothing left for SH3. Rerun: see hand-back env line.
