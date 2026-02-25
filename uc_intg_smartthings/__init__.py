#!/usr/bin/env python3
"""
SmartThings Integration for Unfolded Circle Remote Two/3.

:copyright: (c) 2026 by Meir Miyara.
:license: MPL-2.0, see LICENSE for more details.
"""

import asyncio
import json
import logging
from pathlib import Path

logging.getLogger(__name__).addHandler(logging.NullHandler())

try:
    driver_path = Path(__file__).parent.parent / "driver.json"
    with open(driver_path, "r", encoding="utf-8") as f:
        driver_info = json.load(f)
        __version__ = driver_info.get("version", "0.0.0")
except (FileNotFoundError, json.JSONDecodeError, KeyError):
    __version__ = "0.0.0"

__all__ = ["__version__"]


def main() -> None:
    """Main entry point for the SmartThings integration."""
    from uc_intg_smartthings.driver import main as driver_main

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s | %(name)-40s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    asyncio.run(driver_main())


if __name__ == "__main__":
    main()
