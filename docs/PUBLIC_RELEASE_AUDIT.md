# Public release audit — 2026-09-22

This checklist records the repository state prepared for public release.

## Completed

- README rewritten to reflect the final frozen research state rather than the original v0.1 plan.
- MIT license added.
- CONTRIBUTING.md and SECURITY.md added.
- Final positive and negative results are linked from the README.
- Current default-branch code was searched for obvious credential/private-key patterns; no matching committed credential value was found.
- Paid GitHub Actions remain manual workflow_dispatch jobs.
- Push/pull-request verification workflows have read-only contents permissions and do not receive paid-service secrets.
- No pull_request_target workflow is present.
- Experiment fixtures are synthetic; the public README explicitly warns against uploading real customer/private traces.
- Negative results, censored outcomes, and known methodology flaws remain documented rather than being removed for presentation.

## Important pre-publication caveats

1. Git commit metadata becomes public with the repository. Review historical author/committer names and email addresses if you do not want them exposed.
2. Existing GitHub Actions run logs and other repository history may become visible according to GitHub's public-repository behavior. Secrets were masked/scanned in the experiment workflows, but this audit is not a complete historical secret-scanning product.
3. Repository Secrets themselves are not exposed by changing repository visibility, but do not assume an old committed credential is protected merely because the repository used to be private.
4. The benchmark numbers are research snapshots, not vendor rankings or production guarantees.

## Release position

The recommended public description is: an independent reproducible research harness with a negative/freeze conclusion on the current standalone Jev context-manager hypothesis, while preserving evidence for future semantic-routing work.
