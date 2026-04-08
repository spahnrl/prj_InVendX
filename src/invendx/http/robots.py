from __future__ import annotations

import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)


class RobotsPolicy:
    """Per-origin robots.txt cache. Uses stdlib RobotFileParser."""

    def __init__(self, user_agent: str) -> None:
        self._ua = user_agent
        self._cache: dict[str, RobotFileParser] = {}

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        robots_url = f"{origin}/robots.txt"
        rp = self._cache.get(origin)
        if rp is None:
            rp = RobotFileParser()
            try:
                rp.set_url(robots_url)
                rp.read()
            except Exception as e:  # noqa: BLE001
                logger.debug("robots read failed %s: %s", robots_url, e)
                rp = _AllowAllParser()
            self._cache[origin] = rp
        return rp.can_fetch(self._ua, url)


class _AllowAllParser:
    def can_fetch(self, _ua: str, _url: str) -> bool:
        return True
