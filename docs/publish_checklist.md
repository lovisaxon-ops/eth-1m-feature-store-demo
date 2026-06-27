# Public Publish Checklist

Before pushing this folder to GitHub:

- Run a secret scan on this folder only.
- Confirm there are no `.env` or `*.env` files except `.env.example`.
- Confirm no API keys, private keys, wallet mnemonics, passwords, or DB credentials.
- Confirm no production account IDs, wallet addresses, trade logs, or live state files.
- Confirm no `.keras`, `.joblib`, `.pkl`, `.h5`, or other model artifacts.
- Confirm no full-history commercial/raw datasets.
- Confirm no production strategy thresholds or raw optimization sweeps.
- Confirm `.gitignore` excludes generated databases, logs, env files, and large artifacts.
- Create a new Git repository inside this folder, not from the parent `server` folder.
- Review `NOTICE.md` and decide whether to keep source-available terms or add a formal license.

Suggested first commit:

```bash
git init
git add .
git status --short
git commit -m "Add public ETH 1m feature store demo"
```

