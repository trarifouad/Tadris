import pytest

from tadris import app


@pytest.fixture
def env(monkeypatch):
    # _choose_scale writes os.environ itself: set first, so monkeypatch restores the value
    # (or its absence) after the test and no later Qt test runs scaled.
    for key in ("QT_SCALE_FACTOR", app.SCALE_ENV):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)

    def run(platform: str, **values) -> str | None:
        monkeypatch.setattr(app.sys, "platform", platform)
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        app._choose_scale()
        return app.os.environ.get("QT_SCALE_FACTOR")
    return run


def test_linux_opens_at_125_percent(env):
    assert env("linux") == "1.25"


def test_windows_follows_its_own_scale(env):
    assert env("win32") is None


def test_tadris_scale_wins_everywhere(env):
    assert env("win32", TADRIS_SCALE="1,5") == "1.5"


def test_tadris_scale_100_percent_on_linux(env):
    assert env("linux", TADRIS_SCALE="1") == "1.0"


def test_a_qt_scale_already_set_is_kept(env):
    assert env("linux", QT_SCALE_FACTOR="2") == "2"


@pytest.mark.parametrize("value", ["abc", "0.1", "9"])
def test_a_bad_tadris_scale_is_ignored(env, capsys, value):
    assert env("linux", TADRIS_SCALE=value) == "1.25"
    assert "TADRIS_SCALE" in capsys.readouterr().err
