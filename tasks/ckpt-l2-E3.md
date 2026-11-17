status: done
unit: E3 (gateway validator fixture tests)
updated: 2026-11-17T20:16:21Z
completed sections:
- reading; baseline recorded (origin/main 2813343 == branch for testnet --enable/--reset, mainnet --enable)
- tools/tests/gateway_validator_test.sh: 165 checks, 0 failures (bash 5 and bash 3.2); mutation-tested
- tools/tests/gateway_upstream_test.sh: 75 checks, 0 failures (bash 5 and bash 3.2); mutation-tested
- defect fixed: firewall-setup.sh fw_gw_rule_present matched ufw status literally (a /32 host shown bare, a CIDR shown by network address read as missing on the status screen and in desired[].ok); now delegates to tn_gateway_from_rules_ok. Check "ufw display" failed 3/3 before, passes after
- gates: bash -n, shellcheck error/warning (0 new), check-bash32, check-perl-interp, check-network-hits all rc 0; 11 named test files rc 0
next: hand-back
