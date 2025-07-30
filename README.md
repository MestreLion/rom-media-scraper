# Rom Media Scraper
Simple, standalone, platform-independent CLI and Library to fetch ROM info and media from online databases
such as [ScreenScraper][1].

Alternatives:
- [Tiny Scraper][2]: also written in Python, scraper GUI for Anbernic devices only
- [Skyscraper][3]: written in C++, a very ambitious standalone, platform-independent CLI scraper
- [ES-DE][4], [Batocera][5], [Recalbox][6] and other retro-gaming distributions:
  most in C++, scraper built-in in their Emulationstation frontend and tightly integrated with the distro.

[1]: https://screenscraper.fr
[2]: https://github.com/Julioevm/tiny-scraper
[3]: https://github.com/muldjord/skyscraper
[4]: https://es-de.org/
[5]: https://batocera.org/
[6]: https://www.recalbox.com/

---
## Installing

To install the project and dependencies, preferably in a virtual environment:

    pip3 install .

> _**Note**: Fully tested on Python 3.12, should work fine on all later python versions._

## Usage

For basic usage, just run:

    rom-media-scraper

Debugging, testing or fine-tuning?

```console
$ rom-media-scraper --help
...
```

---
## Contributing

Patches are welcome! Fork, hack, request pull!

If you find a bug or have any enhancement request, please do open a [new issue][99]

[99]: https://github.com/MestreLion/rom-media-scraper/issues

## Author

Rodrigo Silva (MestreLion) <linux@rodrigosilva.com>

## License and Copyright
```
Copyright (C) 2025 Rodrigo Silva (MestreLion) <linux@rodrigosilva.com>.
License GPLv3+: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>.
This is free software: you are free to change and redistribute it.
There is NO WARRANTY, to the extent permitted by law.
```
