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

import requests


__version__ = "0.1"
__title__ = "Rom Media Scraper"

log: logging.Logger = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    args = argparse.Namespace(
        loglevel=logging.DEBUG,
        config=pathlib.Path(__file__).with_name("config.toml"),
    )
    args.debug = (args.loglevel == logging.DEBUG)
    logging.basicConfig(
        level=args.loglevel,
        format="[%(asctime)s %(levelname)-6.6s] %(module)-4s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    return args


def read_config(path:os.PathLike) -> dict:
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return data


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
    ):
        self.dev_id = dev_id
        self.dev_password = dev_password
        self.software = software
        self.username = username
        self.password = password

    def call(self, endpoint, *, json=True, **params):
        url = "/".join((self.API_URL, endpoint))
        data = {
            "devid": self.dev_id,
            "devpassword": self.dev_password,
            "softname": self.software,
            "ssid": self.username,
            "sspassword": self.password,
            "output": "JSON" if json else "XML",
        }
        data.update(params)
        return requests.get(url, params=data)

    def game_info(self, system_id:int, name:str, crc:str):
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
    api = ScreenScraper(**config["ScreenScraper"])
    res = api.game_info(1, "Sonic The Hedgehog 2 (World).zip", "50ABC90A")
    print(res.url)
    print(res.text)


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
