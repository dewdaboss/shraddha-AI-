"""The model fetcher, tested without the network.

A download is the one step that cannot run in CI, so everything around it is pinned:
the catalogue, the alias expansion, and the archive handling (including a zip-slip
attempt).
"""

from __future__ import annotations

import importlib.util
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "fetch_models.py"


@pytest.fixture(scope="module")
def fetcher():
    spec = importlib.util.spec_from_file_location("fetch_models", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["fetch_models"] = module
    spec.loader.exec_module(module)
    return module


def test_every_set_is_pinned(fetcher) -> None:
    assert set(fetcher.SETS) == {"asr-light", "asr-main", "tts-piper"}
    for name, assets in fetcher.SETS.items():
        assert assets, f"{name} has no assets"
        for asset in assets:
            assert asset.url.startswith("https://")
            assert asset.licence, f"{name} must declare a licence"
            assert asset.size_mb > 0


def test_the_licences_are_the_documented_ones(fetcher) -> None:
    light = fetcher.SETS["asr-light"][0]
    main = fetcher.SETS["asr-main"][0]
    piper = fetcher.SETS["tts-piper"][0]
    assert light.licence == "Apache-2.0"
    assert main.licence.startswith("CC-BY")
    assert "NON-COMMERCIAL" in piper.licence


def test_the_alias_expands_to_light_assets(fetcher) -> None:
    names = {asset.filename for asset in fetcher.resolve_sets(["all-light"])}
    assert "vosk-model-small-hi-0.22.zip" in names
    assert any(name.endswith(".onnx") for name in names)


def test_duplicates_are_fetched_once(fetcher) -> None:
    assets = fetcher.resolve_sets(["asr-light", "asr-light"])
    assert len(assets) == len({asset.filename for asset in assets})


def test_an_unknown_set_is_an_error(fetcher) -> None:
    with pytest.raises(KeyError):
        fetcher.resolve_sets(["nope"])


def test_listing_prints_the_catalogue(fetcher, capsys) -> None:
    assert fetcher.main(["--list"]) == 0
    printed = capsys.readouterr().out
    assert "asr-light" in printed
    assert "Apache-2.0" in printed


def test_a_dry_run_touches_nothing(fetcher, app_home, capsys) -> None:
    assert fetcher.main(["--set", "asr-light", "--dry-run"]) == 0
    printed = capsys.readouterr().out
    assert "would fetch" in printed
    assert not any(fetcher.get_paths().models.rglob("*.zip"))


def test_a_zip_is_extracted_and_removed(fetcher, tmp_path: Path, capsys) -> None:
    archive = tmp_path / "vosk-model-small-hi-0.22.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("vosk-model-small-hi-0.22/am/final.mdl", b"\x00")
        bundle.writestr("vosk-model-small-hi-0.22/conf/model.conf", b"x")

    model_dir = fetcher.extract_archive(archive, tmp_path)

    assert model_dir is not None
    assert (model_dir / "am" / "final.mdl").is_file()
    assert not archive.exists(), "the archive is not needed once unpacked"
    assert "unzip" in capsys.readouterr().out


def test_loose_files_are_not_extracted(fetcher, tmp_path: Path) -> None:
    model = tmp_path / "hi_IN-priyamvada-medium.onnx"
    model.write_bytes(b"\x00")
    assert fetcher.extract_archive(model, tmp_path) is None
    assert model.exists()


def test_a_traversing_member_is_refused(fetcher, tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("../escape.txt", b"x")

    with pytest.raises(RuntimeError, match="outside"):
        fetcher.extract_archive(archive, tmp_path / "models")
    assert not (tmp_path / "escape.txt").exists()


def test_the_extracted_model_is_then_discoverable(fetcher, tmp_path: Path) -> None:
    """The whole point: fetch -> extract -> the recogniser finds the model."""
    from shraddha.speech.engines.vosk_engine import find_model_dir

    archive = tmp_path / "vosk-model-small-hi-0.22.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("vosk-model-small-hi-0.22/am/final.mdl", b"\x00")

    fetcher.extract_archive(archive, tmp_path)
    assert find_model_dir(tmp_path) is not None


def test_a_checksum_mismatch_is_reported(fetcher, tmp_path: Path) -> None:
    asset = fetcher.Asset(
        url="https://example.invalid/x", filename="x.bin", size_mb=1, licence="MIT"
    )
    target = tmp_path / "x.bin"
    target.write_bytes(b"payload")
    asset = fetcher.Asset(
        url=asset.url, filename=asset.filename, size_mb=1, licence="MIT", sha256="deadbeef"
    )
    with pytest.raises(RuntimeError, match="checksum"):
        fetcher.download(asset, tmp_path)
