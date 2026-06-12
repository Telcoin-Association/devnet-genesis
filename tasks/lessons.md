# Lessons

## gcloud: never put `gcloud alpha` in a non-interactive script (2026-06-10)

**Symptom:** `setup-obs-disk-alert.sh` hung silently at Step 3 after printing
">>> Step 3: create/replace alert policy". No error, just a hang.

**Root cause:** the `alpha` gcloud component was "Not Installed" on the operator's
machine. The first `gcloud alpha …` call stops to ask "install the alpha component?
(Y/n)" — an interactive prompt that reads as a hang in a script. (`beta` was
installed, so Step 1's `gcloud beta monitoring channels` worked — which made the
hang look mysterious.)

**Fix / rule:**
- Prefer the **GA** surface. Check with `gcloud <group> <cmd> --help`. Here GA
  `gcloud monitoring policies` exists; `gcloud monitoring channels` does NOT (still
  beta-only).
- Use `beta`/`alpha` only when there's no GA equivalent, and **document the required
  component** in the script + README (`gcloud components install beta`).
- When picking a surface, verify availability rather than copying from a plan:
  `gcloud components list --filter='id=alpha OR id=beta' --format='value(id,state.name)'`.
  Note state can be `Installed`, `Update Available`, or `Not Installed` — only
  `Not Installed` blocks; don't write a guard that treats `Update Available` as
  broken.

**Why it matters:** scripts that hang on a hidden prompt are worse than scripts that
fail loudly — they look like network/permission issues and waste debugging time.
