status: done
unit: SU (devnet-startup.sh in dg-l2, branch l2/launch-2)
updated: 2026-11-17T19:44:01Z
completed sections:
- read rules/contract/units/facts (2026-11-17T19:44:01Z)
- edit: header line 16 extended (+2 lines); new block after the docker branch (lines 89-110): dpkg-query guard, apt-get update + install -y nftables ufw only if either missing; no ufw enable, no nft ruleset
- gates: bash -n 0; shellcheck -x 0 findings before / 0 after (exit 0); check-bash-portability exit 0; stubbed guard test both paths exit 0
- nftables.service on 24.04: noble nftables 1.0.9-1ubuntu0.1 postinst enables only if debian-installed+was-enabled, restarts only via try-restart -> fresh install = disabled, inactive
- wc -l 286 (was 263)
