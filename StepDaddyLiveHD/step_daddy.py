import json
import re
from pydantic import BaseModel
from urllib.parse import urlparse, urljoin, parse_qs
from curl_cffi.requests import AsyncSession, RetryStrategy
from typing import List
from .utils import encrypt, decrypt, urlsafe_base64, decode_econfig
from rxconfig import config
import html

import asyncio
import time
import logging
import base64
import random

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# Upstream statuses that mean the signed stream token has expired or been revoked.
TOKEN_EXPIRED_STATUSES = (403, 410)
# A fresh entry is not evicted again for this long, so late 403s from segments
# or keys signed with the previous token don't throw away the new one.
EVICT_GRACE_SECONDS = 20
# Re-resolving a channel this soon after it was evicted is delayed slightly to
# avoid hammering the CDN when a token keeps getting rejected.
REFETCH_COOLDOWN_SECONDS = 120


class UpstreamError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class Channel(BaseModel):
    id: str
    name: str
    tags: List[str]
    logo: str | None
    tvg_id: str | None = None


FLAG_TO_COUNTRY = {
    "\U0001F1FA\U0001F1F8": "US",
    "\U0001F1E8\U0001F1E6": "CA",
    "\U0001F1EC\U0001F1E7": "UK",
    "\U0001F1EE\U0001F1F9": "Italy",
    "\U0001F1EB\U0001F1F7": "France",
    "\U0001F1E9\U0001F1EA": "Germany",
    "\U0001F1EA\U0001F1F8": "Spain",
    "\U0001F1F5\U0001F1F1": "Poland",
    "\U0001F1F5\U0001F1F9": "Portugal",
    "\U0001F1EC\U0001F1F7": "Greece",
    "\U0001F1EE\U0001F1F1": "Israel",
    "\U0001F1FF\U0001F1E6": "South Africa",
    "\U0001F1E7\U0001F1EC": "Bulgaria",
    "\U0001F1F7\U0001F1F8": "Serbia",
    "\U0001F1E9\U0001F1F0": "Denmark",
    "\U0001F1F8\U0001F1EA": "Sweden",
    "\U0001F1F6\U0001F1E6": "Qatar",
    "\U0001F1F2\U0001F1FD": "Mexico",
    "\U0001F1F3\U0001F1F1": "Netherlands",
    "\U0001F1E8\U0001F1FF": "Czech",
    "\U0001F1E7\U0001F1F7": "Brazil",
    "\U0001F1F9\U0001F1F7": "Turkey",
    "\U0001F1F3\U0001F1FF": "New Zealand",
    "\U0001F1E6\U0001F1FA": "Australia",
    "\U0001F1F2\U0001F1FE": "Malaysia",
    "\U0001F1F7\U0001F1F4": "Romania",
    "\U0001F1E6\U0001F1F7": "Argentina",
    "\U0001F1E6\U0001F1EA": "UAE",
    "\U0001F1E8\U0001F1FE": "Cyprus",
    "\U0001F1ED\U0001F1F7": "Croatia",
    "\U0001F1F7\U0001F1FA": "Russia",
    "\U0001F1EE\U0001F1F3": "India",
    "\U0001F1EE\U0001F1EA": "Ireland",
    "\U0001F1F5\U0001F1F0": "Pakistan",
    "\U0001F1EA\U0001F1EC": "Egypt",
    "\U0001F1E7\U0001F1E6": "Bosnia",
    "\U0001F1E7\U0001F1E9": "Bangladesh",
    "\U0001F1E6\U0001F1F9": "Austria",
    "\U0001F1E8\U0001F1F4": "Colombia",
    "\U0001F1FA\U0001F1FE": "Uruguay",
    "\U0001F1E8\U0001F1F1": "Chile",
    "\U0001F1ED\U0001F1FA": "Hungary",
}

SPORTS_TAGS = {
    "#sports", "#football", "#basketball", "#cricket", "#tennis", "#golf",
    "#motorsport", "#f1", "#motogp", "#rally", "#racing", "#baseball",
    "#hockey", "#rugby", "#wrestling", "#mma", "#combatsports", "#combat",
    "#darts", "#nfl", "#laliga", "#soccer", "#college",
}

MOVIE_TAGS = {
    "#movies", "#action", "#drama", "#thriller", "#comedy", "#horror",
    "#suspense", "#mystery", "#romance", "#western", "#westerns",
    "#classics", "#sciencefiction", "#scifi", "#classic",
}

NEWS_TAGS = {"#news", "#weather", "#politics", "#breaking", "#publicaffairs"}

KIDS_TAGS = {"#kids", "#cartoons", "#animation", "#family", "#youth"}

MUSIC_TAGS = {"#music", "#hits", "#country"}

DOC_TAGS = {"#documentary", "#history", "#science", "#nature", "#animals", "#education"}

LIFESTYLE_TAGS = {"#cooking", "#travel", "#fashion", "#home", "#outdoors", "#health"}

ENTERTAINMENT_TAGS = {
    "#entertainment", "#general", "#variety", "#reality", "#lifestyle",
    "#culture", "#talk", "#arts", "#series",
}


def tags_to_group(tags: List[str]) -> str:
    if not tags:
        return "General"
    hashes = {t for t in tags if t.startswith("#")}
    hashes_lower = {t.lower() for t in hashes}
    flag = next((t for t in tags if t not in hashes and t not in {"", " "}), "")

    if hashes_lower & {"#nsfw", "#adult"}:
        return "Adult"

    is_sports = bool(hashes_lower & SPORTS_TAGS)
    if is_sports:
        country = FLAG_TO_COUNTRY.get(flag)
        if country in ("US", "CA", None):
            return "Sports"
        return f"Sports {country}"

    if hashes_lower & MOVIE_TAGS:
        return "Movies"
    if hashes_lower & NEWS_TAGS:
        return "News"
    if hashes_lower & KIDS_TAGS:
        return "Kids"
    if hashes_lower & MUSIC_TAGS:
        return "Music"
    if hashes_lower & DOC_TAGS:
        return "Documentary"
    if hashes_lower & LIFESTYLE_TAGS:
        return "Lifestyle"
    if hashes_lower & ENTERTAINMENT_TAGS:
        return "Entertainment"
    if hashes_lower & {"#business"}:
        return "Business"
    if hashes_lower & {"#international", "#arabic", "#mena", "#english"}:
        return "International"
    if hashes_lower & {"#regional", "#local", "#community", "#public", "#national"}:
        return "Regional"
    if hashes_lower & {"#premium", "#select", "#extra"}:
        return "Premium"
    return "General"


class StepDaddy:
    def __init__(self):
        socks5 = config.socks5
        strategy = RetryStrategy(
            count=3, delay=0.5, jitter=0.1, backoff="exponential")
        # Do NOT override User-Agent manually: curl_cffi sets one matching the
        # impersonated fingerprint, and a mismatched/duplicate UA header gets
        # the embed host to return 403.
        session_kwargs = dict(
            impersonate=config.impersonate, retry=strategy, allow_redirects="safe")
        if socks5 != "":
            session_kwargs["proxy"] = "socks5://" + socks5
        self._session = AsyncSession(**session_kwargs)
        self._base_url = "https://dlive.sx"
        self.channels = []
        self.channel_auth_done = False
        with open("StepDaddyLiveHD/meta.json", "r") as f:
            self._meta = json.load(f)
        try:
            with open("StepDaddyLiveHD/epg.json", "r", encoding="utf-8") as f:
                self._epg_map = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._epg_map = {}
        self._cache = {}  # channel_id -> resolved playlist info (see _resolve)
        self._evicted_at = {}  # channel_id -> when its token was last rejected
        self._resolve_locks = {}  # channel_id -> lock so viewers share one resolve
        self._prefetch_tasks = set()  # keeps background re-resolves referenced
        # Cookies to be set by Flaresolverr first and used by curl_cffi subsequently
        self._cookies = {}

    def _headers(self, referer: str = None, origin: str = None):
        if referer is None:
            referer = self._base_url
        headers = {"Referer": referer}
        if origin:
            headers["Origin"] = origin
        return headers


    async def load_channels(self):
        """Fetch the channel list and replace ``self.channels`` on success.

        Raises on any failure (network error, bad status, no channels parsed)
        and leaves the previous channel list in place, so a transient upstream
        problem doesn't wipe the playlist.
        """
        channels = []
        channels_url = f"{self._base_url}/24-7-channels.php"
        response = await self._session.post(
            url=channels_url,
            headers=self._headers(),
            cookies=self._cookies
        )
        # Logic to update self._base_url if it hase moved to a new domain
        url_from_resp = urlparse(response.url)
        extracted_base_url = f"{
            url_from_resp.scheme}://{url_from_resp.netloc}"
        if extracted_base_url != self._base_url:
            logger.info(f"Updated baseUrl: {extracted_base_url}")
            self._base_url = extracted_base_url

        if response.status_code != 200:
            raise RuntimeError(
                f"Channel list returned HTTP {response.status_code}")

        matches = re.findall(
            r'<a class="card"\s+href="/watch\.php\?id=(\d+)"[^>]*>\s*<div class="card__title">(.*?)</div>',
            # response,
            response.text,
            re.DOTALL
        )
        for channel_id, channel_name in matches:
            channel_name = html.unescape(
                channel_name.strip()).replace("#", "")
            meta = self._meta.get(
                "18+" if channel_name.startswith("18+") else channel_name, {})
            logo = meta.get("logo", "")
            if logo:
                logo = f"{config.api_url}/logo/{urlsafe_base64(logo)}"
            channels.append(
                Channel(id=channel_id, name=channel_name, tags=meta.get("tags", []), logo=logo,
                        tvg_id=self._epg_map.get(channel_name)))
        if not channels:
            raise RuntimeError("Channel list page contained no channels")
        self.channels = sorted(channels, key=lambda channel: (
            channel.name.startswith("18"), channel.name))
        logger.info(f"Loaded {len(self.channels)} channels")

    async def _extract_stream_url(self, source_url: str) -> str:
        """Fetch the embed page and pull the signed m3u8 URL out of it.

        The embed page currently ships its config as ``window._econfig`` (see
        ``decode_econfig``). The older ``window.atob("...")`` form is kept as a
        fallback in case the provider flips back.
        """
        source_resp = await self._session.get(
            url=source_url,
            headers=self._headers(f"{self._base_url}/"),
            timeout=12
        )
        if source_resp.status_code != 200:
            logger.warning(f"Embed page returned {source_resp.status_code} for {source_url}")
            raise IndexError(f"Embed page returned {source_resp.status_code}")

        econfig = re.search(
            r"window\._econfig\s*=\s*['\"]([^'\"]+)['\"]", source_resp.text)
        if econfig:
            cfg = decode_econfig(econfig.group(1))
            stream_url = cfg.get("stream_url_nop2p") or cfg.get("stream_url")
            if not stream_url:
                raise IndexError("No stream_url in embed config")
            return stream_url

        legacy = re.search(
            r'window\.atob\(["\']([A-Za-z0-9+/=]+)["\']\)', source_resp.text)
        if legacy:
            return base64.b64decode(legacy.group(1)).decode("utf-8")

        logger.warning("Embed page format not recognised (no _econfig / atob)")
        raise IndexError("Unable to locate stream config in embed page")

    async def _resolve(self, channel_id: str) -> dict:
        """Resolve a channel id to a media playlist URL (uncached)."""
        url = f"{self._base_url}/stream/stream-{channel_id}.php"
        response = await self._session.post(
            url=url,
            headers=self._headers(),
            cookies=self._cookies,
            timeout=12
        )
        matches = re.findall(r'<iframe[^>]+src="([^"]+)"', response.text)
        if not matches:
            raise IndexError("No embed iframe found on stream page")
        source_url = matches[0]
        logger.info("source_url: %s", source_url)

        m3u8_url = await self._extract_stream_url(source_url)
        logger.info(f"m3u8_url: {m3u8_url}")

        # Signed URLs carry their expiry as ?e= (current) or ?expires= (older).
        query = parse_qs(urlparse(m3u8_url).query)
        expiry = query.get("e") or query.get("expires")
        try:
            expiry = int(expiry[0])
        except (TypeError, ValueError, IndexError):
            expiry = int(time.time()) + 2400
        logger.info(f"Expiry timestamp: {expiry}")

        m3u8_resp = await self._session.get(
            url=m3u8_url,
            headers=self._headers(source_url),
            timeout=12
        )
        if not m3u8_resp.text.startswith("#EXTM3U"):
            logger.warning(f"Invalid CDN response, discarding: {m3u8_resp.text[:120]}")
            raise IndexError("Invalid CDN response")

        # The URL may point at a master playlist (variant list) or directly at
        # a media playlist. Only follow it if it is a master.
        m3u8_playlist_url = m3u8_url
        m3u8_stream_info = ""
        if "#EXT-X-STREAM-INF" in m3u8_resp.text:
            m3u8_playlist_url = None
            for line in m3u8_resp.text.split("\n"):
                if line.startswith("#EXT-X-STREAM-INF"):
                    m3u8_stream_info = line
                elif line and not line.startswith("#"):
                    m3u8_playlist_url = urljoin(m3u8_url, line)
            if m3u8_playlist_url is None:
                raise IndexError("No playable stream URL found")
        logger.info(f"m3u8_playlist_url: {m3u8_playlist_url}")

        return {
            "source_url": source_url,
            "m3u8_playlist_url": m3u8_playlist_url,
            "m3u8_stream_info": m3u8_stream_info,
            "expiry": expiry,
            "resolved_at": time.time(),
        }

    async def _get_entry(self, channel_id: str) -> dict:
        """Return a valid cached entry for the channel, resolving it if needed."""
        entry = self._cache.get(channel_id)
        if entry is not None and int(time.time()) < entry["expiry"]:
            return entry
        lock = self._resolve_locks.setdefault(channel_id, asyncio.Lock())
        async with lock:
            # Another viewer may have resolved it while we waited for the lock.
            entry = self._cache.get(channel_id)
            if entry is not None and int(time.time()) < entry["expiry"]:
                return entry
            logger.info(f"Cache miss for channel {channel_id}")
            self._cache.pop(channel_id, None)
            since_evict = time.time() - self._evicted_at.get(channel_id, 0)
            if since_evict < REFETCH_COOLDOWN_SECONDS:
                cooldown = random.uniform(1.0, 3.0)
                logger.info(f"Cooling down {cooldown:.1f}s before CDN re-fetch for channel {channel_id}")
                await asyncio.sleep(cooldown)
            entry = await self._resolve(channel_id)
            self._cache[channel_id] = entry
            return entry

    async def stream(self, channel_id: str):
        # Try the cached token first; if the CDN rejects it, evict this channel
        # only and retry once with a freshly resolved token. This is also what
        # catches expiry when PROXY_CONTENT is off and segments bypass us.
        for attempt in range(2):
            entry = await self._get_entry(channel_id)
            source_url = entry["source_url"]
            m3u8_playlist_url = entry["m3u8_playlist_url"]
            m3u8_stream_info = entry["m3u8_stream_info"]

            m3u8_playlist_resp = await self._session.get(
                url=m3u8_playlist_url,
                headers=self._headers(source_url),
                timeout=12
            )
            if m3u8_playlist_resp.status_code == 200 and m3u8_playlist_resp.text.startswith("#EXTM3U"):
                break
            logger.warning(f"Media playlist fetch failed ({m3u8_playlist_resp.status_code}) for channel {channel_id}")
            # Token most likely expired early; drop it so the retry re-resolves.
            self.invalidate_channel(channel_id, force=True)
        else:
            raise IndexError("Media playlist unavailable")

        m3u8_data = ""
        for line in m3u8_playlist_resp.text.split("\n"):
            if line.startswith('#'):
                if line.startswith("#EXT-X-KEY:"):
                    original_url = re.search(r'URI="(.*?)"', line).group(1)
                    content_key_url = urljoin(m3u8_playlist_url, original_url)
                    line = line.replace(original_url, f"{
                        config.api_url}/key/{encrypt(content_key_url)}/{encrypt(source_url)}")
            elif line != '':
                # Segment URIs are relative to the upstream playlist, so they
                # must be absolutised even when not proxying.
                line = urljoin(m3u8_playlist_url, line)
                if config.proxy_content:
                    line = f"{
                        config.api_url}/content/{encrypt(line)}/{encrypt(source_url)}.ts"
            m3u8_data += line + "\n"
        m3u8_data += m3u8_stream_info
        return m3u8_data

    async def key(self, url: str, host: str):
        url = decrypt(url)
        host = decrypt(host)
        logger.info(f"Content_Key_Url: {url}")
        key_headers = self._headers(referer=f"{host}")

        key_response = await self._session.get(url, headers=key_headers, timeout=12)
        if key_response.status_code != 200:
            if key_response.status_code in TOKEN_EXPIRED_STATUSES:
                # The key is signed with the same token as the playlist, so a
                # rejected key means the channel's token is dead.
                self.invalidate_source(host)
            raise UpstreamError(key_response.status_code, f"Failed to get key ({key_response.status_code})")
        return key_response.content

    async def _prefetch(self, channel_id: str):
        try:
            await self._get_entry(channel_id)
        except Exception as e:
            logger.warning(f"Background re-resolve failed for channel {channel_id}: {e}")

    @staticmethod
    def content_url(path: str):
        return decrypt(path)

    def invalidate_channel(self, channel_id: str, force: bool = False) -> bool:
        """Drop one channel's cached token. Returns True if it was evicted.

        Unless ``force`` is set, an entry resolved within the last
        EVICT_GRACE_SECONDS is kept: in-flight requests still carrying the old
        token keep failing for a moment after a re-resolve.
        """
        entry = self._cache.get(channel_id)
        if entry is None:
            return False
        if not force and time.time() - entry.get("resolved_at", 0) < EVICT_GRACE_SECONDS:
            return False
        logger.info(f"Token expired for channel {channel_id}, evicting it from cache")
        del self._cache[channel_id]
        self._evicted_at[channel_id] = time.time()
        return True

    def invalidate_source(self, source_url: str) -> str | None:
        """Evict the channel whose embed page is ``source_url``.

        Segment and key URLs carry the channel's source_url rather than its id,
        so this maps one back to the other. The channel is re-resolved in the
        background so the player's next playlist reload doesn't wait for it.
        Returns the evicted channel id.
        """
        for channel_id, entry in list(self._cache.items()):
            if entry["source_url"] == source_url:
                if not self.invalidate_channel(channel_id):
                    return None
                task = asyncio.create_task(self._prefetch(channel_id))
                self._prefetch_tasks.add(task)
                task.add_done_callback(self._prefetch_tasks.discard)
                return channel_id
        return None

    def playlist(self):
        data = f"#EXTM3U url-tvg=\"{config.api_url}/epg.xml\"\n"
        for channel in self.channels:
            attrs = f" group-title=\"{tags_to_group(channel.tags)}\""
            if channel.tvg_id:
                attrs += f" tvg-id=\"{channel.tvg_id}\""
            if channel.logo:
                attrs += f" tvg-logo=\"{channel.logo}\""
            data += f"#EXTINF:-1{attrs},{channel.name}\n{
                config.api_url}/stream/{channel.id}.m3u8\n"
        return data

    async def schedule(self):
        response = await self._session.get(f"{self._base_url}/schedule/schedule-generated.php", headers=self._headers())
        return response.json()
