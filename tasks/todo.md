# Fix obs-VM secret access + harden create-obs-instance.sh

## Root cause
VM SA reads secrets via metadata token + Secret Manager REST, but `roles/editor`
does NOT grant `secretmanager.versions.access`. REST returns 403; `access_secret()`
only checks `.payload.data`, so it misreports as "not found or empty". Whole stack
fails to deploy (set -euo pipefail aborts before `.env` + compose up).

## Tasks
- [x] B. create-obs-instance.sh — grant secretAccessor to VM SA in Step 2 (idempotent)
- [x] B. create-obs-instance.sh — update header comment block (step list)
- [x] C. bringup-remote.sh — rewrite access_secret() to surface HTTP status + 403 hint
- [x] D. config.sh — OBS_IMAGE → image family (kill deprecation warning)
- [x] E2. config.sh — add OBS_ALERT_EMAIL + OBS_DISK_ALERT_THRESHOLD
- [x] E1. startup-obs.sh — install Ops Agent (idempotent)
- [x] E2. setup-obs-disk-alert.sh — NEW: notification channel + disk alert policy
- [x] E2. create-obs-instance.sh — reference disk-alert script in Step-7 next-steps
- [x] E2. README.md — disk-alert + resize runbook

## Notes
- A (operator IAM grant + redeploy) is out of code scope; operator runs manually.
- `common/` is a git submodule (origin: deploy-networks-common-). Edits land there.
- Pre-existing submodule diff (stdin redirects + secretmanager API enable) is
  unrelated baseline; my changes build on top.

## Review

All code changes implemented and verified (no live GCP mutations performed —
those are the operator's Section-A step).

Files changed:
- common/create-obs-instance.sh — grant_secret_access() in Step 2 + header + Step-7 note
- common/observability/obs-vm/bringup-remote.sh — access_secret() HTTP-aware errors
- common/observability/obs-vm/startup-obs.sh — Ops Agent install (new §2), renumbered
- common/observability/setup-obs-disk-alert.sh — NEW (chmod 0755)
- common/observability/README.md — file tree, deploy step 5, Disk-fill response runbook
- config.sh — OBS_IMAGE → debian-12 family; OBS_ALERT_EMAIL + OBS_DISK_ALERT_THRESHOLD

Verification done:
- `bash -n` passes on all 5 shell scripts.
- access_secret parsing validated for 403 (prints HTTP 403 + grant hint) and 200
  (decodes payload) paths.
- config.sh sources clean; OBS_ALERT_EMAIL defaults to LETSENCRYPT_EMAIL
  (devs@telcoin.org) and honors an env override.
- `gcloud compute images describe-from-family debian-12` → debian-12-bookworm-v20260528,
  no deprecation state (confirms the warning is gone).
- Exact generated alert-policy JSON parses; Monitoring filter string is well-formed.

Out of code scope (operator runs manually — Section A):
- The two `gcloud secrets add-iam-policy-binding` grants on the CURRENT VM SA, then
  re-run create-obs-instance.sh to unblock the already-provisioned obs-devnet VM.
  (Fresh runs now self-heal via the new grant_secret_access in Step 2.)
- setup-obs-disk-alert.sh must be run once, a few minutes after the VM reports
  disk/percent_used (not auto-called — keeps alpha CLI off the deploy path).

Note: changes to common/* live in the deploy-networks-common- submodule and need a
separate commit there (+ submodule pointer bump in devnet-genesis) when ready.
