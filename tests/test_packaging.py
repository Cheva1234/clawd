import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pyproject_installs_a_clawd_command_that_exists():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["project"]["scripts"]["clawd"] == "clawd.__main__:main"
    from clawd.__main__ import main

    assert callable(main)


def test_the_package_is_found_by_the_build_backend():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert project["build-system"]["build-backend"] == "setuptools.build_meta"
    assert project["tool"]["setuptools"]["packages"] == ["clawd"]


def test_no_machine_specific_path_is_baked_into_the_code():
    import re

    for path in list((ROOT / "clawd").glob("*.py")) + [ROOT / "plugin" / "hooks" / "register.ts"]:
        assert not re.search(r"/home/(?!x/|user/)\w+", path.read_text()), path


def test_the_default_voice_is_a_standard_one_that_works_with_any_account():
    from clawd.config import Config

    assert Config().voice_id == "JBFqnCBsd6RMkjVDRZzb"
