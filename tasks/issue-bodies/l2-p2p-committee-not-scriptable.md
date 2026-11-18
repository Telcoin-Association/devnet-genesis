# firewall-setup.sh --p2p-committee refuses --json, waits for a lock rather than a snapshot, and its tool is off PATH

Turning the committee P2P allowlist on is a manual step per validator: `--p2p-committee` cannot run with `--json`, its sync waits for the tool's lock but not for an authoritative snapshot, and the tool it installs is not on sudo's PATH.
Every validator operator who turns the allowlist on meets the first two; anyone who follows the docs to the tool's own `status` or `check` meets the third. They are three parts of one flow and could be split.

## What happens

- `--p2p-committee on|off|sync|status` goes alone: with `--json` the script stops with "--p2p-committee goes alone: not with --json, --status, --enable, --reset, --port or a source flag …".
  A driver gets no machine-readable result for the step and has to read the human output. The code says this is deliberate: "it is turned on and off on the server only, and --json --status reports it in its "p2p_committee" object."
- `on` runs the tool's `sync --require-authoritative --wait 30`. Per the challenge row and the tool's contract (not re-read here), `--wait 30` waits for the tool's lock only.
  A node whose admission snapshot is not yet authoritative is refused at once: the sync exits 1, writes nothing, gives a `reason=`, and the script removes what this run installed. A driver has to retry; the devnet's driver does.
- On validator-1-devnet, `sudo tn-p2p-allow-sync status` and `sudo tn-p2p-allow-sync check` answered rc 1, `sudo: tn-p2p-allow-sync: command not found`.
  With the full path `/usr/local/libexec/telcoin/tn-p2p-allow-sync`, `check` answered `result=ok missing_total=0 mismatch_total=0`, rc 0. Validators 3 and 4 gave the same `command not found`.
  OPERATOR.md lists the full path in its file table, but its message table names the tool bare ("tn-p2p-allow-sync check finds …").

## Evidence

- Devnet in mainnet shape (four validators behind worker gateways, a committee P2P allowlist, one public RPC node, a fifth node staking after genesis), run of 2026-11-17/18.
- `command not found` and the full-path result: validator-1-devnet at 02:29 UTC, devnet-genesis `tasks/l2/w3/d4/as-run.md:55-58`; validators 3 and 4 in `tasks/l2/w3/d4/C-v3-check.txt:2` and `C-v4-check.txt:2`.
- The lock-only wait: read from code and from the tool's `docs/contract.md:287-288` (tn-p2p-allow-sync repository) by an earlier pass; the contract was not re-read here. The driver's retries are taken from the row, not re-read.

## Where in the code

tn-node-deployment, `origin/main` (2813343) / PR #68's head (79fb24e). PR #68 moves the lines but does not change them.

- Argument parsing: `firewall-setup.sh:3990` / `:4329`; the refusal with `--json`: `:4015` / `:4361`; the design comment: `:3602-3604` / `:3918`.
- The sync call: `firewall-setup.sh:1745` / `:1883` (`fw_allow_run sync --require-authoritative --wait 30`), described at `:1662-1670` / from `:1803`.
- The tool's path: `firewall-setup.sh:1500` and `:1573` / `:1638` and `:1711`.
- OPERATOR.md: full path in the file table at `:307` / `:308`; the bare name in messages at `:635`, `:649` / `:637`, `:651`.

## What is not known

- How long a freshly started validator takes to become authoritative, and so how long a driver must keep retrying.
- Whether tn-p2p-allow-sync could wait for an authoritative snapshot itself (another repository; not read).
- Whether the refusal's exit code tells "not yet authoritative" apart from a real failure (not read).

## What could be done (suggestions, none tried)

- Accept `--json` with `--p2p-committee` and print one `done` event carrying the tool's `result=` and `reason=`.
- Wait, bounded, for an authoritative snapshot before refusing, or exit with a code a driver can treat as "retry".
- Link the tool into a directory on sudo's PATH, or give the full path wherever OPERATOR.md names a tool command.

## Related

- Row 72 of the same run, not drafted here: `--p2p-committee status` shows `keys=4` beside five addresses without saying the fifth is the trusted RPC node, and its drop counter (`accept=177128 drop=992`) names no source.
- {{joiner-sync-stalls-behind-allowlist}}: a joining validator's sync behind this allowlist.
- {{public-rpc-serves-tn-namespace}}: the admission snapshot the tool reads.
