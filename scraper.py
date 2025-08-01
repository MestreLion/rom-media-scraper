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
        format="[%(asctime)s %(levelname)-6.6s] %(module)-4s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return args


def read_config(path:os.PathLike) -> dict:
    return tomllib.loads(pathlib.Path(path).read_text())


def pretty(obj: object, indent=2, sort_keys=False) -> str:
    return json.dumps(obj, separators=(',', ':'), default=str, sort_keys=sort_keys, indent=indent)


def hashobj(obj: object) -> str:
    return xxhash.xxh3_128_hexdigest(pretty(obj, indent=1, sort_keys=True))


class CachedResource:
    TEXT_TYPES = {"json", "xml", "txt", "html"}

    def __init__(
        self,
        provider:str,
        endpoint:str,
        params:dict,
        filetype: str = "",
        rootdir: os.PathLike | None = None
    ):
        self.stem = pathlib.Path(hashobj((provider, endpoint, params)))
        self.type = filetype.lstrip(".").lower()
        self.root = None if rootdir is None else pathlib.Path(rootdir)

    @property
    def relpath(self) -> pathlib.Path:
        return self.stem.with_suffix(f".{self.type}") if self.type else self.stem

    @property
    def path(self) -> pathlib.Path | None:
        if self.root is None:
            return None
        return self.root / self.relpath

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
    API_SOFTWARE = "zzz"

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

    def get_cached_resource(self, endpoint:str, params:dict, filetype=""):
        return CachedResource(
            provider=self.__class__.__name__,
            endpoint=endpoint,
            params=params,
            filetype=filetype,
            rootdir=self.cachedir,
        )

    def call(self, endpoint, **params) -> dict:
        # Try cached data
        cache = self.get_cached_resource(endpoint, params, "json")
        if (data := cache.read()) is not None:
            return data
        # Fetch data
        url = "/".join((self.API_URL, endpoint))
        data = {
            "devid": self.dev_id,
            "devpassword": self.dev_password,  # not required
            "softname": self.software,
            "ssid": self.username,
            "sspassword": self.password,
            "output": "json",  # default: "xml"
        }
        data.update(params)
        out = requests.get(url, params=data).json()
        # Write to cache
        cache.write(out)
        return out

    def game_info(self, system_id:int, name:str, crc:str) -> dict:
        params = {
            "systemeid": system_id,
            "crc": crc,
            "romnom": name,
            "romtype": "rom",
            "romtaille": 749652,
        }
        return self.call("jeuInfos.php", **params)


def cli(argv:list[str] | None = None) -> None:
    """Command-line argument handling and logging setup"""
    args = parse_args(argv)
    config = read_config(args.config)
    api = ScreenScraper(**config["ScreenScraper"], cachedir=args.cachedir)
    data = api.game_info(1, "Sonic The Hedgehog 2 (World).zip", "50ABC90A")
    print(pretty(data))


def run(argv: list[str] | None = None) -> None:
    """CLI entry point, handling exceptions from cli() and setting exit code"""
    try:
        cli(argv)
    except Exception as err:
        log.exception(err)
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("Aborting")
        sys.exit(2)


if __name__ == "__main__":
    run()
