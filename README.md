# Process Champion Challenge

A separate Streamlit gamification simulation for a manufacturing-excellence kickoff. Teams choose improvement actions across four rounds and compete on productivity, process stability, Cp, Cpk, yield, and budget efficiency.

## Repository structure

```text
cp-cpk-gamification/
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── config/
│   └── actions.json
├── data/
│   ├── leaderboard.csv
│   └── simulation_log.csv
└── assets/
```

## GitHub upload

1. Create a new GitHub repository, for example `cp-cpk-gamification`.
2. Extract the ZIP.
3. Upload the contents of the extracted folder to the repository root.
4. Preserve the `.streamlit`, `config`, `data`, and `assets` folders.
5. Commit to the `main` branch.

## Fine-grained token

Select only this repository and grant:

- Contents: Read and write

## Streamlit secrets

Paste the following in Streamlit Community Cloud under App Settings → Secrets:

```toml
GITHUB_TOKEN="github_pat_replace_me"
GITHUB_OWNER="your_github_username_or_organization"
GITHUB_REPO="cp-cpk-gamification"
GITHUB_BRANCH="main"
SIMULATION_ADMIN_PASSWORD="Admin@2026"
```

## Streamlit deployment

- Repository: `owner/cp-cpk-gamification`
- Branch: `main`
- Main file path: `app.py`

## Gameplay

- Four rounds
- Maximum two selected improvement actions per round
- Random process event in every round
- Starting budget: 100 points
- Highest balanced total score wins

The generated process readings are synthetic simulation data and must not be treated as actual plant-production records.
