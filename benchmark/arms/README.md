# Node switches and arm files

This directory holds the node switches a bench run may flip (`switches.tsv`) and the arm files that set them (`<name>.arm`).
`tools/params-apply.sh` applies an arm to a running fleet by rolling restart.
With `BENCH_ARM_FILE=<file>`, deploy step 7 applies the same arm to every node before the first start, through the same remote snippet.
`MANIFEST-FIELDS.md` lists the manifest fields both of them write.

## switches.tsv

`switches.tsv` is the single source of truth for the switch names, types and allowed values.
`benchmark/config.sh` carries the same list as `BENCH_NODE_SWITCH_KEYS` (and appends it to `BENCH_NODE_PARAM_KEYS`), and `tests/test_node_image.py` keeps the two equal.
Tools that need the switches read the tsv; nothing else keeps its own copy.

The file is ASCII text with LF line ends: one header line, then one row per switch, fields separated by a single tab.
It has no comments and no blank lines.

| column | meaning |
|---|---|
| `key` | the top-level `parameters.yaml` key, a flat field of the node's `Parameters`; `[a-z][a-z0-9_]*` |
| `type` | `bool`, `int` or `dur` |
| `default` | what the node does when the key is absent, which is bench 5's behaviour: `false`, `0` or `0ms` |
| `arm_values` | the values an arm may set, comma-separated; it may include the default |
| `topic` | the node topic's slug, the `Topic:` footer of its commits |
| `optional` | `yes` when a node image may lack the switch, `no` otherwise |

Values follow the type: `bool` is `true` or `false`, `int` is a non-negative integer without leading zeros, and `dur` is `<int>ms` or `<int>s`.
They match the value rule `report/make_bundle.py` applies to `param_arms[].nodes`.
`BENCH_NODE_PARAM_OVERRIDES` takes the same spellings, except that its `int` check refuses 0 (a default never needs an override).

The rows, frozen on 2026-11-10 (renaming one changes the contract with the node image):

| key | type | default | arm values | topic | optional |
|---|---|---|---|---|---|
| `quorum_exec_block` | bool | false | true | quorum-exec-block | no |
| `quorum_exec_block_starved_rounds` | int | 0 | 0, 4 | quorum-exec-block | no |
| `vote_queue_fix` | bool | false | true | voter-lock | no |
| `mdbx_random_advice` | bool | false | true | mdbx-advice | no |
| `sealed_tx_keep` | bool | false | true | sealed-keep | no |
| `digest_dedupe` | bool | false | true | digest-dedupe | no |
| `recovery_threads` | int | 0 | 3 | recovery-pool | no |
| `epoch_close_task_drain` | bool | false | true | tracker-drain | no |
| `epoch_record_state_check` | bool | false | true | tracker-drain | no |
| `parent_grace` | dur | 0ms | 150ms, 100ms | parent-grace | no |
| `rpc_admission_backlog_outputs` | int | 0 | 3 | inflight-bound | no |
| `pipelined_persist` | bool | false | true | pipelined-persist | yes |

`quorum_exec_block_starved_rounds` matters only when `quorum_exec_block` is true.
At 0 every header uses the quorum rule; at K > 0 a header carries the node's own tip by default and uses the quorum rule for K rounds after one of the node's own headers was cancelled uncertified.
The node accepts any non-negative integer; an arm may set 0 or 4.

`pipelined_persist` is optional because it is cut from the image unless its go/no-go tests pass.

To add a switch, add its row here, append `<type>:<key>` to `BENCH_NODE_SWITCH_KEYS` in `benchmark/config.sh` and to `SWITCH_KEYS` in `tests/test_node_image.py`.
To allow another value for an existing switch, add it to that row's `arm_values`.

## Arm files

An arm file, `benchmark/arms/<name>.arm`, states the full switch state of one arm and the host steps to run when each node restarts into it.
A switch the file does not list is at its default.
Arms are therefore not cumulative: an arm that lists only `param vote_queue_fix true` turns every other switch off, so each arm of a cumulative schedule lists every switch that is on in it.

### Grammar

The file is ASCII text with LF line ends, read one line at a time.
Leading and trailing spaces and tabs are ignored, and fields are separated by one or more spaces or tabs.

| line | rule |
|---|---|
| blank | ignored |
| `# ...` | a comment: the first non-blank character is `#`; ignored |
| `name <name>` | exactly once; `[a-z0-9][a-z0-9-]{0,39}` (the arm-name rule of `report/make_bundle.py`); should equal the file name without `.arm` |
| `param <key> <value>` | `<key>` is a row of `switches.tsv` and `<value>` one of that row's `arm_values`; each key at most once |
| `host evict-mdbx` | at most once |
| `host read-ahead-kb <n>` | at most once; `<n>` is a non-negative integer (KiB) without leading zeros |

A switch at its default is normally left out.
A `param` line may give the default only when the row lists it in `arm_values` (today only `quorum_exec_block_starved_rounds 0`); it means the same as leaving the key out, and the recorded `switches` state is the same either way.
A directive has no trailing comment.
An arm with only a `name` line is the control arm (every switch off, no host step).

### What a parser refuses

A parser refuses the whole file, before anything changes on any node, for any of these:

- an unknown directive, an unknown `param` key or an unknown `host` step
- a value that is not in the row's `arm_values` (a default the row does not list included)
- a key, a host step or the `name` line given twice, or no `name` line
- a line with too few or too many fields
- a carriage return, or any other byte outside printable ASCII, space and tab

The refusal names the file, the line number and the reason.
Accepting an unknown key would hide a typo: the node ignores keys it does not know, so a misspelled switch would silently stay off.

### Host steps

`host read-ahead-kb <n>` writes `/sys/block/<data disk>/queue/read_ahead_kb` and reads it back.
It is state: an arm that does not list it puts back the value the host probe recorded at deploy step 7 (`node_startup[<inst>].host.read_ahead_kb`).

`host evict-mdbx` runs `sync -f`, then `posix_fadvise(POSIX_FADV_DONTNEED)` over `<datadir>/db/mdbx.dat`; afterwards fincore must report 0 resident pages, or the step fails on that node.
It is an action, not a state: it runs at every restart the arm makes, and an arm that lists it restarts every node, so each persist arm starts from an evicted cache.

At a restart the order is fixed, whatever the order in the file: stop the node, `read-ahead-kb`, `evict-mdbx`, start the node.
The eviction is the last thing before the start, so nothing reads the file back into the cache in between.

A node is restarted when its `param` state differs from the arm's, when its read-ahead differs from the arm's, or when the arm lists `evict-mdbx`.

### Optional switches

An arm may set an optional switch only when the image knows it.
After each restart the tool reads the node's `node switches` startup line back and compares it with the arm's full state.
If the image lacks an optional switch that the arm sets, that comparison fails at the first node and the arm stops there.
The comparison skips an optional switch the line does not print only while the arm leaves that switch at its default.

### Knobs

`BENCH_ARM_FILE=<file>` makes deploy step 7 apply the arm before the first start (`benchmark/config.sh` checks that it is a readable `<name>.arm` file and makes a relative path absolute).
The arm file then carries the host steps, so `BENCH_NODE_EVICT_MDBX` and `BENCH_NODE_READ_AHEAD_KB` must stay unset beside it; `benchmark/config.sh` refuses either one.

### Example

```
# p2: whole-map random advice on mdbx.dat, an evicted cache and 16 KiB read-ahead
name p2
param mdbx_random_advice true
host read-ahead-kb 16
host evict-mdbx
```

Every application of an arm appends one `param_arms[]` entry to the run's manifest (`MANIFEST-FIELDS.md`).
