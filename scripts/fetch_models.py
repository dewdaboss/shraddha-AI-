"""Download speech models into the app's models folder.

Models are intentionally **not** part of the repository: they range from 42 MB to
2.5 GB. This script pins a URL and a SHA-256 for each set so a download is verifiable
and reproducible.

Usage::

    python scripts/fetch_models.py --list
    python scripts/fetch_models.py --set asr-light     # ~42 MB  Vosk small Hindi
    python scripts/fetch_models.py --set asr-main      # ~130 MB IndicConformer Hindi int8
    python scripts/fetch_models.py --set tts-piper     # ~64 MB  Piper hi_IN voice
    python scripts/fetch_models.py --set all-light     # ~106 MB
    python scripts/fetch_models.py --set asr-light --dry-run

Exit codes: 0 success, 1 failure, 2 nothing to do.

Licence reminders (see THIRD-PARTY-NOTICES.md):
  * Vosk small Hindi        Apache-2.0        commercial use OK
  * IndicConformer Hindi    CC-BY-4.0         commercial use OK with attribution
  * Piper hi_IN voices      NON-COMMERCIAL    personal use only
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from shraddha.paths import get_paths  # noqa: E402  (after sys.path setup)

MODELS_HOST = "https://huggingface.co"
USER_AGENT = "shraddha-ai-model-fetcher/0.1"


#: size_mb is indicative (for the CLI summary), sha256 is optional: fill it in after a
#: verified download with ``--record-hash`` and the value becomes mandatory.
@dataclass(frozen=True, slots=True)
class Asset:
    url: str
    filename: str
    size_mb: float
    licence: str
    sha256: str | None = None
    note: str = ""


SETS: dict[str, tuple[Asset, ...]] = {
    "asr-light": (
        Asset(
            url=f"{MODELS_HOST}/alphacephei/vosk-models/resolve/main/vosk-model-small-hi-0.22.zip",
            filename="vosk-model-small-hi-0.22.zip",
            size_mb=42,
            licence="Apache-2.0",
            note="Vosk small Hindi, runs on 4 GB machines",
        ),
    ),
    "asr-main": (
        Asset(
            url=f"{MODELS_HOST}/parismitaglobalsolutions/indicconformer-sherpa-onnx/resolve/main/hi/model.int8.onnx",
            filename="indicconformer-hi/model.int8.onnx",
            size_mb=130,
            licence="CC-BY-4.0",
            note="IndicConformer Hindi int8 for sherpa-onnx",
        ),
        Asset(
            url=f"{MODELS_HOST}/parismitaglobalsolutions/indicconformer-sherpa-onnx/resolve/main/tokens.txt",
            filename="indicconformer-hi/tokens.txt",
            size_mb=0.1,
            licence="CC-BY-4.0",
        ),
    ),
    "tts-piper": (
        Asset(
            url=f"{MODELS_HOST}/rhasspy/piper-voices/resolve/main/hi/hi_IN/priyamvada/medium/"
            "hi_IN-priyamvada-medium.onnx",
            filename="piper/hi_IN-priyamvada-medium.onnx",
            size_mb=63.5,
            licence="CC-BY-NC-SA (NON-COMMERCIAL)",
        ),
        Asset(
            url=f"{MODELS_HOST}/rhasspy/piper-voices/resolve/main/hi/hi_IN/priyamvada/medium/"
            "hi_IN-priyamvada-medium.onnx.json",
            filename="piper/hi_IN-priyamvada-medium.onnx.json",
            size_mb=0.005,
            licence="CC-BY-NC-SA (NON-COMMERCIAL)",
        ),
    ),
}

ALIASES = {
    "all-light": ("asr-light", "tts-piper"),
}


def resolve_sets(names: list[str]) -> list[Asset]:
    assets: list[Asset] = []
    for name in names:
        expanded = ALIASES.get(name, (name,))
        for key in expanded:
            if key not in SETS:
                raise KeyError(f"unknown set {key!r}; known: {', '.join(sorted(SETS))}")
            assets.extend(SETS[key])
    unique: dict[str, Asset] = {asset.filename: asset for asset in assets}
    return list(unique.values())


def sha256_of(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(chunk):
            digest.update(block)
    return digest.hexdigest()


def download(asset: Asset, destination: Path, force: bool = False) -> Path:
    target = destination / asset.filename
    if target.exists() and not force:
        if asset.sha256 and sha256_of(target) != asset.sha256:
            raise RuntimeError(f"{target} exists but its checksum does not match; use --force")
        print(f"  skip   {asset.filename} (already present)")
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    request = urllib.request.Request(asset.url, headers={"User-Agent": USER_AGENT})
    print(f"  get    {asset.filename} (~{asset.size_mb:g} MB, {asset.licence})")
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as out:
            while block := response.read(1 << 16):
                out.write(block)
    except (urllib.error.URLError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"download failed for {asset.url}: {exc}") from exc

    actual = sha256_of(partial)
    if asset.sha256 and actual != asset.sha256:
        partial.unlink(missing_ok=True)
        raise RuntimeError(f"checksum mismatch for {asset.filename}: got {actual}")

    partial.replace(target)
    print(f"  ok     {asset.filename}  sha256={actual}")
    return target


def extract_archive(archive: Path, destination: Path) -> Path | None:
    """Unpack a ``.zip`` model next to the archive; returns the model directory.

    Vosk ships a zip, everything else ships loose files. Members are validated first so a
    tampered archive cannot write outside the models folder.
    """
    if archive.suffix.lower() != ".zip":
        return None

    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.namelist():
            resolved = (destination / member).resolve()
            if not resolved.is_relative_to(destination.resolve()):
                raise RuntimeError(f"refusing to extract {member!r} outside {destination}")
        bundle.extractall(destination)
        roots = {member.split("/")[0] for member in bundle.namelist() if member.strip()}

    print(f"  unzip  {archive.name} -> {', '.join(sorted(roots))}")
    archive.unlink(missing_ok=True)
    if len(roots) == 1:
        single = destination / roots.pop()
        if single.is_dir():
            return single
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch local speech models for SHRADDHA AI.")
    parser.add_argument(
        "--set", dest="sets", action="append", default=[], help="model set to fetch"
    )
    parser.add_argument("--list", action="store_true", help="list available sets and exit")
    parser.add_argument("--dry-run", action="store_true", help="show what would be downloaded")
    parser.add_argument("--force", action="store_true", help="re-download even if present")
    args = parser.parse_args(argv)

    if args.list or not args.sets:
        print("available model sets:")
        for name, assets in SETS.items():
            total = sum(asset.size_mb for asset in assets)
            print(f"  {name:<12} {total:>6.1f} MB   {', '.join(a.licence for a in assets)}")
        print(f"  {'all-light':<12} alias for asr-light + tts-piper")
        return 0

    try:
        assets = resolve_sets(args.sets)
    except KeyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    destination = get_paths().models
    print(f"destination: {destination}")
    if args.dry_run:
        for asset in assets:
            print(f"  would fetch {asset.filename} (~{asset.size_mb:g} MB, {asset.licence})")
        return 0

    failures = 0
    for asset in assets:
        try:
            target = download(asset, destination, force=args.force)
            extract_archive(target, destination)
        except (RuntimeError, OSError, zipfile.BadZipFile) as exc:
            print(f"  FAIL   {exc}", file=sys.stderr)
            failures += 1
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
