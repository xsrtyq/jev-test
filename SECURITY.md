# Security Policy

This repository is a research harness and is not intended to authorize production actions.

## Secrets

Never commit or paste API keys, access tokens, private keys, customer credentials, or real confidential traces. Use environment variables or GitHub Actions secrets for authorized live runs.

If you believe a credential has been exposed:
1. revoke/rotate it at the provider first;
2. do not paste the credential into a public issue;
3. use GitHub's private vulnerability reporting feature if it is available for this repository;
4. otherwise open a minimal public issue that contains no secret and asks the maintainer for a private contact path.

## Supported scope

Security-relevant reports include:
- secret leakage from logs or artifacts;
- a workflow that can trigger paid/external actions without explicit authorization;
- unsafe artifact handling;
- prompt/model output being able to bypass deterministic permission or provenance controls.

Research-quality disagreements and benchmark-methodology issues should use normal issues rather than security reporting.
