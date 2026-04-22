#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Load and resolve extraction profiles for normalized WeChat content."""

from __future__ import annotations

import json
from pathlib import Path


PROFILE_DIR = Path(__file__).resolve().parent / "profiles"


def _iter_profile_files():
    if not PROFILE_DIR.exists():
        return []
    return sorted(PROFILE_DIR.rglob("*.json"))


def load_profiles(profile_dir: Path | None = None):
    base_dir = Path(profile_dir) if profile_dir else PROFILE_DIR
    profiles = {}
    if not base_dir.exists():
        return profiles
    for path in sorted(base_dir.rglob("*.json")):
        with path.open("r", encoding="utf-8") as f:
            profile = json.load(f)
        name = (profile.get("name") or "").strip()
        version = (profile.get("version") or "").strip()
        if not name:
            raise ValueError(f"Profile missing name: {path}")
        if not version:
            raise ValueError(f"Profile missing version: {path}")
        profile.setdefault("source", "wechat")
        profile.setdefault("account_match", {})
        profile.setdefault("root_selectors", ["#js_content"])
        profile.setdefault("remove_selectors", [])
        profile.setdefault("lead_trim_patterns", [])
        profile.setdefault("trailing_trim_patterns", [])
        profile.setdefault("preserve_selectors", [])
        profile.setdefault("block_drop_patterns", [])
        profile.setdefault("ocr", {})
        profiles[name] = profile
    return profiles


class ProfileResolver:
    def __init__(self, profile_dir: Path | None = None):
        self.profile_dir = Path(profile_dir) if profile_dir else PROFILE_DIR
        self.profiles = load_profiles(self.profile_dir)
        if "default" not in self.profiles:
            raise ValueError("Missing required default extraction profile")

    def list_profiles(self):
        return self.profiles

    def get_profile(self, name: str):
        profile = self.profiles.get((name or "").strip())
        if not profile:
            raise RuntimeError(f"未找到抽取 profile: {name}")
        return profile

    def resolve_for_account(self, account: dict | None):
        account = account or {}
        explicit = (account.get("extraction_profile") or "").strip()
        if explicit:
            return self.get_profile(explicit)

        nickname = (account.get("nickname") or "").strip()
        alias = (account.get("alias") or "").strip()

        for profile in self.profiles.values():
            account_match = profile.get("account_match") or {}
            nicknames = {item.strip() for item in account_match.get("nickname", []) if item and item.strip()}
            aliases = {item.strip() for item in account_match.get("alias", []) if item and item.strip()}
            if nickname and nickname in nicknames:
                return profile
            if alias and alias in aliases:
                return profile

        return self.profiles["default"]
