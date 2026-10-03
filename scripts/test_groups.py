import sys, types

fake_curl = types.ModuleType("curl_cffi")
fake_req = types.ModuleType("curl_cffi.requests")
class AsyncSession: pass
class RetryStrategy: pass
AsyncSession.__init__ = RetryStrategy.__init__ = lambda s, *a, **k: None
fake_req.AsyncSession = AsyncSession
fake_req.RetryStrategy = RetryStrategy
fake_curl.requests = fake_req
sys.modules["curl_cffi"] = fake_curl
sys.modules["curl_cffi.requests"] = fake_req

fake_rxconfig = types.ModuleType("rxconfig")
class Cfg:
    socks5 = ""
    api_url = "http://x:3535"
    proxy_content = True
    impersonate = "chrome"
fake_rxconfig.config = Cfg()
sys.modules["rxconfig"] = fake_rxconfig

fake_utils = types.ModuleType("StepDaddyLiveHD.utils")
fu = fake_utils
fu.encrypt = fu.decrypt = fu.urlsafe_base64 = lambda x: x
fu.decode_econfig = lambda x: {}
sys.modules["StepDaddyLiveHD.utils"] = fu

from StepDaddyLiveHD.step_daddy import tags_to_group

US = "\U0001F1FA\U0001F1F8"
CA = "\U0001F1E8\U0001F1E6"
UK = "\U0001F1EC\U0001F1E7"
IT = "\U0001F1EE\U0001F1F9"
ES = "\U0001F1EA\U0001F1F8"
FR = "\U0001F1EB\U0001F1F7"
PL = "\U0001F1F5\U0001F1F1"
BR = "\U0001F1E7\U0001F1F7"
HU = "\U0001F1ED\U0001F1FA"
NSFW = "\U0001F51E"
QA = "\U0001F1F6\U0001F1E6"
AU = "\U0001F1E6\U0001F1FA"
EG = "\U0001F1EA\U0001F1EC"

tests = [
    ([US, "#sports"], "Sports"),
    ([CA, "#sports", "#hockey"], "Sports"),
    ([UK, "#sports", "#football"], "Sports UK"),
    ([IT, "#sports", "#football"], "Sports Italy"),
    ([ES, "#sports"], "Sports Spain"),
    ([FR, "#movies", "#drama"], "Movies"),
    ([US, "#news"], "News"),
    ([US, "#kids", "#animation"], "Kids"),
    ([US, "#music"], "Music"),
    ([US, "#documentary", "#history"], "Documentary"),
    ([US, "#entertainment", "#general"], "Entertainment"),
    ([US, "#cooking"], "Lifestyle"),
    ([ES, "#sports", "#tennis"], "Sports Spain"),
    ([PL, "#sports", "#football"], "Sports Poland"),
    ([BR, "#sports", "#football"], "Sports Brazil"),
    ([], "General"),
    ([US, "#sports", "#premium"], "Sports"),
    ([US, "#sports", "#tennis", "#live", "#documentary"], "Sports"),
    ([QA, "#sports", "#football"], "Sports Qatar"),
    ([AU, "#sports", "#cricket"], "Sports Australia"),
    ([EG, "#sports"], "Sports Egypt"),
    ([HU, "#sports"], "Sports Hungary"),
    ([NSFW, "#NSFW", "#adult"], "Adult"),
    (["\U0001F30D", "#sports", "#MENA", "#English"], "Sports"),
    (["\U0001F310", "#sports"], "Sports"),
]

for tags, expected in tests:
    result = tags_to_group(tags)
    status = "OK" if result == expected else f"FAIL (expected {expected!r})"
    print(f"{status:6s}  {result:25s} <- {tags}")

print()

from StepDaddyLiveHD.step_daddy import StepDaddy, Channel
sd = StepDaddy()
sd.channels = [
    Channel(id="44", name="ESPN USA", tags=[US, "#sports"], logo=None, tvg_id="ESPN.HD.us2"),
    Channel(id="356", name="BBC One UK", tags=[UK, "#general", "#entertainment"], logo=None, tvg_id=None),
    Channel(id="832", name="CBC CA", tags=[CA, "#general", "#news"], logo=None, tvg_id="CBC.Toronto.HD.ca2"),
    Channel(id="999", name="Adult Channel", tags=[NSFW, "#NSFW", "#adult"], logo=None, tvg_id=None),
    Channel(id="269", name="A Sport PK", tags=[AU, "#sports", "#live"], logo=None, tvg_id=None),
]
print(sd.playlist())
