import json
import os
import re
import sys
import urllib.request
from difflib import SequenceMatcher

BASE = "https://epgshare01.online/epgshare01/epg_ripper_{}.txt"
SOURCES = ["US2", "CA2", "US_SPORTS1", "US_LOCALS1", "DUMMY_CHANNELS", "FANDUEL1"]
LISTS_DIR = os.path.join("epg-cache", "lists")
META_PATH = os.path.join("StepDaddyLiveHD", "meta.json")
OUT_PATH = os.path.join("StepDaddyLiveHD", "epg.json")
REPORT_PATH = os.path.join("epg-cache", "match_report.txt")

US_FLAG = "\U0001F1FA\U0001F1F8"
CA_FLAG = "\U0001F1E8\U0001F1E6"

NOISE_TOKENS = {
    "hd", "sd", "4k", "hdtv", "east", "west", "pacific", "eastern", "western",
    "feed", "alternate", "national", "the",
}
STAGE2_TOKENS = {"channel", "network", "tv", "usa", "us", "canada", "ca"}

MANUAL_OVERRIDES = {
    "ABC NY USA": "WABC-DT.us_locals1",
    "CBSNY USA": "WCBS-DT.us_locals1",
    "FOXNY USA": "WNYW-DT.us_locals1",
    "NBCNY USA": "WNBC-DT.us_locals1",
    "CW PIX 11 USA": "WPIX-DT.us_locals1",
    "CW Philly": "WPHL-DT.us_locals1",
    "A&E USA": "A.and.E.HD.East.us2",
    "AHC (American Heroes Channel)": "American.Heroes.Channel.HD.us2",
    "BBC America (BBCA)": "BBC.America.HD.us2",
    "BBC News Channel HD": "BBC.News.(North.America).HD.us2",
    "BeIN SPORTS USA": "beIN.Sports.USA.HD.us2",
    "BIG TEN Network (BTN USA)": "Big.Ten.Network.HD.us2",
    "CBS Sports Network (CBSSN)": "CBS.Sports.Network.HD.us2",
    "C SPAN 1": "C-SPAN.us2",
    "ESPNews": "ESPNEWS.HD.us2",
    "Fox Sports 1 USA": "FS1.HD.us2",
    "Fox Sports 2 USA": "FS2.HD.us2",
    "Great American Family Channel (GAC)": "Great.American.Family.HD.us2",
    "Hallmark Movies & Mysterie": "Hallmark.Mystery.HD.us2",
    "Headline News": "HLN.HD.us2",
    "Heroes & Icons (H&I) USA": "Heroes.and.Icons.us2",
    "Investigation Discovery (ID USA)": "Investigation.Discovery.HD.us2",
    "Lifetime Movies Network": "LMN.HD.us2",
    "MGM+ USA / Epix": "MGM+.HD.East.us2",
    "MY9TV USA": "WWOR-DT.us_locals1",
    "TeleMundo": "Telemundo.Satellite.Feed.us2",
    "Telemundo": "Telemundo.Satellite.Feed.us2",
    "Universo": "UNIVERSO.HD.us2",
    "NBC Universo": "UNIVERSO.HD.us2",
    "5 USA": None,
    "Adult Swim": "AdultSwim.com.Cartoon.Network.us2",
    "CBC CA": "CBC.Toronto.HD.ca2",
    "CTV Canada": "CTV.Toronto.HD.ca2",
    "CTV 2 Canada": "CTV.Two.-.Toronto.ca2",
    "Global CA": "Global.Toronto.HD.ca2",
    "Yes TV CA": "YesTV.ca2",
    "RDS CA": "R\u00e9seau.des.Sports.(RDS).HD.ca2",
    "Discovery Velocity CA": "CTV.Speed.HD.ca2",
    "FOX USA": "WNYW-DT.us_locals1",
    "NBC USA": "NBC.East.Stream.us2",
    "NBC10 Philadelphia": "WCAU-DT.us_locals1",
    "PBS USA": "PBS.Stream.us2",
    "ION USA": "ION.Television.HD.us2",
    "MASN USA": "MASN.-.Mid.Atlantic.Sports.Network.us2",
    "METV USA": "Me.TV.Network.us2",
    "WETV USA": "WE.tv.HD.us2",
    "TCM USA": "Turner.Classic.Movies.HD.us2",
    "TMC Channel USA": "The.Movie.Channel.HD.us2",
    "TVLAND": "TV.Land.HD.us2",
    "NICK": "Nickelodeon.HD.us2",
    "Disney JR": "Disney.Junior.HD.us2",
    "Nat Geo Wild USA": "National.Geographic.Wild.HD.us2",
    "HGTV": "Home.and.Garden.Television.HD.us2",
    "Galavisi\u8d38n USA": "Galavision.Cable.Network.HD.us2",
    "GOLTV USA": "GOL.TV.us2",
    "MTV USA": "MTV.-.Music.Television.HD.us2",
    "Showtime USA": "Paramount+.with.Showtime.HD.us2",
    "Showtime SHOxBET USA": "SHO.x.BET.HD.us2",
    "Sundance TV": "SundanceTV.HD.us2",
    "Reelz Channel": "ReelzChannel.HD.us2",
    "Chicago Sports Network": "CHSN.Chicago.Sports.Network.us2",
    "Crime+ Investigation USA": "Crime.and.Investigation.Network.HD.us2",
    "Starz Kids & Family": "Starz.Kids.HD.us2",
    "Spectrum Sportsnet LA": "Spectrum.SportsNet.LA.Dodgers.HD.us2",
    "Spectrum SportsNet USA": "Spectrum.SportsNet.Lakers.HD.us2",
    "FanDuel Sports Network Kansas City": "FanDuel.Sports.Midwest.-.Kansas.City.us",
    "FanDuel Sports Network Midwest": "FanDuel.Sports.Network.Midwest.St..Louis.us",
    "FanDuel Sports Network Ohio": "FanDuel.Sports.Ohio.-.Cleveland.HD.us",
}


def download_lists():
    os.makedirs(LISTS_DIR, exist_ok=True)
    for src in SOURCES:
        path = os.path.join(LISTS_DIR, f"{src}.txt")
        if not os.path.exists(path):
            print(f"Downloading {src}...")
            urllib.request.urlretrieve(BASE.format(src), path)


def load_ids():
    ids = {"us": [], "ca": []}
    for src in SOURCES:
        with open(os.path.join(LISTS_DIR, f"{src}.txt"), encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("--") or line.isdigit():
                    continue
                country = "ca" if src == "CA2" else "us"
                ids[country].append(line)
    return ids


def strip_suffix(epg_id):
    return re.sub(r"\.(us2|ca2|us_locals1|us)$", "", epg_id)


def normalize(text, stage=1):
    text = text.lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\(.*?\)", " ", text)
    text = re.sub(r"[^a-z0-9+]+", " ", text)
    text = re.sub(r"(?<=[a-z])(?=[0-9])", " ", text)
    tokens = [t for t in text.split() if t not in NOISE_TOKENS]
    if stage >= 2:
        tokens = [t for t in tokens if t not in STAGE2_TOKENS]
    return " ".join(tokens)


def epg_variants(epg_id):
    name = strip_suffix(epg_id).replace(".", " ")
    return name


def is_us_channel(name, tags):
    if US_FLAG in tags:
        return True
    return bool(re.search(r"\b(USA|US)\b", name))


def is_ca_channel(name, tags):
    if CA_FLAG in tags:
        return True
    return bool(re.search(r"\b(Canada|CA)\b", name))


def feed_priority(epg_id):
    low = epg_id.lower()
    score = 0
    if "pacific" in low or "west" in low:
        score += 10
    if "alternate" in low or "(alternate)" in low:
        score += 5
    if ".hd." in low or low.endswith(".hd") or "hd" in low.split("."):
        score -= 2
    if "east" in low:
        score -= 1
    return score


def build_index(id_list, stage):
    index = {}
    for epg_id in id_list:
        key = normalize(epg_variants(epg_id), stage)
        if not key:
            continue
        index.setdefault(key, []).append(epg_id)
    for key in index:
        index[key].sort(key=feed_priority)
    return index


def best_fuzzy(key, index, cutoff=0.9):
    best_score, best_key = 0.0, None
    for cand in index:
        score = SequenceMatcher(None, key, cand).ratio()
        if score > best_score:
            best_score, best_key = score, cand
    if best_score >= cutoff:
        return best_key, best_score
    return None, best_score


def main():
    download_lists()
    ids = load_ids()
    with open(META_PATH, encoding="utf-8") as f:
        meta = json.load(f)

    indexes = {
        country: {stage: build_index(ids[country], stage) for stage in (1, 2)}
        for country in ("us", "ca")
    }

    mapping = {}
    report = {"manual": [], "exact": [], "fuzzy": [], "unmatched": [], "skipped": []}

    for name, info in meta.items():
        tags = info.get("tags") or []
        if name in MANUAL_OVERRIDES:
            epg_id = MANUAL_OVERRIDES[name]
            if epg_id:
                mapping[name] = epg_id
                report["manual"].append(f"{name} -> {epg_id}")
            else:
                report["unmatched"].append(f"{name} (manual: no source)")
            continue
        if is_ca_channel(name, tags) and CA_FLAG in tags:
            country = "ca"
        elif is_us_channel(name, tags):
            country = "us"
        else:
            report["skipped"].append(name)
            continue

        matched = False
        for stage in (1, 2):
            key = normalize(name, stage)
            hit = indexes[country][stage].get(key)
            if hit:
                mapping[name] = hit[0]
                report["exact"].append(f"{name} -> {hit[0]} (stage {stage})")
                matched = True
                break
        if matched:
            continue

        key = normalize(name, 2)
        fuzzy_key, score = best_fuzzy(key, indexes[country][2])
        if fuzzy_key:
            epg_id = indexes[country][2][fuzzy_key][0]
            mapping[name] = epg_id
            report["fuzzy"].append(f"{name} -> {epg_id} ({score:.2f})")
        else:
            report["unmatched"].append(f"{name} (best {score:.2f})")

    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(mapping.items())), f, indent=2, ensure_ascii=False)

    os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        for section in ("manual", "exact", "fuzzy", "unmatched", "skipped"):
            f.write(f"===== {section.upper()} ({len(report[section])}) =====\n")
            for line in report[section]:
                f.write(line + "\n")
            f.write("\n")

    total = len(report["manual"]) + len(report["exact"]) + len(report["fuzzy"])
    print(f"Matched: {total} (manual {len(report['manual'])}, exact {len(report['exact'])}, fuzzy {len(report['fuzzy'])})")
    print(f"Unmatched US/CA: {len(report['unmatched'])}")
    print(f"Skipped (non-US/CA): {len(report['skipped'])}")
    print(f"Wrote {OUT_PATH} and {REPORT_PATH}")


if __name__ == "__main__":
    sys.exit(main())
