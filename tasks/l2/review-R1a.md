status: done
completed: lib/common.sh helpers; firewall-setup.sh --gateway-from; edit-config.sh gateway_upstream; check-node.sh check_gateway_upstream; JSON/UI consumers; version skew; open-question rulings

# Review R1a: tn-node-deployment `worker-gateway`, validator side

Branch `/home/drtnarg/coding/telcoin/tnd-l2-gateway` @ 405af9e, diff against `origin/main`. Line numbers are in the branch files.
Harnesses (throwaway, built from the branch's own tests and `tools/tests/fwstub.sh`):
`/tmp/claude-1000/-home-drtnarg-coding-telcoin-devnet-genesis/d70f6bbc-58c2-43ff-8487-c755e557b71e/scratchpad/R1a/h_fw.sh` (firewall-setup.sh) and
`.../scratchpad/R1a/h_ec.sh` (edit-config.sh). "Reproduced" means a harness run showed it. "Traced" means I followed the code line by line and did not run it.
No real ufw or systemd was used. Where a finding depends on how real ufw normalizes addresses, that is the A-2 premise, and the tests' `UFW_AS_UFW` mode models it.

Counts: High 3, Medium 4, Low 12.

## High

### H1. `--gateway-from none`, or a new list without the upstream host, succeeds while `GATEWAY_UPSTREAM` is set
- Where: `firewall-setup.sh` fw_preflight (2234-2260) and the stale delete (2771-2778). Nothing in firewall-setup.sh reads `GATEWAY_UPSTREAM`.
- Scenario (reproduced, S2 and S2b): `.node-meta` holds `GATEWAY_ALLOW_FROM=10.0.0.7`, `GATEWAY_UPSTREAM=10.0.0.7`, and the two rules exist. Then:
  - `--enable --gateway-from none` exits 0 with no warning. Both rules are deleted and `GATEWAY_ALLOW_FROM` is unset. `GATEWAY_UPSTREAM` stays, so `--http.addr 0.0.0.0` and `--healthcheck 0.0.0.0:43174` stay.
  - `--enable --gateway-from 10.0.0.8` does the same thing to 10.0.0.7.
- Why it is wrong: the bind stays on 0.0.0.0, but the only guard the contract names for it has been removed. From then on, the default-deny policy is all that protects the staked node's RPC. A later `ufw disable`, a broader allow, or a policy change exposes it. The gateway also goes dark, and the operator is not told. edit-config.sh refuses to bind without these rules, but firewall-setup.sh can remove them after the bind without any check.
- Smallest fix: in fw_preflight, after FW_GW_SRCS is filled and when `GATEWAY_UPSTREAM` is set, refuse unless every upstream address is still in FW_GW_SRCS (compare after normalizing, see H2). Message: "run `edit-config.sh --set gateway_upstream=off` (or `=<new list>`) first". Add a test for both forms.

### H2. The stale-source delete compares spellings literally, and ufw normalizes them, so a run can delete the rules it just confirmed
- Where: `firewall-setup.sh:605-610` (fw_stale_sources `[[ "$n" == "$s" ]]`), and `fw_health_keeps` (652), which has the same literal compare.
- Scenario (reproduced command order, S1): the stored value is `GATEWAY_ALLOW_FROM=10.0.0.7/32`, which `--gateway-from 10.0.0.7/32` accepts. Then `--enable --gateway-from 10.0.0.7` issues, in this order:
  - `allow from 10.0.0.7 … 8545` and `… 43174`. Real ufw skips these because the rule already exists, stored as `10.0.0.7`.
  - `delete allow from 10.0.0.7/32 … 8545` and `… 43174`. ufw normalizes `/32` to the bare host, so these delete the same two rules.
  - The run exits 0, and the stored list now says `10.0.0.7`.
- The same thing happens with `10.0.0.5/24` replaced by `10.0.0.0/24`, since ufw stores both as the network address.
- A gateway source written `104.155.184.201`, while TN_KUMA_SRC is `104.155.184.201/32`, has the same problem. fw_health_keeps answers "not kept", so the delete removes the Association monitor's health rule.
- Why it is wrong: rules are lost without any message while the stored list still names their source. With GATEWAY_UPSTREAM set, the gateway loses its node. The stub deletes lines literally, so the suite cannot see this.
- The bug existed before this branch for `--ssh-from`, where it can lock the operator out (GCE keeps IAP), and for `--p2p-from`.
- Smallest fix: one helper that normalizes a source the way ufw does (drop `/32`, reduce a CIDR to its network address). `tn_gateway_from_rules_ok` already does this at lib/common.sh:11316-11321 and can be factored out. Use the helper:
  - on both sides of the compare in fw_stale_sources and fw_health_keeps;
  - in fw_persist_sources, so the stored form is canonical.

### H3. On a node-less gateway host, which is the mainnet shape, replacing the SSH list leaves the old SSH sources open
- Where: `firewall-setup.sh:2817` fw_wants_meta_write needs `.node-meta`, so fw_persist_sources never runs on such a host. fw_stale_sources (594) then finds nothing stored.
- Scenario (reproduced, S3 with NODE=0): a host with only `gateway.meta` and `NETWORK=mainnet`.
  - `--enable --ssh-from 1.2.3.4` and then `--enable --ssh-from 5.6.7.8` both exit 0.
  - ufw ends up with `allow from 1.2.3.4 to any port 22` and `allow from 5.6.7.8 to any port 22`.
  - A plain `--enable` exits 1 because there are no SSH sources.
- Why it is wrong: on a node host, the same commands delete 1.2.3.4. On the gateway host, a source the operator removed keeps SSH access and nobody is told. The contract (§5) makes this host shape a supported `--enable` path, and the brief makes it the mainnet shape. The root cause is older (no list is stored on any node-less host), but this branch makes such a host a supported one.
- Smallest fix: when FW_GW_ONLY=true, store and read `SSH_ALLOW_FROM` in `gateway.meta`. Do it through `meta_set KEY VALUE "$(tn_gateway_meta_path)"` under the update lock, in fw_persist_sources, fw_sources ssh and fw_stale_sources ssh. This also settles the "plain `--enable` refused" open question.

## Medium

### M1. The stopped-node guard treats `activating` as stopped, including a crashed node waiting to be restarted
- Where: `edit-config.sh:3953` (`! systemctl is-active --quiet`).
- Scenario (the message path is reproduced, E1; the systemd behaviour is traced): the node crashed, and with `Restart=on-failure` and `RestartSec=10` (lib/common.sh unit template) the unit sits in `activating (auto-restart)`. `is-active` is non-zero for `activating`. So:
  - `--set gateway_upstream=10.0.0.7` edits the files and starts nothing.
  - The done line is `ok:true` and says "was stopped and stays stopped (not started or restarted)".
  - Within 10 s, systemd starts the node with the wildcard binds. That start skips the guarded restart: no health wait and no rollback.
  - A unit in ExecStartPre (`docker stop`/`rm`) is also `activating`, and it picks up the new launch file the same way.
- Why it is wrong: the done line is false, the contract ("left stopped") is violated, and the change goes in without the restart guard.
- Smallest fix: read `systemctl show -p ActiveState --value`. Treat only `inactive` and `failed` as stopped. Refuse `activating`, `deactivating` and `reloading` with "the node is changing state; run this again". Keep `failed` as stopped.

### M2. The bind guard checks that the listed allows exist, not that nobody else gets in
- Where: `lib/common.sh:11295` (tn_gateway_from_rules_ok), used by `edit-config.sh:2872`.
- Scenario (reproduced, E2): on mainnet, `ufw status` shows `8545/tcp ALLOW Anywhere` next to the two 10.0.0.7 allows. `--set gateway_upstream=10.0.0.7` exits 0 and writes `--http.addr 0.0.0.0`, so the RPC is open to the internet.
- Traced: with `ufw default allow incoming`, the check also passes, because plain `ufw status` does not print the policy.
- A `DENY` ahead of the allow also passes. That one blocks rather than exposes.
- Why it is wrong: the header calls this check "the guard on every network". It can approve a bind that leaves the RPC public. The state needs a host the scripts did not set up this way, which is why this is not rated High.
- Smallest fix: in set_gateway_upstream (and in check_gateway_upstream), also refuse when:
  - `ufw status verbose` does not show `deny (incoming)` or `reject (incoming)`; or
  - an ALLOW on the RPC port is from `Anywhere`, or from a source outside the list.
- Keep the shared reader as it is.

### M3. `--reset` opens the 0.0.0.0 RPC to every address for the length of the re-apply
- Where: `firewall-setup.sh:2685`.
- Scenario (traced; the call order is reproduced, S6): a mainnet validator with `GATEWAY_UPSTREAM` set runs `--reset`:
  - `ufw --force reset` is call 1. ufw is now disabled and the kernel policy goes back to ACCEPT.
  - `ufw --force enable` is call 12.
  - Between the two, the node's RPC on 0.0.0.0:8545 accepts anyone. On a real host this takes seconds, and the script prints no warning.
- Why it is wrong: before this branch, nothing private listened on a wildcard during a reset. The contract keeps the gateway rules across `--reset`, but the bind is exposed while they are re-added.
- Smallest fix: refuse `--reset` while `GATEWAY_UPSTREAM` is set, and name `edit-config.sh --set gateway_upstream=off`, then `--reset`, then set it again. Or ask for confirmation interactively and refuse under `--json`. The owner decides which.

### M4. Removing a monitor extra deletes a health rule a gateway source still needs
- Where: `lib/common.sh:9603` kuma_extra_remove (older code, now reached through this branch). It runs `ufw delete allow from SRC … TN_KUMA_PORT` without condition.
- Scenario (traced; the harness attempt did not run the function): on testnet or devnet, 10.0.0.7 is in both `KUMA_EXTRA_SRC` and `GATEWAY_ALLOW_FROM`. Removing it from the extras through the menu deletes the gateway's health rule. The gateway shows not-ready until the next `--enable`.
- Why it is wrong: fw_health_keeps protects the opposite direction only. The rule is lost without a message (check-node does flag it). The trigger is narrow.
- Smallest fix: in kuma_extra_remove, skip the delete when `tn_gateway_from_list` holds SRC (normalized as in H2).

## Low

- **L1** `firewall-setup.sh:2771-2778`: stale gateway rules are deleted on the current RPC port only. After `RPC_PORT` changes, the old-port rules stay until `--reset`. Fix: store the port with the list (`GATEWAY_RPC_PORT`) and delete on that port.
- **L2** `edit-config.sh:2838` (E4, reproduced): `off` always writes `--http.addr 127.0.0.1` and `TN_RPC_ADDR=127.0.0.1`. A bind that was 0.0.0.0 before the key was set is lost.
- **L3** `edit-config.sh:2896-2897` (E3, reproduced): if `GATEWAY_PREV_HEALTHCHECK` is lost while the key is set, setting it again records the wildcard (`0.0.0.0:43174`) as the "previous" value, and `off` then leaves `--healthcheck` on 0.0.0.0. Fix: when `GATEWAY_UPSTREAM` is already set and PREV is missing, record `none` or refuse.
- **L4** `edit-config.sh:2843`: `GATEWAY_PREV_HEALTHCHECK` goes from `.node-meta` into the launch file without validation. A value with a space adds a flag. The file is root-only. Fix: validate `^(none|[0-9]{1,5}|[0-9.]+:[0-9]{1,5})$`.
- **L5** check-node.sh:2323 reads the RPC port as `.node-meta RPC_PORT` and then 8545. firewall-setup.sh and edit-config.sh use `tn_local_rpc_url`, which adds the `RPC_PORT` env fallback and the `10#` normalization. A port written `08545`, or one that comes from env, gives a false issue. Fix: call `tn_local_rpc_url` there as well.
- **L6** `firewall-setup.sh:2502-2505`: on a non-testnet host with gateway sources, the status screen says "only the worker gateway sources below reach it" and skips the existing "open to Anywhere" warning. Fix: put the `kuma_rule_state == anywhere` check first.
- **L7** On mainnet, the gateway rules make `kuma_rule_state` report `restricted`, and the UI's `ports["43174/tcp"]` shows "Uptime Kuma health" as open. Closing it from the UI deletes only the TN_KUMA_SRC and Anywhere rules, says "firewall updated", and the port stays open.
- **L8** `--gateway-from` accepts IPv6, because it uses the same grammar as `--p2p-from`. `tn_gateway_from_rules_ok` compares IPv6 literally (ufw prints the compressed lower-case form), and `gateway_upstream` refuses IPv6. check-node can raise false issues.
- **L9** Rules are applied before the list is saved (`json_fw_enable`, the interactive enable). If fw_persist_sources fails, the rules stay in ufw, and no later list change will delete them. There is a warning. This is the existing pattern for SSH and P2P.
- **L10** Script downgrade: an older firewall-setup.sh on a host with `GATEWAY_ALLOW_FROM` drops the gateway rules on `--reset` and does not add them back, while the bind stays on 0.0.0.0. Nothing makes an older script refuse a newer `.node-meta`. Note it in OPERATOR.md under update-scripts.
- **L11** check-node.sh:2317 `for s in ${up//,/ }` expands globs in a hand-edited value. Use `IFS=, read -ra`.
- **L12** False negatives in `tn_gateway_from_rules_ok`: a rule with no proto (`8545`), or one written `on <iface>`, is judged absent. This makes the check stricter, and is acceptable.

## What I checked and found sound
- A failure between the two steps leaves a safe state. Rules without the bind are harmless, and edit-config refuses to bind when the rules are absent.
- set_gateway_upstream:
  - It refuses before any file changes on an empty value, blank entries, leading zeros, 0.0.0.0, or ufw inactive.
  - The launch file, node.env and `.node-meta` are all backed up before they change.
  - The `set_field` failure, quorum-refusal and restart-failure paths go through the generic run_set rollback.
  - `off` with nothing set is "no change".
  - Changing the list when only `.node-meta` changes needs no restart.
  - Other `--set` keys are not affected by the guard, which is keyed on the field name.
- Locking and ownership migration (AGENTS.md:157): edit-config takes `edit_lock` and runs `tn_migrate_ownership` (edit-config.sh:756). In firewall-setup, `fw_meta_lock` runs `addon_meta_write_begin`, and fw_wants_meta_write includes the gateway flags.
- Duplicate keys: a duplicated `GATEWAY_ALLOW_FROM` makes `--enable` refuse, and the stale step warns and keeps the rules. Duplicated `GATEWAY_UPSTREAM` or `GATEWAY_PREV_HEALTHCHECK` makes edit-config refuse and check-node report.
- Within one run, the health block's deletes on networks other than testnet and devnet (apply_kuma_rule: the Anywhere rule, TN_KUMA_SRC and extras) run before the gateway allows, so they cannot remove them.
- The node runs with `--network=host`, so ufw does govern its ports (no Docker publish bypass).
- Reading `ufw status`:
  - These lines are handled: `ALLOW`, `ALLOW IN`, comments, `(v6)`, and Anywhere (which does not count).
  - `ALLOW OUT` and `ALLOW FWD` lines are not mistaken for a source.
  - `/32` and CIDR network-address forms are matched.
  - The CIDR mask arithmetic is correct for /8 to /32.
- The parser refuses `--gateway-from` alone, with `--status`, and with `--p2p-committee`.
- `caddy_serves_public_edge` cannot be turned into an empty pattern that matches every line.
- Lib skew is checked by function presence (`fw_require_lib`, edit-config's `tn_require_fns`, check-node's `have_fns` with a one-line skip). gateway.sh is sourced under an `if` guard.
- JSON and UI:
  - ui/server.py parses the status by key.
  - ui/static/index.html:3396-3405 renders `desired[]` generically and escapes it, so the `"<port>/tcp from <src>"` spec and the `gateway_from` key break nothing.
  - No existing desired spec contains `" from "`, which fw_rule_satisfied's first case depends on.
- bash 3.2 and `set -e` in the new lines: none of the features the repo rules out for bash 3.2 (associative arrays, `mapfile` and the rest), `(( ++x ))` starts from 0, and the `$(…)` / `|| rc=$?` patterns are safe.
- None of H1-H3 or M1-M4, nor real ufw normalization on delete, is covered by `gateway_validator_test.sh` or `gateway_upstream_test.sh`.

## Rulings on the open questions (review-notes.md "-> R1a")
1. C3, `off` loses a public bind: a defect, Low (L2). Owner's decision: refuse `gateway_upstream=<list>` when `--http.addr` is already a wildcard and `GATEWAY_UPSTREAM` is unset (my recommendation, the simplest), or record `GATEWAY_PREV_HTTP_ADDR` as A-3 does for the health check.
2. C2/C3, the RPC port from env: C2 and C3 both use `tn_local_rpc_url`, so they agree. D1 does not (L5): a defect, Low. Use `tn_local_rpc_url` in check-node.
3. C3, `failed` and `activating` count as stopped: `failed` is acceptable as is. `activating` is a defect (M1).
4. C2, a node-less mainnet host cannot store `SSH_ALLOW_FROM`: a defect, High (H3). Store it in `gateway.meta`.
5. C2, stale rules on the old RPC port: a defect, Low (L1). Acceptable for launch 2 if documented.
6. C2, `"kuma":"restricted"` on mainnet: acceptable as is. The UI does not read `kuma`, and the visible effect is L7 (Low).
7. C2, `gateway_from` placed before `p2p_committee`, and the `desired[].spec` shape: acceptable as is. The UI parses by key and renders the rows generically. Only a test helper assumes the order.
8. D1, the hint `--set gateway_upstream=off`: already fixed. check-node now says to edit `--healthcheck` in the launch file. No action.
9. E3, a CIDR in `GATEWAY_ALLOW_FROM` covering the upstream is refused: acceptable as is. Keep literal matching, and add one line to the edit-config header saying the list must match the `--gateway-from` entries.
10. E3, an empty `--gateway-from` value becomes a plain `--enable`: acceptable for now, to stay consistent with the other source flags (challenge 17 family). Fix all of them together.
11. E3, a plain `--enable` on a node-less mainnet host is refused: the same defect as 4 (H3).
