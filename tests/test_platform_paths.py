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

"""Testes dos caminhos Linux/XDG sem dependencias de interface grafica."""

import os
import unittest
from pathlib import Path
from unittest import mock

from cartridges.platform import paths

LINUX_ENV = {
    "XDG_DATA_HOME": "/home/player/.local/share",
    "XDG_CONFIG_HOME": "/home/player/.config",
    "XDG_CACHE_HOME": "/home/player/.cache",
}


class _PlatformTestCase(unittest.TestCase):
    env: dict[str, str] = {}

    def setUp(self):
        patcher = mock.patch.dict(os.environ, {**self.env, "HOME": "/home/player"}, clear=False)
        patcher.start()
        self.addCleanup(patcher.stop)


class LinuxPathsTest(_PlatformTestCase):
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

    def test_base_directories(self):
        self.assertEqual(
            paths.base_data_dir(), Path(LINUX_ENV["XDG_DATA_HOME"])
        )
        self.assertEqual(
            paths.base_config_dir(), Path(LINUX_ENV["XDG_CONFIG_HOME"])
        )
        self.assertEqual(
            paths.base_cache_dir(), Path(LINUX_ENV["XDG_CACHE_HOME"])
        )

    def test_base_directories_fall_back_to_home(self):
        with mock.patch.dict(os.environ, {"HOME": "/home/player"}, clear=True):
            self.assertEqual(
                paths.base_data_dir(), Path("/home/player/.local/share")
            )
            self.assertEqual(
                paths.base_config_dir(), Path("/home/player/.config")
            )
            self.assertEqual(
                paths.base_cache_dir(), Path("/home/player/.cache")
            )



if __name__ == "__main__":
    unittest.main()
