# Handling exposed secrets (runbook)

Follow this playbook when a `.env` file is accidentally committed. Once a secret appears in public history it must be treated as compromised—rotate and eradicate it using the steps below.

## 1. Immediate revocation and rotation
- Rotate API keys, passwords, and other secrets in the operational environment (secret store / configuration) right away.
- Update the application’s `.env` or deployment environment variables and restart services.

## 2. Remove from the repository (current commit)
- Add `.env` to `.gitignore`.
- Delete `.env` from the working tree (keep local copies outside of Git as needed).

## 3. Purge from history (optional, disruptive)
Erasing `.env` from existing history requires rewriting commits, which affects forks, open PRs, and tags.

### Example (recommended: `git filter-repo`)
```
pipx install git-filter-repo  # or another installation method
git filter-repo --invert-paths --path .env
git push --force-with-lease origin main
```

Notes: obtain organizational approval, adjust branch protections, and communicate broadly. Even after rewriting history, anyone with a previous clone can recover the secret, so rotation is mandatory.

## 4. Prevent recurrence
- Keep `.env` and other sensitive files in `.gitignore`.
- Version only sanitized templates such as `configs/env.example`; store real values in local or CI secret stores.
- Add pre-push hooks or CI checks to detect `.env` files when necessary.
