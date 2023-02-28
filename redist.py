#!/usr/bin/env python3
import os
import platform
import re
import shutil
from copy import deepcopy
from dataclasses import dataclass, field
from email.message import EmailMessage
from http.client import OK
from pathlib import Path
from subprocess import DEVNULL, STDOUT, check_call, check_output
from tempfile import mkdtemp
from time import gmtime, strftime
from typing import Any, Final, Literal, NoReturn, TypeAlias, final, TypedDict, Iterable
from zipfile import ZIP_DEFLATED, ZipInfo

import click
from click_help_colors import HelpColorsGroup
from dataclasses_json import DataClassJsonMixin, undefined
from packaging.version import Version
from requests import Session
from rich import markup, traceback
from rich.console import Console
from wheel.wheelfile import WheelFile

# region ----------------------------------------------------------------------- paths
ROOT_DIR: Final = Path(__file__).parent.absolute()
CACHE_DIR: Final = ROOT_DIR / ".cache"
BUILD_DIR: Final = ROOT_DIR / "build"
DIST_DIR: Final = ROOT_DIR / "dist"
# endregion -------------------------------------------------------------------- paths
# region ----------------------------------------------------------------------- config
EXE_NAME: Final = "buf"
EXE_TEST_ARGS: Final = ("--version",)

PRJ_NAME: Final = f"{EXE_NAME}-exe"
PRJ_DESC_PATH: Final = ROOT_DIR / "README.md"

ORIGIN: Final = f"fleshgrinder/python-{PRJ_NAME}"
ORIGIN_URL: Final = f"https://github.com/{ORIGIN}"

UPSTREAM: Final = "bufbuild/buf"
UPSTREAM_URL: Final = f"https://github.com/{UPSTREAM}"

PYPI_METADATA: Final = {
    "Metadata-Version": "2.1",
    "Name": PRJ_NAME,
    "Summary": "PyPI packaged Buf CLI",
    "Description-Content-Type": "text/markdown",
    "Author": "Buf Technologies",
    "Maintainer": "Fleshgrinder",
    "Maintainer-email": "pypi@fleshgrinder.com",
    "Home-page": ORIGIN_URL,
    "License-File": "LICENSE",
    "License": "Apache-2.0",
    "Classifier": [
        "Topic :: Software Development :: Code Generators",
        "Topic :: Software Development :: Quality Assurance",
        "Topic :: Text Processing :: Markup",
        "Topic :: Utilities",
        "License :: OSI Approved :: Apache Software License",
    ],
    "Project-URL": [
        "Official Website, https://buf.build/",
        f"Source Code, {UPSTREAM_URL}",
        f"Issue Tracker, {UPSTREAM_URL}/issues",
    ],
}

WHL_NAME: Final = PRJ_NAME.replace("-", "_")
WHL_METADATA: Final = {
    "Wheel-Version": "1.0",
    "Generator": ORIGIN_URL,
    "Root-Is-Purelib": "false",
}

EXE_CACHE_DIR: Final = CACHE_DIR / EXE_NAME
EXE_BUILD_DIR: Final = BUILD_DIR / EXE_NAME
# endregion -------------------------------------------------------------------- config
# region ----------------------------------------------------------------------- utils
CI: Final = "CI" in os.environ
GHA: Final = "GITHUB_ACTIONS" in os.environ
CONSOLE: Final = Console(stderr=True)
VERBOSE = False

# region ----------------------------------------------------------------------- style
traceback.install(console=CONSOLE, show_locals=True)

Severity: TypeAlias = Literal["debug", "notice", "warning", "error"]

if GHA:

    def log(s: Severity, m: Any) -> None:
        m = m.replace("%", "%25").replace("\n", "%0A").replace("\r", "%0D")
        CONSOLE.print(f"::{s}::{m}")

else:
    _LOG_COLORS: Final = dict[Severity, str](debug="bright_black", notice="blue", warning="yellow", error="red")


    def log(s: Severity, m: Any) -> None:
        CONSOLE.print(f"[{_LOG_COLORS[s]}][bold]{s.upper()}:[/bold] {m}")


def debug(m: Any) -> None:
    if CI or VERBOSE:
        log("debug", m)


def info(m: Any) -> None:
    CONSOLE.print(m)


def notice(m: Any) -> None:
    log("notice", m)


def warning(m: Any) -> None:
    log("warning", m)


def error(m: Any) -> None:
    log("error", m)


def done(m: Any) -> NoReturn:
    info(m)
    raise SystemExit(0)


def fail(m: Any, ec: int = 1) -> NoReturn:
    error(m)
    raise SystemExit(ec)


def fpath(it: Path) -> str:
    return f"[magenta bold]{it.relative_to(ROOT_DIR)}[/magenta bold]"


# endregion -------------------------------------------------------------------- style


# noinspection SpellCheckingInspection
def map_platform(s: str) -> str | None:
    return {
        "Linux-aarch64": "manylinux_2_17_aarch64.manylinux2014_aarch64",
        "Linux-x86_64": "manylinux_2_5_x86_64.manylinux1_x86_64",
        "Darwin-arm64": "macosx_11_0_arm64",
        "Darwin-x86_64": "macosx_10_4_x86_64",
        "Windows-arm64": "win_arm64",
        "Windows-x86_64": "win_amd64",
    }.get(s.removeprefix(f"{EXE_NAME}-").removesuffix(".exe"))


def run(cmd: str, *args: str, stderr: int | None = None) -> str:
    return check_output(
        (cmd, *args),
        encoding="utf8",
        stderr=stderr,
        universal_newlines=True,
    ).rstrip()


def has_uncommitted_changes() -> bool:
    return run("git", "status", "--porcelain=v1", stderr=DEVNULL) != ""


@final
class ReproducibleWheelFile(WheelFile):
    def writestr(self, zi: ZipInfo, *args, **kwargs) -> None:
        zi.create_system = 3
        zi.date_time = (1980, 1, 1, 0, 0, 0)
        super().writestr(zi, *args, **kwargs)


def emsg(headers: dict[str, Any], payload: str | None = None) -> bytes:
    em = EmailMessage()
    for hk, hv in headers.items():
        if isinstance(hv, list):
            for e in hv:
                em[hk] = e
        else:
            em[hk] = hv
    if payload:
        em.set_payload(payload)
    return bytes(em)


def maybe_clean(clean: bool, directory: Path) -> None:  # noqa: FBT001
    if clean is True and directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True, exist_ok=True)


def gh_token() -> str:
    it = os.environ.get("GITHUB_TOKEN", os.environ.get("GH_TOKEN"))
    if it is None:
        fail(
            "Missing required [bold]GITHUB_TOKEN[/bold] or [bold]GH_TOKEN[/bold] environment variable. Make sure it "
            "set and contains a valid GitHub API token.",
        )
    return it


# endregion -------------------------------------------------------------------- utils
# region ----------------------------------------------------------------------- cli
@click.group(
    cls=HelpColorsGroup,
    context_settings={"help_option_names": ("-h", "--help")},
    help_headers_color="yellow",
    help_options_color="green",
)
@click.option("-v", "--verbose", is_flag=True)
def redist(*, verbose: bool) -> None:
    global VERBOSE  # noqa: PLW0603
    VERBOSE = verbose


@redist.command()
@click.option("-c", "--clean", is_flag=True)
@click.argument("tag", default="latest")
def download(tag: str, *, clean: bool) -> None:
    maybe_clean(clean, EXE_CACHE_DIR)

    with CONSOLE.status(f"Fetching {UPSTREAM} [bold]{tag}[/bold]...") as status, Session() as session:
        session.headers["Accept"] = "application/vnd.github+json"
        session.headers["Authorization"] = f"Bearer {gh_token()}"
        session.headers["X-GitHub-Api-Version"] = "2022-11-28"

        def download_file(dst: Path, url: str) -> None:
            if dst.exists():
                debug(f"Skipping download as it is already cached: {fpath(dst)}")
                return

            status.update(f"Downloading {fpath(dst)}")
            r = session.get(url, stream=True)
            r.raise_for_status()
            with dst.open("wb") as fp:
                for chunk in r.iter_content(chunk_size=8192):
                    fp.write(chunk)
            info(f"Downloaded {fpath(dst)}")

        if tag != "latest":
            tag = f"tags/{tag}"
        response = session.get(f"https://api.github.com/repos/{UPSTREAM}/releases/{tag}")
        response.raise_for_status()
        release = response.json()
        if tag == "latest":
            tag = release["tag_name"]
            status.update(f"Fetching {UPSTREAM} [bold]{tag}[/bold]...")
        exe_dir = EXE_CACHE_DIR / tag
        exe_dir.mkdir(parents=True, exist_ok=True)

        download_file(exe_dir / "LICENSE", f"https://raw.githubusercontent.com/{UPSTREAM}/{tag}/LICENSE")

        asset_filter = re.compile(r"\Abuf-[^.]+(?:\.exe)?\Z")
        for asset in release["assets"]:
            exe_name = asset["name"]
            if asset_filter.match(exe_name):
                download_file(exe_dir / exe_name, asset["browser_download_url"])
            else:
                debug(
                    f"Ignoring asset {exe_name!r} because it does not match the asset filter /{asset_filter.pattern}/"
                )


@redist.command()
@click.option("-c", "--clean", is_flag=True)
@click.option("-t", "--tag", "tag_glob", default="*", metavar="GLOB")
def build(*, clean: bool, tag_glob: str) -> None:
    maybe_clean(clean, EXE_BUILD_DIR)

    for src in EXE_CACHE_DIR.glob(tag_glob):
        if not src.is_dir():
            debug(f"Ignoring non-directory: {fpath(src)}")
            continue

        dst = EXE_BUILD_DIR / src.name
        try:
            dst.mkdir(parents=True)
        except FileExistsError:
            debug(f"ignoring existing: {fpath(dst)}")
            continue

        shutil.copyfile(src / "LICENSE", dst / "LICENSE")
        for exe_src in src.glob(f"{EXE_NAME}*"):
            if not exe_src.is_file():
                debug(f"Ignoring non-file: {fpath(exe_src)}")
                continue

            exe_platform = map_platform(exe_src.name)
            if exe_platform is None:
                warning(f"Unknown platform [bold]{markup.escape(exe_src.name)}[/bold]")
                continue
            exe_platform = f"py2.py3-none-{exe_platform}"
            exe_dst = dst / exe_platform
            shutil.copyfile(exe_src, exe_dst)
            info(f"Built {fpath(exe_dst)}")


@redist.command()
@click.option("-c", "--clean", is_flag=True)
@click.option("-d", "--dev", is_flag=True)
@click.option("-t", "--tag", default="*")
def assemble(*, clean: bool, dev: bool, tag: str) -> None:
    maybe_clean(clean, DIST_DIR)

    if dev is True:
        dt = strftime("%Y%m%d%H%M%S", gmtime(int(run("git", "log", "-1", "--format=%ct"))))
        version_suffix = f".dev{dt}"
    else:
        version_suffix = ""

    description = PRJ_DESC_PATH.read_text()
    pypi_metadata = deepcopy(PYPI_METADATA)
    whl_metadata = deepcopy(WHL_METADATA)

    for tag_dir in EXE_BUILD_DIR.glob(tag):
        if not tag_dir.is_dir():
            debug(f"ignoring non-dir: {tag_dir.relative_to(ROOT_DIR)}")
            continue

        tag = tag_dir.name
        version = str(Version(f"{tag.removeprefix('v')}{version_suffix}"))
        whl_dir = DIST_DIR / version
        whl_dir.mkdir(parents=True, exist_ok=True)
        whl_name = f"{WHL_NAME}-{version}"
        pypi_metadata["Version"] = version
        pypi_metadata["Download-URL"] = f"{UPSTREAM_URL}/releases/tag/{tag}"
        license_ = (tag_dir / "LICENSE").read_bytes()
        for exe_file in tag_dir.glob("py2.py3-none-*"):
            if not exe_file.is_file():
                debug(f"ignoring non-file: {exe_file.relative_to(ROOT_DIR)}")
                continue

            pypi_platform = exe_file.name
            whl_file = whl_dir / f"{whl_name}-{pypi_platform}.whl"
            if whl_file.exists():
                debug(f"skipping existing wheel: {whl_file.relative_to(ROOT_DIR)}")
                continue

            whl_metadata["Tag"] = pypi_platform
            exe_name = f"{EXE_NAME}.exe" if pypi_platform.startswith("py2.py3-none-win") else EXE_NAME
            dist_info = f"{whl_name}.dist-info"
            with ReproducibleWheelFile(whl_file, "w") as it:
                for _k, v, p in (
                    (f"{whl_name}.data/scripts/{exe_name}", exe_file.read_bytes(), 0o755),
                    (f"{dist_info}/LICENSE", license_, 0o644),
                    (f"{dist_info}/METADATA", emsg(pypi_metadata, description), 0o644),
                    (f"{dist_info}/WHEEL", emsg(whl_metadata), 0o644),
                ):
                    k = ZipInfo(_k)
                    k.compress_type = ZIP_DEFLATED
                    k.external_attr = (p + 0o100000) << 16
                    k.file_size = len(v)
                    it.writestr(k, v)
            info(f"Assembled [magenta bold]{whl_file.relative_to(ROOT_DIR)}")


@redist.command()
@click.option("-v", "--version", "version_glob", default="*", metavar="GLOB")
def verify(*, version_glob: str) -> None:
    from twine.commands.check import check

    errors = False
    for version_dir in DIST_DIR.glob(version_glob):
        debug(fpath(version_dir))
        if version_dir.is_dir():
            os.chdir(version_dir)
            dists = [str(it.relative_to(version_dir)) for it in version_dir.glob("*.whl") if it.is_file()]
            errors |= check(dists, strict=True)
        else:
            debug(f"Ignoring non-directory: {fpath(version_dir)}")
    raise SystemExit(int(errors))


@redist.command()
@click.option("-v", "--version", default="*")
@click.argument("args", nargs=-1)
def test(args: tuple[str, ...], *, version: str) -> None:
    if len(args) == 0:
        args = EXE_TEST_ARGS

    system = {"Darwin": "macos", "Linux": "linux", "Windows": "win"}[platform.system()]
    windows = system == "win"
    machine = platform.machine()
    machine = f"_{machine.lower()}" if windows else f"*{machine}"
    glob = f"{WHL_NAME}-{version}-*-{system}{machine}.whl"
    wheel = next(map(str, DIST_DIR.glob(glob)), None)
    if wheel is None:
        fail(f"Could not find any wheel matching [bold]{glob!r}[/bold] in {DIST_DIR.relative_to(ROOT_DIR)}")

    tmp = None
    pip = ["pip", "--disable-pip-version-check", "--no-input"]
    if not CI:
        tmp = mkdtemp(dir=BUILD_DIR)
        os.chdir(tmp)
        pip.append("--require-virtualenv")
    try:
        check_call([*pip, "install", "--force-reinstall", wheel])

        results = (
            run("where" if windows else "which", EXE_NAME, stderr=STDOUT),
            run(EXE_NAME, *args, stderr=STDOUT),
        )
        notice("\n".join(results))

        if not CI:
            check_call([*pip, "uninstall", "--yes", wheel])
    finally:
        if tmp is not None:
            shutil.rmtree(tmp, ignore_errors=True)


@redist.command()
@click.option("-f", "--force", is_flag=True)
@click.option("-v", "--version", default="*", metavar="GLOB")
@click.argument("repo", default="testpypi")
def publish(repo: str, *, force: bool, version: str) -> None:
    """Publish all wheels from the distribution directory to the given repo."""
    if force is False and has_uncommitted_changes() is True:
        fail("Refusing publication, you have uncommitted changes, use [bold]--force[/bold] to ignore this check.")

    from twine.commands.upload import upload
    from twine.settings import Settings

    settings = Settings(repository_name=repo)
    for version_dir in DIST_DIR.glob(version):
        if version_dir.is_dir():
            upload(settings, [str(it) for it in version_dir.glob("*.whl") if it.is_file()])


JsonArray: TypeAlias = list["Json"]
JsonObject: TypeAlias = dict[str, "Json"]
JsonPrimitive: TypeAlias = bool | float | int | str | None
Json: TypeAlias = JsonArray | JsonObject | JsonPrimitive


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Asset(DataClassJsonMixin):
    id: int
    url: str = field(hash=False)
    name: str = field(hash=False)
    content_type: str = field(hash=False)
    size: int = field(hash=False)

    def download(self) -> None:
        pass


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Release(DataClassJsonMixin):
    id: int
    url: str = field(hash=False)
    tag_name: str = field(hash=False)
    draft: bool = field(hash=False)
    prerelease: bool = field(hash=False)
    assets: list[Asset] = field(hash=False)


def href(s: Any) -> str:
    return f"[link={s}]{s}[/link]"


def file(s: Any) -> str:
    return f"[magenta]{s}[/magenta]"


SESSION: Final = Session()
SESSION.headers["Accept"] = "application/vnd.github+json"
SESSION.headers["Authorization"] = f"Bearer {gh_token()}"
SESSION.headers["X-GitHub-Api-Version"] = "2022-11-28"

STATUS: Final = CONSOLE.status("")


def fetch_releases(repo: str) -> Iterable[Release]:
    page = 1
    url = f"https://api.github.com/repos/{repo}/releases?per_page=100"
    while True:
        STATUS.update(f"Fetching {href(f'{url}&page={page}')}")
        response = SESSION.get(url)
        if response.status_code != OK:
            fail(f"Request failed {href(url)}")
        for it in Release.schema().load(response.json(), many=True, unknown="exclude"):  # type: Release
            if not it.draft and not it.prerelease:
                yield it
        if "next" not in response.links:
            break
        page += 1
        url = response.links["next"]["url"]


@redist.command()
def sync() -> None:
    origin_releases = frozenset(fetch_releases(ORIGIN))
    for it in origin_releases:
        print(it)
    upstream_releases = frozenset(fetch_releases(UPSTREAM))
    for it in upstream_releases:
        print(it)


# endregion -------------------------------------------------------------------- cli
if __name__ == "__main__":
    redist()
