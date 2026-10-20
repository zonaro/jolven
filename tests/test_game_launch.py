import unittest

from cartridges.game_launch import GameProfile, append_uzdoom_mods, build_game_command


def programs(*available):
    return lambda name: f"/usr/bin/{name}" if name in available else None


class GameLaunchTests(unittest.TestCase):
    def test_command_is_unchanged_without_integrations(self):
        self.assertEqual(
            build_game_command("steam steam://rungameid/10", find_program=programs()),
            ("steam steam://rungameid/10", ()),
        )

    def test_gamemode_wraps_game_only_when_installed(self):
        command, enabled = build_game_command(
            'flatpak run "com.example.Game"',
            use_gamemode=True,
            find_program=programs("gamemoderun"),
        )
        self.assertEqual(command, 'gamemoderun flatpak run "com.example.Game"')
        self.assertEqual(enabled, ("gamemode",))

    def test_missing_gamemode_is_safe_fallback(self):
        command, enabled = build_game_command(
            "/opt/game/game", use_gamemode=True, find_program=programs()
        )
        self.assertEqual(command, "/opt/game/game")
        self.assertEqual(enabled, ())

    def test_wrappers_have_stable_order(self):
        command, enabled = build_game_command(
            "wine game.exe",
            use_gamemode=True,
            use_mangohud=True,
            find_program=programs("gamemoderun", "mangohud"),
        )
        self.assertEqual(command, "gamemoderun mangohud wine game.exe")
        self.assertEqual(enabled, ("mangohud", "gamemode"))

    def test_profile_carries_future_per_game_settings(self):
        profile = GameProfile(
            executable="game", fps_limit=60, resolution=(1920, 1080)
        )
        self.assertEqual(profile.resolution, (1920, 1080))

    def test_per_game_gamescope_profile(self):
        command, enabled = build_game_command(
            "game",
            fps_limit=40,
            resolution="1920x1080",
            scaling_mode="fit",
            find_program=programs("gamescope"),
        )
        self.assertEqual(
            command,
            "gamescope --framerate-limit 40 -W 1920 -H 1080 -S fit -- game",
        )
        self.assertEqual(enabled, ("gamescope",))

    def test_dedicated_session_does_not_nest_gamescope(self):
        command, enabled = build_game_command(
            "game",
            fps_limit=60,
            allow_gamescope=False,
            find_program=programs("gamescope"),
        )
        self.assertEqual((command, enabled), ("game", ()))


class UzdoomModsTests(unittest.TestCase):
    def test_no_mods_leaves_the_command_untouched(self):
        self.assertEqual(
            append_uzdoom_mods("uzdoom -iwad doom2.wad", []),
            "uzdoom -iwad doom2.wad",
        )

    def test_single_mod_is_appended(self):
        self.assertEqual(
            append_uzdoom_mods("uzdoom -iwad doom2.wad", ["/games/mods/cool.wad"]),
            "uzdoom -iwad doom2.wad -file /games/mods/cool.wad",
        )

    def test_mods_keep_their_order(self):
        self.assertEqual(
            append_uzdoom_mods(
                "uzdoom -iwad doom2.wad",
                ["/mods/first.wad", "/mods/second.wad", "/mods/third.pk3"],
            ),
            "uzdoom -iwad doom2.wad -file "
            "/mods/first.wad /mods/second.wad /mods/third.pk3",
        )

    def test_mod_with_spaces_is_quoted(self):
        self.assertEqual(
            append_uzdoom_mods("uzdoom", ["/mods/my cool mod.wad"]),
            "uzdoom -file '/mods/my cool mod.wad'",
        )

    def test_only_one_file_flag_is_used(self):
        command = append_uzdoom_mods(
            "uzdoom", ["/mods/one.wad", "/mods/two.wad", "/mods/three.pk3"]
        )
        self.assertEqual(command.count("-file"), 1)


if __name__ == "__main__":
    unittest.main()
