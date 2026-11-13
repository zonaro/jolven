# SPDX-License-Identifier: GPL-3.0-or-later
"""Portable, offline user playlists keyed by Jolven's existing game_id.

No copied Game records, no Steam injection and no destructive library edits.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

_FORMAT = "jolven-playlists"
_VERSION = 1
_MAX_FILE_BYTES = 4 * 1024 * 1024
_MAX_LISTS = 100
_MAX_GAMES = 10_000


class PlaylistStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @staticmethod
    def _validate(data: object) -> list[dict]:
        if not isinstance(data, dict):
            raise ValueError("Invalid playlist manifest")
        if data.get("format") != _FORMAT or data.get("version") != _VERSION:
            raise ValueError("Unsupported playlist version")
        lists = data.get("playlists")
        if not isinstance(lists, list) or len(lists) > _MAX_LISTS:
            raise ValueError("Invalid playlist collection")

        parsed: list[dict] = []
        ids: set[str] = set()
        for item in lists:
            if not isinstance(item, dict):
                raise ValueError("Invalid playlist record")
            playlist_id = item.get("id")
            title = item.get("title")
            games = item.get("games")
            if (
                not isinstance(playlist_id, str) or len(playlist_id) > 100
                or not isinstance(title, str) or not 1 <= len(title.strip()) <= 72
                or not isinstance(games, list) or len(games) > _MAX_GAMES
            ):
                raise ValueError("Invalid playlist record fields")
            try:
                uuid.UUID(playlist_id)
            except (ValueError, AttributeError) as error:
                raise ValueError("Invalid playlist ID") from error
            if playlist_id in ids:
                raise ValueError("Duplicate playlist ID")
            ids.add(playlist_id)
            if any(
                not isinstance(game, str)
                or len(game) not in range(1, 201)
                or "\x00" in game
                for game in games
            ):
                raise ValueError("Invalid game ID")
            if len(games) != len(set(games)):
                raise ValueError("Duplicate membership")
            parsed.append({"id": playlist_id, "title": title.strip(), "games": list(games)})
        return parsed

    def all(self) -> list[dict]:
        if not self.path.exists():
            return []
        if self.path.stat().st_size > _MAX_FILE_BYTES:
            raise ValueError("Playlists file too large")
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeDecodeError) as error:
            raise ValueError("Playlists could not be read; original remains untouched") from error
        return self._validate(data)

    def _save(self, playlists: list[dict]) -> None:
        self._validate({"format": _FORMAT, "version": _VERSION, "playlists": playlists})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({
            "format": _FORMAT,
            "version": _VERSION,
            "playlists": playlists,
        }, ensure_ascii=False, separators=(",", ":"))
        if len(payload.encode("utf-8")) > _MAX_FILE_BYTES:
            raise ValueError("Playlists file exceeds size limit")
        temp: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent,
                prefix=".jolven-playlists-", delete=False
            ) as handle:
                temp = Path(handle.name)
                os.chmod(temp, 0o600)
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
            temp = None
        finally:
            if temp is not None:
                temp.unlink(missing_ok=True)

    def create(self, title: str) -> dict:
        name = title.strip()
        if not 1 <= len(name) <= 72:
            raise ValueError("Invalid playlist title")
        all_lists = self.all()
        if len(all_lists) >= _MAX_LISTS:
            raise ValueError("Too many playlists")
        if any(p["title"].casefold() == name.casefold() for p in all_lists):
            raise ValueError("Playlist title already exists")
        playlist = {"id": str(uuid.uuid4()), "title": name, "games": []}
        self._save([*all_lists, playlist])
        return dict(playlist, games=[])

    def rename(self, playlist_id: str, title: str) -> None:
        name = title.strip()
        if not 1 <= len(name) <= 72:
            raise ValueError("Invalid playlist title")
        playlists = self.all()
        if not any(p["id"] == playlist_id for p in playlists):
            raise KeyError("Playlist missing")
        if any(
            p["id"] != playlist_id and p["title"].casefold() == name.casefold()
            for p in playlists
        ):
            raise ValueError("Playlist title already exists")
        for playlist in playlists:
            if playlist["id"] == playlist_id:
                playlist["title"] = name
        self._save(playlists)

    def delete(self, playlist_id: str) -> None:
        playlists = self.all()
        updated = [p for p in playlists if p["id"] != playlist_id]
        if len(updated) == len(playlists):
            raise KeyError("Playlist missing")
        self._save(updated)

    def set_member(self, playlist_id: str, game_id: str, include: bool) -> None:
        if not game_id or len(game_id) > 200 or "\x00" in game_id:
            raise ValueError("Invalid game ID")
        playlists = self.all()
        target = next((p for p in playlists if p["id"] == playlist_id), None)
        if target is None:
            raise KeyError("Playlist missing")
        members = target["games"]
        if include and game_id not in members:
            if len(members) >= _MAX_GAMES:
                raise ValueError("Playlist has too many games")
            members.append(game_id)
        if not include and game_id in members:
            members.remove(game_id)
        self._save(playlists)

    def reorder(self, playlist_id: str, game_ids: list[str]) -> None:
        playlists = self.all()
        target = next((p for p in playlists if p["id"] == playlist_id), None)
        if target is None:
            raise KeyError("Playlist missing")
        if (
            len(game_ids) != len(target["games"])
            or len(game_ids) != len(set(game_ids))
            or set(game_ids) != set(target["games"])
        ):
            raise ValueError("Reorder must preserve exact playlist membership")
        target["games"] = list(game_ids)
        self._save(playlists)
