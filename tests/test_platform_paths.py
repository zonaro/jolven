# test_platform_paths.py
#
# Copyright 2026 zonaro
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Testes dos caminhos por plataforma.

O backend do Windows e exercitado trocando `paths._IS_WINDOWS` e as variaveis de
ambiente, que e como o codigo decide o diretorio.
"""

import os
import unittest
from pathlib import Path
from unittest import mock

from cartridges.platform import paths

WINDOWS_ENV = {
    "APPDATA": r"C:\Users\player\AppData\Roaming",
    "LOCALAPPDATA": r"C:\Users\player\AppData\Local",
    "ProgramFiles": r"C:\Program Files",
}

LINUX_ENV = {
    "XDG_DATA_HOME": "/home/player/.local/share",
    "XDG_CONFIG_HOME": "/home/player/.config",
    "XDG_CACHE_HOME": "/home/player/.cache",
}


class _PlatformTestCase(unittest.TestCase):
    is_windows = False
    env: dict[str, str] = {}

    def setUp(self):
        self._force_platform(self.is_windows)
        self._force_env(self.env)

    def _force_platform(self, is_windows: bool) -> None:
        patcher = mock.patch.object(paths, "_IS_WINDOWS", is_windows)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _force_env(self, env: dict[str, str]) -> None:
        patcher = mock.patch.dict(
            os.environ, {**env, "HOME": "/home/player"}, clear=False
        )
        patcher.start()
        self.addCleanup(patcher.stop)


class WindowsPathsTest(_PlatformTestCase):
    is_windows = True
    env = WINDOWS_ENV

    def test_data_and_config_share_roaming(self):
        appdata = Path(WINDOWS_ENV["APPDATA"])
        self.assertEqual(paths.data_dir(), appdata / "jolven")
        self.assertEqual(paths.config_dir(), appdata / "jolven")

    def test_cache_stays_out_of_inet_cache(self):
        expected = Path(WINDOWS_ENV["LOCALAPPDATA"]) / "jolven" / "cache"
        self.assertEqual(paths.cache_dir(), expected)
        self.assertEqual(paths.logs_dir(), expected / "logs")

    def test_third_party_locations(self):
        self.assertEqual(paths.appdata_dir(), Path(WINDOWS_ENV["APPDATA"]))
        self.assertEqual(
            paths.local_appdata_dir(), Path(WINDOWS_ENV["LOCALAPPDATA"])
        )
        self.assertEqual(
            paths.program_files_dir(), Path(WINDOWS_ENV["ProgramFiles"])
        )


class LinuxPathsTest(_PlatformTestCase):
    is_windows = False
    env = LINUX_ENV

    def test_xdg_directories(self):
        self.assertEqual(
            paths.data_dir(), Path(LINUX_ENV["XDG_DATA_HOME"]) / "jolven"
        )
        self.assertEqual(
            paths.config_dir(), Path(LINUX_ENV["XDG_CONFIG_HOME"]) / "jolven"
        )
        self.assertEqual(
            paths.cache_dir(), Path(LINUX_ENV["XDG_CACHE_HOME"]) / "jolven"
        )

    def test_falls_back_to_home(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/player"}, clear=True):
            self.assertEqual(
                paths.data_dir(), Path("/home/player/.local/share/jolven")
            )
            self.assertEqual(paths.config_dir(), Path("/home/player/.config/jolven"))
            self.assertEqual(paths.cache_dir(), Path("/home/player/.cache/jolven"))

    def test_third_party_locations_are_windows_only(self):
        self.assertIsNone(paths.appdata_dir())
        self.assertIsNone(paths.local_appdata_dir())
        self.assertIsNone(paths.program_files_dir())


if __name__ == "__main__":
    unittest.main()
