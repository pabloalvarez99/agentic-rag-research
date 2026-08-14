# Security policy

## Supported versions

This repository is pre-release. Security fixes are applied to the latest commit on `main`;
there is no supported release line yet.

## Report a vulnerability

Use GitHub's private vulnerability reporting from the repository's **Security** tab. Do not
open a public issue for a suspected vulnerability, leaked credential, or exploit details.
Include the affected commit, a minimal reproduction, impact, and any suggested mitigation.
Do not include a real credential or personal data in the report.

## Security boundaries

- The default fake backend is local and makes no network request.
- The optional HTTP backend may contact only the configured `PRODUCTION_RAG_URL`; there is no
  arbitrary fetch, shell, filesystem, write, or sub-agent tool.
- Retrieved passages are untrusted input. The current deterministic components score, cite,
  or ignore them; they do not execute passage contents.
- This service has no authentication, authorization, rate limiting, or multi-tenancy. Do not
  expose it directly to an untrusted network.
- `.env.example` documents variable names only. Never commit credentials, tokens, cookies,
  private keys, or connection strings.

If a credential is committed, rotate it first. Removing it from the latest tree does not
remove it from Git history.

