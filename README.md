# Process Champion Live Simulation

GitHub-ready Streamlit simulation with an animated tile-manufacturing flow from Slip House through Spray Dryer, Silo, Press, Glaze Line, Kiln, Polishing, and Sorting & Packing.

## Fix for missing GITHUB_OWNER

The updated app runs in local leaderboard mode when GitHub secrets are missing. It no longer displays an exception to participants. For a shared leaderboard across devices, add all GitHub secrets in Streamlit App Settings.

```toml
GITHUB_TOKEN="github_pat_replace_me"
GITHUB_OWNER="your_exact_github_username_or_organization"
GITHUB_REPO="process-champion-live-simulation"
GITHUB_BRANCH="main"
```

## Upload structure

```text
repository-root/
├── app.py
├── requirements.txt
├── README.md
├── .gitignore
├── .streamlit/
│   ├── config.toml
│   └── secrets.toml.example
├── config/
│   └── actions.json
└── data/
    ├── leaderboard.csv
    └── simulation_log.csv
```

## Streamlit deployment

- Repository: `owner/process-champion-live-simulation`
- Branch: `main`
- Main file path: `app.py`

The app uses synthetic training data only.
