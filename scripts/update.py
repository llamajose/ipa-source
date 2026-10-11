#!/usr/bin/env python3
"""Rebuild source.json from the GitHub repos listed in apps.json.

For each repo: grab its newest release(s), find the .ipa asset, read the
IPA's Info.plist + entitlements, and add any version not already in the
source. Existing history is kept. Standard library only.
"""
import json
import os
import plistlib
import re
import struct
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "apps.json"
SOURCE = ROOT / "source.json"
API = "https://api.github.com"
SKIP_ENTITLEMENTS = {"application-identifier", "com.apple.developer.team-identifier"}


def _request(url, accept="application/vnd.github+json"):
    headers = {"Accept": accept, "User-Agent": "ipa-source-updater"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and url.startswith(API):
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers)


def fetch_json(url):
    with urllib.request.urlopen(_request(url), timeout=60) as r:
        return json.load(r)


def download(url, dest):
    with urllib.request.urlopen(_request(url, "application/octet-stream"), timeout=600) as r, open(dest, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)


def read_entitlements(binary: bytes):
    """Pull the entitlements plist out of a Mach-O's code signature blob."""
    i = binary.find(b"\xfa\xde\x71\x71")  # CSMAGIC_EMBEDDED_ENTITLEMENTS
    while i != -1:
        length = struct.unpack(">I", binary[i + 4:i + 8])[0]
        blob = binary[i + 8:i + length]
        if blob.lstrip().startswith(b"<?xml"):
            try:
                return plistlib.loads(blob)
            except Exception:
                pass
        i = binary.find(b"\xfa\xde\x71\x71", i + 4)
    return {}


def inspect_ipa(path):
    with zipfile.ZipFile(path) as z:
        plist_name = next(n for n in z.namelist()
                          if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", n))
        app_dir = plist_name.rsplit("/", 1)[0]
        info = plistlib.loads(z.read(plist_name))
        exe = info.get("CFBundleExecutable")
        ents = {}
        if exe and f"{app_dir}/{exe}" in z.namelist():
            ents = read_entitlements(z.read(f"{app_dir}/{exe}"))
    return {
        "name": info.get("CFBundleDisplayName") or info.get("CFBundleName"),
        "bundleIdentifier": info["CFBundleIdentifier"],
        "version": str(info.get("CFBundleShortVersionString", "1.0")),
        "buildVersion": str(info.get("CFBundleVersion", "1")),
        "minOSVersion": info.get("MinimumOSVersion"),
        "entitlements": sorted(k for k in ents if k not in SKIP_ENTITLEMENTS),
        "privacy": {k: v for k, v in info.items()
                    if k.startswith("NS") and k.endswith("UsageDescription")},
    }


def pick_asset(release, pattern):
    rx = re.compile(pattern or r"\.ipa$", re.I)
    return next((a for a in release.get("assets", []) if rx.search(a["name"])), None)


def update_app(entry, existing):
    repo = entry["repo"]
    releases = fetch_json(f"{API}/repos/{repo}/releases?per_page=50")
    releases = [r for r in releases if not r["draft"]
                and (entry.get("prerelease", False) or not r["prerelease"])]
    releases = releases[:entry.get("releases", 1)]

    app = existing or {}
    versions = app.get("versions", [])
    known = {v["downloadURL"] for v in versions}
    meta = None

    for rel in releases:
        asset = pick_asset(rel, entry.get("asset"))
        if not asset or asset["browser_download_url"] in known:
            continue
        print(f"  new: {rel['tag_name']} -> {asset['name']}")
        with tempfile.TemporaryDirectory() as tmp:
            ipa = Path(tmp) / "app.ipa"
            download(asset["browser_download_url"], ipa)
            this = inspect_ipa(ipa)
        meta = meta or this  # releases are newest-first, so first new one wins
        v = {
            "version": this["version"],
            "buildVersion": this["buildVersion"],
            "date": rel["published_at"],
            "localizedDescription": (rel.get("body") or rel["tag_name"]).strip()[:4000],
            "downloadURL": asset["browser_download_url"],
            "size": asset["size"],
        }
        if this["minOSVersion"]:
            v["minOSVersion"] = this["minOSVersion"]
        versions.append(v)

    if not versions:
        print(f"  no IPA found in {repo} releases, skipping")
        return existing

    versions.sort(key=lambda v: v["date"], reverse=True)
    versions = versions[:entry.get("keep", 10)]

    owner = repo.split("/")[0]
    app.update({
        "name": entry.get("name") or app.get("name") or (meta or {}).get("name") or repo.split("/")[1],
        "bundleIdentifier": (meta or {}).get("bundleIdentifier") or app["bundleIdentifier"],
        "developerName": entry.get("developerName") or app.get("developerName") or owner,
        "subtitle": entry.get("subtitle", app.get("subtitle", "")),
        "localizedDescription": entry.get("description") or app.get("localizedDescription") or f"Built from github.com/{repo}",
        "iconURL": entry.get("iconURL") or app.get("iconURL") or f"https://github.com/{owner}.png",
        "category": entry.get("category", app.get("category", "other")),
        "versions": versions,
    })
    if meta:
        app["appPermissions"] = {"entitlements": meta["entitlements"], "privacy": meta["privacy"]}
    app.setdefault("appPermissions", {"entitlements": [], "privacy": {}})
    return app


def main():
    config = json.loads(CONFIG.read_text())
    source = json.loads(SOURCE.read_text()) if SOURCE.exists() else {}
    by_repo = {a.get("_repo"): a for a in source.get("apps", [])}

    apps = []
    for entry in config["apps"]:
        print(entry["repo"])
        try:
            app = update_app(entry, by_repo.get(entry["repo"]))
        except Exception as e:  # one broken repo shouldn't kill the run
            print(f"  ERROR: {e}", file=sys.stderr)
            app = by_repo.get(entry["repo"])
        if app:
            app["_repo"] = entry["repo"]
            apps.append(app)

    out = {k: v for k, v in config["source"].items()}
    out["apps"] = apps
    out.setdefault("news", source.get("news", []))
    SOURCE.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
