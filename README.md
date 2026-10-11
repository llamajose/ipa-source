# ipa-source

Self-updating AltStore-format source. A GitHub Action checks the repos in
`apps.json` every 6 hours, pulls the newest `.ipa` from their releases, reads
the bundle ID / version / entitlements straight out of the IPA, and rewrites
`source.json`. Works in AltStore, SideStore, Feather, and LiveContainer.

## Setup

1. Create a **public** repo named `ipa-source` and upload these files.
2. Settings → Actions → General → Workflow permissions → **Read and write**.
3. Actions tab → **Update source** → **Run workflow**.
4. Add this URL in your sideloader:
   `https://raw.githubusercontent.com/llamajose/ipa-source/main/source.json`

## Adding an app

Add an entry to `apps.json` and commit. The workflow runs on its own.

```json
{ "repo": "owner/name" }
```

Optional fields:

| key | default | what it does |
|---|---|---|
| `name` | from IPA | display name |
| `description` | `Built from github.com/...` | store page text |
| `iconURL` | owner's GitHub avatar | app icon |
| `category` | `other` | `developer`, `entertainment`, `games`, `lifestyle`, `photo-video`, `social`, `utilities` |
| `asset` | `\.ipa$` | regex to pick the right file when a release has several IPAs |
| `prerelease` | `false` | include beta/pre-releases |
| `releases` | `1` | how many recent releases to check (raise it to backfill history) |
| `keep` | `10` | max versions kept in the source |

## Limits

- Only works for repos that publish the IPA as a GitHub Release asset.
- Entitlements are read from the main binary only. If AltStore Classic rejects
  an install for an entitlement mismatch, use SideStore or Feather.
- `raw.githubusercontent.com` caches for ~5 minutes, so updates show up
  a few minutes after the commit.
