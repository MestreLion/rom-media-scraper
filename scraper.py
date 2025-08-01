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

from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import sys
import tomllib
import zlib

import requests
import xxhash


__version__ = "0.1"
__title__ = "Rom Media Scraper"

TIMEOUT = 20
LAYOUT = "batocera"

log: logging.Logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    args = argparse.Namespace(
        loglevel=logging.DEBUG,
        config=pathlib.Path(__file__).with_name("config.toml"),
        path=pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "."),
        cachedir=pathlib.Path(__file__).with_name("cache")
    )
    args.debug = (args.loglevel == logging.DEBUG)
    logging.basicConfig(
        level=args.loglevel,
        format="[%(asctime)s %(levelname)-5s] %(module)-4s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return args


def read_config(path:os.PathLike) -> dict:
    return tomllib.loads(pathlib.Path(path).read_text())


def pretty(obj: object, indent=2, sort_keys=False) -> str:
    return json.dumps(obj, separators=(',', ':'), default=str, sort_keys=sort_keys, indent=indent)


def hashobj(obj: object) -> str:
    return xxhash.xxh3_128_hexdigest(pretty(obj, indent=1, sort_keys=True))


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
        err:Exception | None = None
    ):
        super().__init__((str(msg) % args) if args else msg)
        self.errno: int = errno
        self.err: Exception | None = err


class CachedResource:
    TEXT_TYPES = {"json", "xml", "txt", "html"}

    def __init__(
        self,
        origin:str,
        name:str,
        params:dict | None = None,
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

    def read(self) -> object | None:
        if (path := self.path) is None:
            return None
        try:
            data = path.read_text() if self.is_text else path.read_bytes()
        except FileNotFoundError:
            return None
        log.debug("Data retrieved from cache: %s", path)
        return json.loads(data) if self.is_json else data

    def write(self, data:object) -> None:
        if (path := self.path) is None:
            return
        log.debug("Write data to cache: %s", path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.is_json:
            path.write_text(pretty(data))
        elif self.is_text:
            path.write_text(data)
        else:
            path.write_bytes(data)


class Rom:
    CHUNK_SIZE = 64 * 2**10

    def __init__(self, path:os.PathLike):
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


class ScreenScraper:
    """ScreenScraper API (https://screenscraper.fr)"""
    API_URL = "https://api.screenscraper.fr/api2"
    API_DEVELOPER = "xxx"
    API_PASSWORD = "yyy"
    API_SOFTWARE = f"{__title__} v{__version__}"
    TIMEOUT: int | None = TIMEOUT

    def __init__(
        self,
        username:str,
        password:str,
        dev_id: str = API_DEVELOPER,
        dev_password:str = API_PASSWORD,
        software: str = API_SOFTWARE,
        cachedir: os.PathLike | None = None,
    ):
        self.dev_id = dev_id
        self.dev_password = dev_password
        self.software = software
        self.username = username
        self.password = password
        self.cachedir: pathlib.Path | None = None if cachedir is None else pathlib.Path(cachedir)

    @property
    def source(self) -> str:
        return self.__class__.__name__

    def __str__(self):
        return self.source

    def get_cached_resource(self, endpoint:str, params:dict, filetype=""):
        return CachedResource(
            origin=self.source,
            name=endpoint,
            params=params,
            filetype=filetype,
            rootdir=self.cachedir,
        )

    def api_call(self, endpoint:str, **params) -> dict:
        # Try cached data
        cache = self.get_cached_resource(endpoint, params, "json")
        if (data := cache.read()) is not None:
            return data["response"]
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
        try:
            res = requests.get(url, params=data, timeout=self.TIMEOUT)
            res.raise_for_status()
            out = res.json()
        except requests.exceptions.ReadTimeout as e:
            raise ScraperError("%s", e, err=e)
        except requests.exceptions.JSONDecodeError as e:
            raise ScraperError("Malformed JSON: %s from url: %s\n%r", e, res.url, res.text, err=e)
        except requests.exceptions.RequestException as e:
            # requests error message already contains URL
            if res.status_code in { 403 }:  # Forbidden
                msg = res.text.strip()
                if "identifiants développeur" in msg:  # "Erreur de login : Vérifier vos identifiants développeur !  "
                    raise ScraperError("%s\t%s (Invalid developer credentials)", e, msg, errno=403, err=e)
            raise ScraperError("%s\n%s\n%s", e, pretty(dict(res.headers)), res.text, errno=res.status_code, err=e)
        # Write to cache
        cache.write(out)
        return out["response"]

    def api_systems_list(self) -> list[dict]:
        return self.api_call("systemesListe.php")["systemes"]

    def api_game_info(self, system_id:int, rom_name:str, rom_size:int, crc:str, rom_type="rom") -> dict:
        params = {
            "systemeid": system_id,
            "crc": crc,
            "romnom": rom_name,
            "romtype": rom_type,
            "romtaille": rom_size,
        }
        return self.api_call("jeuInfos.php", **params)["jeu"]

    def identify_rom_system(self, rom, layout=LAYOUT) -> dict:
        return {"id": 14, "noms": {"nom_eu": "Nintendo 64"}}

    def find_game(self, rom: Rom, layout=LAYOUT) -> dict:
        system = self.identify_rom_system(rom, layout=layout)
        try:
            info = self.api_game_info(system["id"], rom.name, rom.size, rom.crc32)
        except ScraperError as e:
            if e.errno in { 404 }:  # Not Found
                msg = e.err.response.text.strip()
                pretty_system = (system["id"], system["noms"]["nom_eu"])
                if "non trouvée" in msg:  # "Erreur : Rom/Iso/Dossier non trouvée !  "
                    raise ScraperError(
                        "%r for system %r not found in %s database.",
                        rom, system["noms"]["nom_eu"], self.source, err=e.err
                    )
            raise
        print(pretty(info))

    def download_rom_media(self, rom: Rom, path: os.PathLike, media_type="ss", language="us", region="wor", layout=LAYOUT):
        game = self.find_game(rom, layout=layout)
        ...


def cli(argv:list[str] | None = None) -> None:
    """Command-line argument handling and logging setup"""
    args = parse_args(argv)
    config = read_config(args.config)
    api = ScreenScraper(**config["ScreenScraper"], cachedir=args.cachedir)

    if args.path.is_file():
        rom = Rom(args.path)
        api.download_rom_media(rom, ".")


def run(argv: list[str] | None = None) -> None:
    """CLI entry point, handling exceptions from cli() and setting exit code"""
    try:
        sys.exit(cli(argv))
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
