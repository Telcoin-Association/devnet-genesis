# PT-0 API: adding a runtime switch on `feat/bench6-switches-obs`

PT-0's head (branch `b7/pt0`; tip sha in `tasks/checkpoint-bench7-PT-0.md`) carries the switch machinery with zero switches.
A topic adds its switch in one file, `crates/config/src/node.rs`, in three marked places, and nothing else anywhere.
The `node switches` line and the `tn_node_switch{name}` gauge pick the switch up from the list.

## The three places

Each place has the same two marker lines; add your lines just above `// ---- runtime switches: end ----`.
Two topics' lines will sit side by side there; the orchestrator merges them.

```
// ---- runtime switches: begin ----
// ---- runtime switches: end ----
```

1. The field, at the end of `pub struct Parameters`:

```rust
    /// <What the switch changes, in one sentence.>
    ///
    /// <What the node does when it is on.> The default `false` keeps the previous behaviour:
    /// <M's behaviour>. Issue #NNNN.
    #[serde(default, skip_serializing_if = "Parameters::switch_at_default")]
    pub my_switch: bool,
```

   A duration takes `with = "humantime_serde"` first: `#[serde(with = "humantime_serde", default, skip_serializing_if = "Parameters::switch_at_default")]`.

2. Its default, at the end of `impl Default for Parameters`: `my_switch: false,` (or `0`, or `Duration::ZERO`).

3. Its entry, in the `runtime_switches! { … }` call below `impl Parameters`: `my_switch,`.
   The entries' order is the order of the `node switches` line.

## Rules the tests hold you to

- The default is the type's default (`false`, `0`, `Duration::ZERO`) and is M's behaviour.
- `skip_serializing_if` keeps a switch at its default out of a written `parameters.yaml` (the genesis ceremony and the mainnet preset regeneration write `Parameters::default()`); an absent key reads back as the default.
- The YAML key is the field name: no `serde(rename)`.
- Types: `bool` (gauge 0/1), `u16`, `u32`, `u64`, `usize` (gauge = the value), `Duration` (gauge in milliseconds, logged in humantime form: `150ms`, `0s`).
- Another type needs a `From<T> for SwitchValue` impl beside the others.
- `quorum_exec_block_starved_rounds` (`u32`) is a count, as in bench 6: the line shows `quorum_exec_block_starved_rounds=4` and the gauge exports 4.

## Tests

The guard tests in `crates/config/src/node.rs` (`mod test`, block `// ---- bench6 bench6-switches ----`) are generic: a topic extends none of them.
- `switches_list_every_switch_field` fails for a field that is neither in `runtime_switches!` nor in `NON_SWITCH_KEYS`, and for a default switch that is written.
- `switch_values_render_as_their_yaml` fails for an entry that names the wrong field.
- `absent_switch_keys_load_the_defaults` fails when `Default` and the serde default disagree.
- `chain_presets_leave_every_switch_at_its_default` fails when a chain preset sets the switch.
- `node_switches_line_renders_yaml_tokens` pins the line at the defaults and with every switch flipped (bools on, counts 3, durations 150ms).

Run them with `cargo nextest run --locked -p tn-config -p tn-types -p tn-node -E 'package(tn-config)'`: on M, `-p tn-config` alone still fails to compile `tn-network-types`.

## What the node shows

At start, once per process (`EpochManager::new`): one info event, target `node::switches`, message exactly `node switches`, one field per switch named by its YAML key, values in YAML form.
With zero switches the line is the bare message `node switches`.
Gauges: `tn_node_switch{name="<yaml key>"}`, one per switch, set once at start.
