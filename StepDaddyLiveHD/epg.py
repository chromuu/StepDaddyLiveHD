import gzip
import json
import logging
import os
import shutil
import tempfile
import urllib.request
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

BASE_URL = "https://epgshare01.online/epgshare01/epg_ripper_{}.xml.gz"
SOURCES = ["US2", "CA2", "US_LOCALS1", "FANDUEL1"]
EPG_MAP_PATH = os.path.join("StepDaddyLiveHD", "epg.json")
CACHE_DIR = "epg-cache"
EPG_XML_PATH = os.path.join(CACHE_DIR, "epg.xml")
EPG_GZ_PATH = os.path.join(CACHE_DIR, "epg.xml.gz")


def load_epg_map() -> dict:
    try:
        with open(EPG_MAP_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        logger.warning("Could not load %s, EPG disabled", EPG_MAP_PATH)
        return {}


def _download(source: str, dest: str):
    url = BASE_URL.format(source)
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(request, timeout=120) as response, open(dest, "wb") as f:
        shutil.copyfileobj(response, f)


def _filter_source(gz_path: str, wanted: set, out, seen: set):
    kept_channels = 0
    kept_programmes = 0
    with gzip.open(gz_path, "rb") as f:
        for _, elem in ET.iterparse(f, events=("end",)):
            if elem.tag == "channel":
                cid = elem.get("id")
                if cid in wanted and cid not in seen:
                    seen.add(cid)
                    out.write(ET.tostring(elem, encoding="unicode"))
                    kept_channels += 1
                elem.clear()
            elif elem.tag == "programme":
                if elem.get("channel") in wanted:
                    out.write(ET.tostring(elem, encoding="unicode"))
                    kept_programmes += 1
                elem.clear()
    return kept_channels, kept_programmes


def build_epg():
    epg_map = load_epg_map()
    if not epg_map:
        return
    wanted = set(epg_map.values())
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp_xml = EPG_XML_PATH + ".tmp"
    seen = set()
    with open(tmp_xml, "w", encoding="utf-8") as out:
        out.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        out.write('<tv generator-info-name="StepDaddyLiveHD">\n')
        for source in SOURCES:
            gz_path = None
            try:
                with tempfile.NamedTemporaryFile(suffix=".xml.gz", delete=False) as tmp:
                    gz_path = tmp.name
                _download(source, gz_path)
                channels, programmes = _filter_source(gz_path, wanted, out, seen)
                logger.info("EPG %s: kept %d channels, %d programmes", source, channels, programmes)
            except Exception as e:
                logger.error("EPG source %s failed: %s", source, e)
            finally:
                if gz_path and os.path.exists(gz_path):
                    os.remove(gz_path)
        out.write("</tv>\n")
    if not seen:
        logger.error("EPG build produced no channels, keeping previous file")
        os.remove(tmp_xml)
        return
    os.replace(tmp_xml, EPG_XML_PATH)
    with open(EPG_XML_PATH, "rb") as src, gzip.open(EPG_GZ_PATH + ".tmp", "wb") as dst:
        shutil.copyfileobj(src, dst)
    os.replace(EPG_GZ_PATH + ".tmp", EPG_GZ_PATH)
    logger.info("EPG built: %d channels -> %s", len(seen), EPG_XML_PATH)
