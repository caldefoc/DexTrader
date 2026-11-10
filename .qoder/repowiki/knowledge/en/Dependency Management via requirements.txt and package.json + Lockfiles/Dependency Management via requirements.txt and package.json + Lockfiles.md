---
kind: dependency_management
name: Dependency Management via requirements.txt and package.json + Lockfiles
category: dependency_management
scope:
    - '**'
source_files:
    - backend/requirements.txt
    - frontend/package.json
    - frontend/package-lock.json
    - .github/workflows/ci.yml
---

# Dependency Management

## Systems Used

The repository has two independent dependency graphs, one per subproject:

- **Backend (Python)** — `backend/requirements.txt` pins every runtime dependency to an exact version using the `==` operator. No virtual-environment manager (venv, poetry, uv) is declared; CI installs directly with `pip install -r requirements.txt`. There is no `requirements.lock`, `Pipfile`, `poetry.lock`, or `pyproject.toml` in the repo.
- **Frontend (Node.js / Next.js)** — `frontend/package.json` declares runtime (`dependencies`) and build-time (`devDependencies`) packages with pinned versions. A generated `frontend/package-lock.json` (lockfileVersion 3) records the full transitive tree with `resolved` URLs pointing at `https://registry.npmjs.org/...` and `integrity` hashes for each package.

No vendoring of third-party source code exists anywhere under `backend/` or `frontend/`; `node_modules/` is excluded from the tree shown and is not committed.

## Key Files

| File | Role |
|---|---|
| `backend/requirements.txt` | Canonical list of Python dependencies, all pinned with `==` |
| `frontend/package.json` | Declares npm dependencies and devDependencies |
| `frontend/package-lock.json` | Deterministic lockfile for the frontend graph |
| `.github/workflows/ci.yml` | CI steps that install both graphs |

## CI Integration

`.github/workflows/ci.yml` enforces the following installation/build flow:

- Backend: `actions/setup-python@v5` with `python-version: "3.12"` and `cache: pip`, then `pip install -r requirements.txt`, then `python -m unittest discover -p "test_*.py"`.
- Frontend: `actions/setup-node@v4` with `node-version: "20"`, `cache: npm`, `cache-dependency-path: frontend/package-lock.json`, then `npm ci`, TypeScript check (`npx tsc --noEmit`), and `npm run build`.

The use of `npm ci` (instead of `npm install`) in CI means the frontend lockfile is treated as authoritative — any drift between `package.json` and `package-lock.json` will fail the job.

## Conventions Observed

- **Exact pinning**: Every entry in `backend/requirements.txt` uses `==` (e.g. `fastapi==0.128.0`, `langchain==1.2.12`). The frontend `package.json` also pins versions exactly (e.g. `next: "14.2.3"`, `react: "18.2.0"`, `ethers: "6.13.2"`).
- **Two separate graphs**: Python and Node dependencies are kept in their respective subdirectories with no cross-imports between them.
- **Lockfile usage**: Only the frontend has a committed lockfile (`package-lock.json`). The backend relies on `requirements.txt` alone; reproducibility depends on the state of PyPI at install time.
- **Public registries only**: All resolved URLs in `package-lock.json` point at `https://registry.npmjs.org/`. No `.npmrc`, `PIP_INDEX_URL`, private registry URL, `GOPRIVATE`, or custom index configuration was found.
- **Runtime vs. dev split**: The frontend separates runtime libraries (`next`, `react`, `react-dom`, `ethers`) from tooling (`typescript`, `eslint`, `tailwindcss`, `autoprefixer`, `postcss`, `@types/*`) via `dependencies` vs. `devDependencies`.
- **CI-enforced environment versions**: Python 3.12 and Node 20 are fixed in the workflow, preventing accidental upgrades of the interpreter/toolchain.

## Rules Enforced by the Repository

1. Backend dependencies must be listed in `backend/requirements.txt` with exact `==` pins — this is the only manifest consumed by `pip install -r requirements.txt` in CI.
2. Frontend dependencies must be reflected in both `frontend/package.json` and `frontend/package-lock.json`; `npm ci` in CI will reject a lockfile that does not match `package.json`.
3. Runtime/personal data files (including `trades.json`, `agent_state.json`, etc.) are explicitly blocked from being tracked by Git via the `no-personal-data` CI job, which acts as a guard against committing state that would otherwise pollute the dependency/install surface.