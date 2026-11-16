# Bench-7 issue titles

Slug, repository and the title passed to `gh issue create --title` by `POST_SET=bench7 tasks/bench7/orch-gh-post.sh issue <slug>`.
Bodies: `tasks/issue-bodies/bench7-<slug>.md`. Every title is the body's H1 and at most 120 characters.
The second report goes to another repository: `GH_REPO=Telcoin-Association/tn-node-deployment`.

| order | slug | title | length |
|---|---|---|---|
| 1 | far-validator-batches-not-committed | A far validator's certified headers often go uncommitted, so its batches wait up to about 50-60 rounds to be re-proposed | 120 |
| 2 | metrics-agent-network-relabel | The metrics agent overwrites the node's own `network` label, so some nodes lose one remote-write batch per scrape | 113 |
