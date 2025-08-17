#!/usr/bin/env python3
# This file is part of Rom Media Scraper, see <https://github.com/MestreLion/rom-media-scraper>
# Copyright (C) 2025 Rodrigo Silva (MestreLion) <linux@rodrigosilva.com>
# License: GPLv3 or later, at your choice. See <http://www.gnu.org/licenses/gpl>
"""
CLI and Library to fetch ROM info and media from online databases
"""
# Documentation:
# https://www.screenscraper.fr/webapi2.php
#
# Useful references:
# https://github.com/Julioevm/tiny-scraper
# https://github.com/muldjord/skyscraper/blob/master/src/screenscraper.cpp
# https://gitlab.com/es-de/emulationstation-de/-/blob/master/es-app/src/scrapers/ScreenScraper.cpp
# https://github.com/batocera-linux/batocera-emulationstation/blob/master/es-app/src/scrapers/ScreenScraper.cpp
# https://gitlab.com/recalbox/recalbox/-/blob/master/projects/frontend/es-app/src/scraping/scrapers/screenscraper
#
# Unuseful references:
# https://github.com/zayamatias/sscraper
# https://github.com/zayamatias/retroscraper

# Nomenclature conventions:
# - ROM: file or folder containing the original data of a game, regardless of digital format or game physical media type
# - System (Platform): A video game system, console, computer, handheld: Nintendo 64, MSX1, Game Boy, Arcade
# - Provider (Source): Online database of metadata and media for Games, ROMs, Systems: ScreenScraper, TheGamesDB
# - Frontend: Device, OS or Software to play emulated: ES-DS, Batocera, Recalbox, RetroPie, Anbernic, Garlic
# - Origin: Origin of a given data, can be either a Frontend or a Provider

from __future__ import annotations

import argparse
import itertools
import json
import logging
import os
import pathlib
import sys
import tomllib  # in stdlib since Python 3.11
import typing as t
import zlib

import requests
import xxhash

if t.TYPE_CHECKING:
    import collections.abc as abc


__version__ = "0.1"
__title__ = "Rom Media Scraper"

TIMEOUT = 60
LAYOUT = "batocera"

CONFIG_PATH = pathlib.Path(__file__).with_name("config.toml")  # TODO: use platformdirs
CACHE_DIR = pathlib.Path(__file__).with_name("cache")  # TODO: use platformdirs

type StrPath = str | os.PathLike[str]
type Json = str | int | float | bool | None | "JsonDict" | "JsonList"
type JsonDict = dict[str, Json]
type JsonList = list[Json]
type JsonDictSet = dict[str, Json | set[str] | set[int]]  # set intentionally only as root value


class ApiData(t.TypedDict):
    response: JsonDict


class SystemData(t.TypedDict):
    id: int
    noms: dict[str, str]  # {nom_eu, nom_us, nom_jp, ...}
    extensions: t.NotRequired[str]
    compagnie: t.NotRequired[str]
    medias: list[dict[str, str]]


class GameInfoSystemData(t.TypedDict):
    id: str  # numeric string
    text: str  # system name


class GameInfoRomData(t.TypedDict):
    id: str  # yeah, numeric string, bummer
    romfilename: str
    romregions: str
    # regions: dict[str, list[str]]  # {regions_id: ["1", ...], regions_shortname: ["eu", ...], regions_*: ...}


class GameInfoData(t.TypedDict):
    id: str  # numeric string
    systeme: GameInfoSystemData
    noms: list[dict[str, str]]  # [{region: "us", text: "..."}, ...]
    medias: list[dict[str, str]]
    rom: GameInfoRomData


log: logging.Logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    epilog = """
    Copyright (C) 2025 Rodrigo Silva (MestreLion) <linux@rodrigosilva.com>
    License: GPLv3 or later, at your choice. See <https://www.gnu.org/licenses/gpl>
    """.strip()
    parser = argparse.ArgumentParser(description=__doc__, epilog=epilog.strip())
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "-q",
        "--quiet",
        dest="loglevel",
        const=logging.WARNING,
        default=logging.INFO,
        action="store_const",
        help="Suppress informative messages.",
    )
    group.add_argument(
        "-v",
        "--verbose",
        dest="loglevel",
        const=logging.DEBUG,
        action="store_const",
        help="Verbose mode, output extra info.",
    )
    parser.add_argument(
        "-C",
        "--config",
        default=CONFIG_PATH,
        type=pathlib.Path,
        help="Configuration file path [Default: %(default)s]"
    )
    parser.add_argument(
        "-c",
        "--cache-dir",
        default=CACHE_DIR,
        type=pathlib.Path,
        help="Cache directory [Default: %(default)s]"
    )
#    group = parser.add_mutually_exclusive_group()
#    group.add_argument("--list-media-types", default=False, action="store_true", help="List supported media types")
    parser.add_argument(nargs="*", dest="paths", metavar="ROM_PATH", help="ROM files or folders")

    args = parser.parse_args(argv)
    args.debug = (args.loglevel == logging.DEBUG)
    logging.basicConfig(
        level=args.loglevel,
        format="[%(asctime)s %(levelname)-5s] %(module)-4s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return args


def read_config(path: os.PathLike) -> dict:
    return tomllib.loads(pathlib.Path(path).read_text())


def pretty(obj: object, indent=2, sort_keys=False) -> str:
    return json.dumps(obj, separators=(',', ':'), default=str, sort_keys=sort_keys, indent=indent)


def hashobj(obj: object) -> str:
    return xxhash.xxh3_128_hexdigest(pretty(obj, indent=1, sort_keys=True))


def unique[T:"abc.Hashable"](iterable: abc.Iterable[T], discard_falsy: bool = True) -> abc.Iterator[T]:
    """Yield unique elements, preserving order. Elements must be hashable"""
    # AKA "Ordered Set" or "De-Duplicated List"
    # Alternative: unique_everseen() from itertools recipes or more-itertools package
    # (faster and allow un-hashable (i.e. mutable) elements)
    # https://stackoverflow.com/a/17016257/624066
    yield from dict.fromkeys(filter(None, iterable) if discard_falsy else iterable)


def iter_files(paths: abc.Iterable[os.PathLike], yield_dirs=False) -> abc.Iterator[pathlib.Path]:
    for item in paths:
        path = pathlib.Path(item)
        if path.is_file():
            if yield_dirs:
                yield path.parent
            yield path
        elif path.is_dir():
            # TODO: handle symlink infinite loops
            for dirpath, _, filenames in path.walk(follow_symlinks=True):
                if yield_dirs and filenames:
                    yield dirpath
                for filename in sorted(filenames):
                    yield dirpath / filename


def csv2iter[T](
    text: str | None,
    sep: str = ",",
    itemtype: abc.Callable[[str], T] = str  # type: ignore[assignment] # https://github.com/python/mypy/issues/3737
) -> abc.Iterator[T]:
    """Split text by separator, yielding each stripped (and possibly converted) element"""
    if text is None or not (text := text.strip()):
        return iter(())
    return (itemtype(_.strip()) for _ in text.split(sep))


class ScraperError(Exception):
    """Base class for custom exceptions with a few extras on top of Exception.

    - %-formatting for args, similar to logging.log()
    - `errno` numeric attribute, similar to OSError
    - `err` attribute for the original exception, useful when re-raising exceptions

    All modules in this package raise this (or a subclass) for all explicitly
    raised, business-logic, expected or handled exceptions.
    """

    def __init__(
        self,
        msg: object = "",
        *args: object,
        errno: int = 0,
        err: Exception | None = None
    ):
        super().__init__((str(msg) % args) if args else msg)
        self.errno: int = errno
        self.err: Exception | None = err


class ScraperResponseError(ScraperError):
    def __init__(self, msg: object = "", *args: object, err: requests.RequestException):
        assert err.response is not None
        self.res: requests.Response = err.response
        super().__init__(msg, *args, errno=self.res.status_code, err=err)


class CachedResource:
    TEXT_TYPES = {"json", "xml", "txt", "html"}

    def __init__(
        self,
        origin: str,
        name: str,
        params: dict | None = None,
        filetype: str = "",
        rootdir: os.PathLike | None = None
    ):
        self.stem = pathlib.Path(hashobj((origin, name, params)))
        self.type = filetype.lstrip(".").lower()
        self.root = None if rootdir is None else pathlib.Path(rootdir)

    @property
    def name(self) -> pathlib.Path:
        return self.stem.with_suffix(f".{self.type}") if self.type else self.stem

    @property
    def path(self) -> pathlib.Path | None:
        if self.root is None:
            return None
        return self.root / self.name

    @property
    def is_text(self) -> bool:
        return self.type in self.TEXT_TYPES

    @property
    def is_json(self) -> bool:
        return self.type == "json"

    def read(self) -> Json | str | bytes | None:
        if (path := self.path) is None:
            return None
        try:
            data = path.read_text() if self.is_text else path.read_bytes()
        except FileNotFoundError:
            return None
        log.debug("Data retrieved from cache: %s", path)
        return json.loads(data) if self.is_json else data

    def write(self, data: str | bytes) -> None:
        if (path := self.path) is None:
            return
        log.debug("Write data to cache: %s", path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.is_json:
            path.write_text(pretty(t.cast(str, data)))
        elif self.is_text:
            path.write_text(t.cast(str, data))
        else:
            path.write_bytes(t.cast(bytes, data))


class Rom:
    CHUNK_SIZE = 64 * 2**10

    def __init__(self, path: os.PathLike):
        self.path = pathlib.Path(path)
        self._crc32 = ""

    @property
    def name(self) -> str:
        return self.path.stem

    @property
    def size(self) -> int:
        return self.path.stat().st_size

    @property
    def crc32(self) -> str:
        if not self._crc32:
            crc = 0
            with self.path.open(mode="rb") as fd:
                while chunk := fd.read(self.CHUNK_SIZE):
                    crc = zlib.crc32(chunk, crc)
            self._crc32 = f"{crc & 0xFFFFFFFF:08X}"
        return self._crc32

    def __repr__(self) -> str:
        return f"<ROM {str(self.path)!r}, {self.size} bytes, CRC32={self.crc32!r}>"

    def __str__(self) -> str:
        return self.name


class System:
    """Video game system, console, computer, handheld. Also known as Platform"""
    # For now, exclusive to ScreenScraper

    def __init__(self, data: SystemData):
        self.data: SystemData = data
        self.id: int = int(data["id"])
        self.name: str = data["noms"]["nom_eu"]  # the only "nom_*" surely present in all systems
        # FIXME: handle "pc(a|b),dos(c|d)" cases for extensions
        self.suffixes: set[str] = set(f".{_}" for _ in csv2iter(data.get("extensions", "")))
        self.manufacturer: str = data.get("compagnie", "")
        self.paths: set[str] = set(
            _.lower() for _ in
            set(itertools.chain.from_iterable(csv2iter(_) for _ in data["noms"].values()))
        )
        self.names: tuple[str, ...] = tuple(unique(data["noms"].get(f"nom_{_}", "") for _ in ("eu", "us", "jp")))

    def __str__(self):
        if self.manufacturer:
            return f"{self.manufacturer} {self.name.removeprefix(self.manufacturer).strip()}"
        return self.name

    def __repr__(self):
        prefix = f"<{self.__class__.__name__} {self.id:3d}:"
        names = " / ".join(self.names)
        if self.manufacturer:
            names = names.removeprefix(self.manufacturer).strip()
            return f"{prefix} {self.manufacturer} {names}>"
        else:
            return f"{prefix} {names}>"


class ScreenScraper:
    """ScreenScraper API (https://screenscraper.fr)"""
    API_URL = "https://api.screenscraper.fr/api2"
    API_DEVELOPER = "xxx"
    API_PASSWORD = "yyy"
    API_SOFTWARE = f"{__title__} v{__version__}"
    TIMEOUT: int | None = TIMEOUT
    ISO_TYPES: set[str] = {".iso", ".chd"}
    MEDIA_TYPES: set[str] = {  # TODO: use a (named)2-tuple, namespace or class to hold description (and name)
        "ss",               # In-game screenshot of typical gameplay
        "sstitle",          # In-game screenshot of the game title screen
        "wheel",            # Game title logo, commonly featured in title screen or game box
        "box-2D",           # Front of the game (physical) box
        "box-2D-side",      # Side (spine) of the box
        "box-2D-back",      # Back of the box
        "box-3D",           # Game box in 3D perspective, generated from box front and spine
        "support-2D",       # Physical media (Cartridge/CD), likely generated from sticker and its system "blank" media
        "support-texture",  # Game "sticker" featured in its physical media
        "mixrbv1",          # Composite of gameplay screenshot, 3D box and logo (Mix Recalbox V1)
        "mixrbv2",          # Composite of gameplay screenshot, 3D box, logo and physical media (Mix Recalbox V2)
        "manuel",           # Game manual
    }
    type Systems = dict[int, System]

    def __init__(
        self,
        username: str,
        password: str,
        dev_id: str = API_DEVELOPER,
        dev_password: str = API_PASSWORD,
        software: str = API_SOFTWARE,
        cachedir: os.PathLike | None = None,
    ):
        self.dev_id = dev_id
        self.dev_password = dev_password
        self.software = software
        self.username = username
        self.password = password
        self.cachedir: pathlib.Path | None = None if cachedir is None else pathlib.Path(cachedir)
        self._systems: ScreenScraper.Systems = {}
        # self._systems: dict[str, System] = {}

    @property
    def source(self) -> str:
        return self.__class__.__name__

    @property
    def systems(self) -> Systems:
        if self._systems:
            return self._systems
        for system_data in self.api_systems_list():
            system = System(system_data)
            # FIXME: handle "x(a|b),y(c|d)" cases
            self._systems[system.id] = system
            log.debug("%r: %s, %s", system, system.paths, system.suffixes)
        return self._systems

    def __str__(self):
        return self.source

    def get_cached_resource(self, endpoint: str, params: dict, filetype=""):
        return CachedResource(
            origin=self.source,
            name=endpoint,
            params=params,
            filetype=filetype,
            rootdir=self.cachedir,
        )

    def api_call(self, endpoint: str, **params) -> JsonDict:
        # Try cached data
        cache = self.get_cached_resource(endpoint, params, "json")
        if (cache_data := t.cast(ApiData | None, cache.read())) is not None:
            return cache_data["response"]
        # Fetch data
        url = "/".join((self.API_URL, endpoint))
        data = {
            "devid": self.dev_id,
            "devpassword": self.dev_password,
            "softname": self.software,
            "ssid": self.username,
            "sspassword": self.password,
            "output": "json",  # default: "xml"
        }
        data.update(params)
        res: requests.Response
        try:
            res = requests.get(url, params=data, timeout=self.TIMEOUT)
        except requests.exceptions.ReadTimeout as e:
            raise ScraperError("%s", e, err=e)
        try:
            res.raise_for_status()
            out = res.json()
        except requests.JSONDecodeError as e:
            raise ScraperError("Malformed JSON: %s from url: %s\n%r", e, res.url, res.text, err=e)
        except requests.RequestException as e:
            # requests error message already contains URL
            if res.status_code in {403}:  # Forbidden
                msg = res.text.strip()
                if "identifiants développeur" in msg:  # "Erreur de login : Vérifier vos identifiants développeur !  "
                    raise ScraperResponseError("%s\t%s (Invalid developer credentials)", e, msg, err=e)
            raise ScraperResponseError("%s\n%s\n%s", e, pretty(dict(res.headers)), res.text, err=e)
        # Write to cache
        cache.write(out)
        return out["response"]

    # Low-level methods --------------------------------------------------

    def api_systems_list(self) -> list[SystemData]:
        """List of systems with their info and media"""
        return t.cast(list[SystemData], self.api_call("systemesListe.php")["systemes"])

    def api_medias_game_list(self) -> list[JsonDict]:
        """List of media for game (media types for games)"""
        return t.cast(list[JsonDict], self.api_call("mediasJeuListe.php")["medias"])

    def api_game_info(self, system_id: int, rom_name: str, rom_size: int, crc: str, rom_type="rom") -> GameInfoData:
        params = {
            "systemeid": system_id,
            "crc": crc,
            "romnom": rom_name,
            "romtype": rom_type,
            "romtaille": rom_size,
        }
        return t.cast(GameInfoData, self.api_call("jeuInfos.php", **params)["jeu"])

    def api_game_search(self, system_id: int, search: str) -> list[JsonDict]:
        """Search for a game by name, return limited to 30 games ranked by probability"""
        params = {
            "systemeid": system_id,
            "recherche": search,
        }
        return t.cast(list[JsonDict], self.api_call("jeuRecherche.php", **params)["jeux"])  # GameSearchData

    # High-level methods --------------------------------------------------

    def find_system_by_dir(self, path: os.PathLike) -> System | None:
        # TODO: Make it recursive on parents, so it find systems for roms in subdirs
        if (path := pathlib.Path(path)).is_file():
            path = path.parent
        dirname: str = path.name
        for system in self.systems.values():
            if dirname.lower() in system.paths:
                return system
        return None
        # raise ScraperError("System not found in %s database for directory: %s", self.source, dirname)

    def find_game(self, system: System, rom: Rom) -> GameInfoData:
        try:
            info = self.api_game_info(system.id, rom.name, rom.size, rom.crc32)
        except ScraperResponseError as e:
            if e.errno in {404}:  # Not Found
                msg = e.res.text.strip()
                if "non trouvée" in msg:  # "Erreur : Rom/Iso/Dossier non trouvée !  "
                    raise ScraperError(
                        "%r for %r not found in %s database.",
                        rom, system, self.source, err=e.err
                    )
            raise
        return info

    def download_file(self, url: str, save_path: os.PathLike):
        # Try cached data
        path = pathlib.Path(save_path)
        cache = self.get_cached_resource("download", {"url": url}, path.suffix)
        log.info("Download file from %s to %s", url, cache.path)
        # path.parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _game_name(game: GameInfoData) -> str:
        for region in unique(itertools.chain(game["rom"]["romregions"].split(","), ("wor", "ss", "eu"))):
            for name in (_["text"] for _ in game["noms"] if _["region"] == region):
                return name
            log.warning("Game from ROM %r missing name in region %r.", game["rom"]["romfilename"], region)
        raise ScraperError("Unknown game region %r", game["rom"]["romregions"])

    def download_rom_media(self, system: System, rom: Rom, save_path: os.PathLike, media_type="mixrbv2") -> bool:
        # Anbernic: 282 x 216 mixrbv2
        # https://neoclone.screenscraper.fr/api2/mediaJeu.php?systemeid=4&jeuid=2138&media=mixrbv2(us)
        # Web, non-API: (will keep original aspect ratio)
        # https://www.screenscraper.fr/image.php?plateformid=4&gameid=2138&media=mixrbv2&hd=0&region=us&num=&version=&maxwidth=282&maxheight=216
        # https://www.screenscraper.fr/image.php?plateformid=4&gameid=2138&media=mixrbv2&hd=0&region=us&num=&version=&maxwidth=282&maxheight=216
        # https://www.screenscraper.fr/image.php?plateformid=4&gameid=2138&media=mixrbv2&region=us&maxwidth=320&maxheight=240
        # tiny-scraper: 320, 240
        game = self.find_game(system, rom)
        assert system.id == int(game["systeme"]["id"])
        rom_regions = game["rom"]["romregions"].split(",")
        game_name = self._game_name(game)
        # "mediaJeu.php"
        if not game["medias"]:
            log.warning("No media for %r game %r", system.name, game_name)
            return False
        for media in game["medias"]:
            if True:
                return True
            if media["type"] == media_type and media["region"] in rom_regions:
                log.info("%r", rom.path.with_suffix(f".{media['format']}").name)
                path = pathlib.Path(save_path) / rom.path.with_suffix(f".{media['format']}").name
                self.download_file(media["url"], path)
                return True
        else:
            log.warning("No %r %s media for %s game %s", media_type, rom_regions, system.name, game_name)
            return False

    def download_media(self, paths: abc.Iterable[os.PathLike], media_type="ss", save_path="."):
        num_media = num_rom = 0
        system: System | None = None
        for path in iter_files(paths, yield_dirs=True):
            if path.is_dir():
                log.info("NEW DIR! %s", path)
                if (system := self.find_system_by_dir(path)) is None:
                    log.error("System not found in %s database for directory: %s", self.source, path)
                continue
            if system is None:
                continue
            if path.suffix not in system.suffixes:
                log.warning("Ignoring non-ROM file for %r: %s", system, path)
                continue
            num_rom += 1
            try:
                num_media += 1 if self.download_rom_media(system, Rom(path), pathlib.Path(save_path), media_type) else 0
            except ScraperError as e:
                log.error(e)
                continue
        log.info("%d / %d", num_media, num_rom)

    def systems_statistics(self):
        # 238 systems in ScreenScraper database
        #   0 missing Europe name
        # 227 missing USA name
        # 229 missing Japan name
        #  71 missing Recalbox name
        #  96 missing Hyperspin name
        #  84 missing Retropie name
        #  49 missing Launchbox name
        #  11 missing Extensions
        # Names: {'eu', 'recalbox', 'retropie', 'jp', 'us', 'launchbox', 'hyperspin', 'noms_commun'}
        systems = self.systems.values()
        stats = (
            (lambda _: _["noms"].get("nom_eu"), "Europe name"),
            (lambda _: _["noms"].get("nom_us"), "USA name"),
            (lambda _: _["noms"].get("nom_jp"), "Japan name"),
            (lambda _: _["noms"].get("nom_recalbox"), "Recalbox name"),
            (lambda _: _["noms"].get("nom_hyperspin"), "Hyperspin name"),
            (lambda _: _["noms"].get("nom_retropie"), "Retropie name"),
            (lambda _: _["noms"].get("nom_launchbox"), "Launchbox name"),
            (lambda _: _["suffixes"], "Extensions"),
        )
        log.info("%3d systems in %s database", len(systems), self.source)
        for criteria, label in stats:
            i = 0
            for system in systems:
                if not criteria(system):
                    i += 1
                    log.debug("Missing %s: %r", label, system)
            log.info("%3d missing %s", i, label)
        noms = itertools.chain.from_iterable(_.data["noms"].keys() for _ in systems)
        log.info("Names: %s", set(_.removeprefix("nom_") for _ in noms))


def cli(argv: list[str] | None = None) -> None:
    """Command-line argument handling and logging setup"""
    args = parse_args(argv)
    config = read_config(args.config)
    api = ScreenScraper(**config["ScreenScraper"], cachedir=args.cache_dir)
    # api.systems_statistics()
    if args.paths:
        api.download_media(args.paths)
        return


def run(argv: list[str] | None = None) -> None:
    """CLI entry point, handling exceptions from cli() and setting exit code"""
    try:
        cli(argv)
    except ScraperError as err:
        log.error(err)
        sys.exit(1)
    except Exception as err:
        log.exception(err)
        sys.exit(3)
    except KeyboardInterrupt:
        log.info("Aborting")
        sys.exit(2)


if __name__ == "__main__":
    run()
