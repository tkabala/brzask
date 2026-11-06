# Changelog

## [0.1.16](https://github.com/tkabala/brzask/compare/v0.1.15...v0.1.16) (2026-11-06)


### Features

* **notify:** brzask notify test ([66561f9](https://github.com/tkabala/brzask/commit/66561f9184b32597104895bf6963923723983d88))
* **notify:** digest-ready and run-failed messages ([5388a69](https://github.com/tkabala/brzask/commit/5388a69e9965c6fa9cca420d0e54e10d6b90dcc5))
* **notify:** notify after pipeline runs ([ab80b5c](https://github.com/tkabala/brzask/commit/ab80b5c197431610adde27c25aaf25f47d507a29))
* **notify:** NOTIFY_URLS setting ([6006127](https://github.com/tkabala/brzask/commit/60061278e322defdb28a3d98386caa17f57106bd))


### Bug Fixes

* **notify:** keep notification URLs out of debug logs and Sentry breadcrumbs ([e1800ea](https://github.com/tkabala/brzask/commit/e1800ea9816ee4091aa60f1f838b5955cb02444a))
* **notify:** leave NOTIFY_URLS empty in .env.example ([fbbb4f0](https://github.com/tkabala/brzask/commit/fbbb4f00e9b6a11486294c2e9d014b1f6a968645))
* **notify:** name the failed NOTIFY_URLS entries in the log ([e5641b0](https://github.com/tkabala/brzask/commit/e5641b06002524841f26872a67a106b2980b653a))


### Documentation

* notifications ([bae9965](https://github.com/tkabala/brzask/commit/bae9965765487e6e30edba90a2f40da11ac75d8b))


### Chores

* release 0.1.16 ([6338359](https://github.com/tkabala/brzask/commit/633835961221c107d5275db6d49704f0cf5b36f5))

## [0.1.15](https://github.com/tkabala/brzask/compare/v0.1.14...v0.1.15) (2026-11-06)


### Features

* **api:** prefix open and feed links and the session cookie ([9b68d93](https://github.com/tkabala/brzask/commit/9b68d9367d90dedf0181283434e816fda8e78dfa))
* **api:** serve under the BASE_URL path ([c9447b3](https://github.com/tkabala/brzask/commit/c9447b31e215c0a5684ca88337de83026df26734))
* **archive:** export every durable table ([41b034c](https://github.com/tkabala/brzask/commit/41b034c99a9202c9780aceb2efe3a98432f51987))
* **archive:** import into an empty database ([29f6c12](https://github.com/tkabala/brzask/commit/29f6c12d7953d602ab50aa983214b65f2ecd481a))
* **archive:** portable archive format ([618b500](https://github.com/tkabala/brzask/commit/618b500d7fbe6271ddd4ed8a25ef4c6df6d33210))
* **cli:** brzask export and import ([91459a5](https://github.com/tkabala/brzask/commit/91459a533391d7e4c5dc73d6d47d479080ceaf23))
* **config:** add BASE_URL ([f4c8224](https://github.com/tkabala/brzask/commit/f4c8224d7aa05867df985b4fb69bc1172c9e9158))
* **deploy:** add an observability profile ([6c44f69](https://github.com/tkabala/brzask/commit/6c44f6953b548f05049b006de77008435116fe4d))
* **deploy:** provision a brzask dashboard ([e434a92](https://github.com/tkabala/brzask/commit/e434a92e6743aa309ca5bc01833859e304f2cc97))
* **telemetry:** measure pipeline runs, LLM cost and digest articles ([8687687](https://github.com/tkabala/brzask/commit/86876873bf02807ca33712dacb8c8d10a3f12024))
* **telemetry:** report the open rate of the last seven digests ([7850090](https://github.com/tkabala/brzask/commit/7850090517ab0365054f0cc43af9551a43e38c60))
* **telemetry:** trace each pipeline run as one span ([35200f6](https://github.com/tkabala/brzask/commit/35200f69a1d133a8d7f4e5dbaf423aad36b9eb2f))
* **web:** run under any path prefix ([0de9cd8](https://github.com/tkabala/brzask/commit/0de9cd85ffac61312fc50d055e42ef068232771c))


### Bug Fixes

* **api:** keep routes, cookies and odd prefixes right under BASE_URL ([6843b4d](https://github.com/tkabala/brzask/commit/6843b4deda4cbb91f8132297d507ad16f6e743dc))
* **archive:** accept database rows in encode_row ([d25cc82](https://github.com/tkabala/brzask/commit/d25cc82ba6514e4c6fc312d9d9f32754f17c0492))
* **archive:** one-line errors for bad values and unwritable paths ([81ecb00](https://github.com/tkabala/brzask/commit/81ecb0002507dc0e947c62e400924d2ca63af6d5))
* **telemetry:** keep the run's context in worker threads ([81b7bbf](https://github.com/tkabala/brzask/commit/81b7bbfb1c28f1300f451153718b7497986a4059))
* **telemetry:** show the open rate all day and keep its reads out of traces ([896d38e](https://github.com/tkabala/brzask/commit/896d38e3bcef9dc09c2944d9220203d91de0bdb5))


### Documentation

* describe the observability profile ([aa36524](https://github.com/tkabala/brzask/commit/aa3652477e4cde0d7a2c128ab8730cb6bdf9b1cf))
* portable export and a restore test ([4920e45](https://github.com/tkabala/brzask/commit/4920e453ad5b097ff7a2b02406e385f6ddd34991))
* serving under a sub-path and Traefik examples ([0a1ee16](https://github.com/tkabala/brzask/commit/0a1ee16e5c8719ac411b274be1104d329c0f5986))


### Chores

* release 0.1.15 ([214c498](https://github.com/tkabala/brzask/commit/214c49870464c329ab8a1e96b49041ef5849a7e4))
* release 0.1.15 ([3d75601](https://github.com/tkabala/brzask/commit/3d7560106bc63b948aa63b55c0849d215e2de32d))
* release 0.1.16 ([408c504](https://github.com/tkabala/brzask/commit/408c5048fb4f1b5982938e01f851c78c6507e23b))
* release 0.1.17 ([bf5ddc4](https://github.com/tkabala/brzask/commit/bf5ddc4d534eb3909d1d0d0303ed6f920324806c))

## [0.1.14](https://github.com/tkabala/brzask/compare/v0.1.13...v0.1.14) (2026-11-05)


### Features

* **pwa:** keep today's digest for offline reading ([199418f](https://github.com/tkabala/brzask/commit/199418f8fe7f92ccb403dadb9c777636f53df8ba))
* **pwa:** make the web app installable ([7bc29b9](https://github.com/tkabala/brzask/commit/7bc29b9a82f670d973eef4cf3b76e62b5f165b5c))
* **pwa:** say when the app is offline ([e5b1d54](https://github.com/tkabala/brzask/commit/e5b1d541257e5497f559ef9f3fb9ca42b4e446e9))


### Bug Fixes

* **pwa:** keep the saved copy to its own reader ([6f03176](https://github.com/tkabala/brzask/commit/6f03176dac19ec7032addb56dae363028b8b90f6))
* **pwa:** start offline when the browser already is ([65279c5](https://github.com/tkabala/brzask/commit/65279c5638dc8254fbc91855209b7637ceb041b7))


### Documentation

* **pwa:** describe installing the app and reading offline ([878e8da](https://github.com/tkabala/brzask/commit/878e8da2cbc0efc433860dd42a4045ed9bc92a2f))


### Chores

* release 0.1.14 ([d2d57a4](https://github.com/tkabala/brzask/commit/d2d57a431761308d79a0ec94ee622f056c200d43))

## [0.1.13](https://github.com/tkabala/brzask/compare/v0.1.12...v0.1.13) (2026-11-05)


### Features

* **budget:** sum spending per day and month and decide when a limit is reached ([e24f65a](https://github.com/tkabala/brzask/commit/e24f65a3a7a262d9e2c31feb5d538f4f370445e5))
* **config:** add daily and monthly spending limits ([398f0bd](https://github.com/tkabala/brzask/commit/398f0bdfa459d6a65be3b88d1759c910a75f50fc))
* **digest:** rank by pool order and skip the dedup judge over budget ([d6471c0](https://github.com/tkabala/brzask/commit/d6471c08f4a7bf4f53d6dd38281b036f62a64a53))
* **discovery:** skip discovery when the spending limit is reached ([0988509](https://github.com/tkabala/brzask/commit/09885099c3cc16de950857aed107d7b546f5e87d))
* **status:** show when a run hit the spending limit ([3830fa6](https://github.com/tkabala/brzask/commit/3830fa6cc9c01e83cd4a364698b054466d419bb7))
* **usage:** report the known part of a run's cost ([9767cd1](https://github.com/tkabala/brzask/commit/9767cd168a09c14acbbf60d74e8ce7489f94017a))


### Bug Fixes

* **budget:** count only JSON numbers when summing spending ([cc93ba2](https://github.com/tkabala/brzask/commit/cc93ba2e3fd817680da6297b6abbcdd2eb41e902))


### Documentation

* describe the spending limits ([0a9c1c2](https://github.com/tkabala/brzask/commit/0a9c1c274c0c52e6d4431dae643df9fb0fa94920))
* state the measured saving of a degraded digest ([33ada2e](https://github.com/tkabala/brzask/commit/33ada2e31bee17544d1ef9e306450c2cada47719))


### Chores

* release 0.1.13 ([08f19a5](https://github.com/tkabala/brzask/commit/08f19a57b6dd3ddaaa64e8e22dfd53ad39ddb432))

## [0.1.12](https://github.com/tkabala/brzask/compare/v0.1.11...v0.1.12) (2026-11-05)


### Features

* **ranking:** show each candidate's age in the ranking prompt ([58f88f5](https://github.com/tkabala/brzask/commit/58f88f5042d400b37f4ef76405d05174aad92bd2))
* **sources:** import and export sources as OPML ([c9b4198](https://github.com/tkabala/brzask/commit/c9b4198283daa1147e211bcbd6ec55303088194f))


### Bug Fixes

* **selection:** read a topic copied with its keywords as the interest topic ([af9a22d](https://github.com/tkabala/brzask/commit/af9a22d6fc85e37285239bf16e653ea70b937628))
* **selection:** top up a short answer from the candidates it left ([f349191](https://github.com/tkabala/brzask/commit/f349191b6d2aa09f0b6c425db1a579377fb271b6))


### Chores

* release 0.1.12 ([f963ef2](https://github.com/tkabala/brzask/commit/f963ef2a5aa024996d0cd059e998498c8cf6c7d1))

## [0.1.11](https://github.com/tkabala/brzask/compare/v0.1.10...v0.1.11) (2026-11-04)


### Features

* **auth:** add a feed token scope that only opens the digest feed ([2c44cc2](https://github.com/tkabala/brzask/commit/2c44cc20be249e132cbef9896f05f6f99938d297))
* **feed:** render digest entries as Atom ([726c983](https://github.com/tkabala/brzask/commit/726c983d8d7b2e78cf0f1a4cc9a3e7d23fdc54dd))
* **feed:** serve the digest of the last seven days as an Atom feed ([9c00114](https://github.com/tkabala/brzask/commit/9c0011420ec3e4b5c894f92fd194d0fb7d751aed))


### Bug Fixes

* **feed:** keep the token out of Sentry and give the feed an author ([7fe3a26](https://github.com/tkabala/brzask/commit/7fe3a26bd02e1d21e903a0300ddc1ac593c9e1f2))
* **log:** redact tokens in request URLs from the access log and spans ([499bce0](https://github.com/tkabala/brzask/commit/499bce0556d8e351be1e97c93c0fbe79fff593be))


### Documentation

* describe the digest feed and letting it past proxy auth ([d414135](https://github.com/tkabala/brzask/commit/d41413552164d1b3489705f66c9e4ea0177df6d8))


### Chores

* release 0.1.11 ([4845b0e](https://github.com/tkabala/brzask/commit/4845b0e64306f10b98b7eaa486a55bb37702c587))

## [0.1.10](https://github.com/tkabala/brzask/compare/v0.1.9...v0.1.10) (2026-11-02)


### Bug Fixes

* **digest:** keep same-day duplicates of a shown article out of later pools ([ca1c5e6](https://github.com/tkabala/brzask/commit/ca1c5e605945ba8eb7f53f4e642dafb3e1a6eaef))
* **discovery:** do not take a blog for a copy of an aggregator that links to it ([7d8be72](https://github.com/tkabala/brzask/commit/7d8be72d0160b2abefe0696fafe35fc35162c1d7))
* **discovery:** follow a fork to its original repository only when that has releases ([2f11bf5](https://github.com/tkabala/brzask/commit/2f11bf56f9d77541850627004c4e34553dd464a7))
* **discovery:** reject copies of known sources instead of enabling them ([b78b403](https://github.com/tkabala/brzask/commit/b78b403fd9d96638c72f15907fbc8230ff5f45ce))
* **discovery:** stop asking the web search for GitHub repositories ([1559735](https://github.com/tkabala/brzask/commit/155973547e55c86125914c6d63c2ca881fb84f46))
* **judge:** leave the reasoning effort out for a chat-model judge on another API ([f16dd8c](https://github.com/tkabala/brzask/commit/f16dd8c226f431bdf019fb43798cf8745496d6b8))
* **llm:** ask for a fixed reasoning effort instead of the provider's default ([72181e4](https://github.com/tkabala/brzask/commit/72181e4faecb5140551d2371e1b5e140e411743f))

## [0.1.9](https://github.com/tkabala/brzask/compare/v0.1.8...v0.1.9) (2026-10-28)


### Features

* **digest:** keep repeats of shown articles out of later pools ([125fa06](https://github.com/tkabala/brzask/commit/125fa06cac443147c7c3599961b8bb646a36ce6e))


### Bug Fixes

* **extractors:** recognise Cloudflare's security verification page ([19ea09b](https://github.com/tkabala/brzask/commit/19ea09be034020c9011ad35eab808c706f063175))


### Chores

* release 0.1.9 ([192de18](https://github.com/tkabala/brzask/commit/192de181591996ee4531a3b71f1c8a5028d0bf92))

## [0.1.8](https://github.com/tkabala/brzask/compare/v0.1.7...v0.1.8) (2026-10-26)


### Bug Fixes

* **feeds:** fail a feed with a malformed URL without stopping the others ([bebb55f](https://github.com/tkabala/brzask/commit/bebb55f78ec7a27c2b7f471f4af34f04935334f2))
* **feeds:** report moves with 304, ignore query changes, judge whole block pages ([2f8f21d](https://github.com/tkabala/brzask/commit/2f8f21d43a20e57b880cb60b3cf5e832aea8cea5))
* **llm:** read the logged call details defensively ([a63edde](https://github.com/tkabala/brzask/commit/a63edde471dbe8bcf32b5804bafa1bca034803b1))
* **selection:** fall back to the path only for a link without a query ([f8fbbd3](https://github.com/tkabala/brzask/commit/f8fbbd38762c79c850f717cb040a9ca184ac7f7b))
* **sources:** log a rejection by hand as source.reject ([7e6d226](https://github.com/tkabala/brzask/commit/7e6d22616e7527a7bfb92ad24063ca2cdc3fcfbf))
* **sources:** move a source onto its own URL in another case, keep merged articles ([144c0a0](https://github.com/tkabala/brzask/commit/144c0a0012fce41545cfbe914636871f730e70f3))

## [0.1.7](https://github.com/tkabala/brzask/compare/v0.1.6...v0.1.7) (2026-10-26)


### Bug Fixes

* **discovery:** ask the web search for repositories that publish releases ([6acec5e](https://github.com/tkabala/brzask/commit/6acec5eaf79e602fa8d621b355f44f10078dcc5b))
* **sources:** merge a muted duplicate when a feed moves onto its URL ([ca06654](https://github.com/tkabala/brzask/commit/ca066545a8acad05516455c7ca9191e2d77b28db))

## [0.1.6](https://github.com/tkabala/brzask/compare/v0.1.5...v0.1.6) (2026-10-26)


### Features

* **llm:** log the provider and reasoning tokens of each call ([f0c4689](https://github.com/tkabala/brzask/commit/f0c4689d60221e31ff3e1e3736055aa8d02bd986))


### Bug Fixes

* **feeds:** count an anti-bot page as a permanent fetch failure ([b5ab102](https://github.com/tkabala/brzask/commit/b5ab102d98bdb87f828de0c875158264a12dc072))


### Chores

* release 0.1.6 ([c13b6ae](https://github.com/tkabala/brzask/commit/c13b6ae46a763d71aa0f5d1653dfa33b59944ab3))

## [0.1.5](https://github.com/tkabala/brzask/compare/v0.1.4...v0.1.5) (2026-10-26)


### Bug Fixes

* **discovery:** judge a feed whose items carry no dates ([4ffbc0f](https://github.com/tkabala/brzask/commit/4ffbc0fc4285a0de6ab5a4195817abcc72a519d4))
* **extractors:** count a crawl4ai anti-bot refusal as blocked ([fa45ac1](https://github.com/tkabala/brzask/commit/fa45ac16b68ec5f694d33ed35db1abbc3952123a))
* **feeds:** follow a feed that moved permanently ([60a23e0](https://github.com/tkabala/brzask/commit/60a23e07db822fb49db102eb590b5814bed849f5))
* **selection:** match a picked link whose query the model dropped ([5a76c35](https://github.com/tkabala/brzask/commit/5a76c35905543f6401530dbc4f97bf65ca248bf0))

## [0.1.4](https://github.com/tkabala/brzask/compare/v0.1.3...v0.1.4) (2026-10-24)


### Bug Fixes

* **feeds:** log the error response a feed fetch failed on ([6cb1719](https://github.com/tkabala/brzask/commit/6cb171935f67a145a4935ad53a87b40a2853e9c9))

## [0.1.3](https://github.com/tkabala/brzask/compare/v0.1.2...v0.1.3) (2026-10-22)


### Bug Fixes

* **sources:** treat feed URLs that differ only in case as one feed ([7f81335](https://github.com/tkabala/brzask/commit/7f81335efb0e9632034c72f24fac999f541623e0))

## [0.1.2](https://github.com/tkabala/brzask/compare/v0.1.1...v0.1.2) (2026-10-22)


### Bug Fixes

* **dedup:** let the judge decide same-site pairs above the zone ([e0b8b40](https://github.com/tkabala/brzask/commit/e0b8b40a83be84c01dd141029a27d0f48850bf36))
* **extraction:** start the article text at its headline ([2eeaefe](https://github.com/tkabala/brzask/commit/2eeaefe9f5b0f3f21dcb37b55f3a149295e159f3))

## [0.1.1](https://github.com/tkabala/brzask/compare/v0.1.0...v0.1.1) (2026-10-21)


### Bug Fixes

* **api:** answer 405 for API routes asked with another method ([623a1bf](https://github.com/tkabala/brzask/commit/623a1bf023a869b6aaa5a89b37a3d57bcce07aa1))
* **cli:** hand the secrets back to the host user when setup is interrupted ([362deb5](https://github.com/tkabala/brzask/commit/362deb534f1cbccee69e47645741a7e0d8d73559))
* **deploy:** let setup write to the BRZASK_SECRETS directory ([797d8de](https://github.com/tkabala/brzask/commit/797d8de8761dcbdd61e05059f1ce109dd383fa6e))
* **deploy:** pin the API address and port inside the containers ([1349937](https://github.com/tkabala/brzask/commit/1349937ca425b998e25fbbaa5a800a28f4a164cd))
* **deploy:** secret files win over the same variables in .env ([9c2eb3b](https://github.com/tkabala/brzask/commit/9c2eb3b86cec99d943c2e54761279bb7d1a041a8))

## 0.1.0 (2026-10-21)


### Features

* **api:** digests, search, sources, interests, runs, status and pause ([541887d](https://github.com/tkabala/brzask/commit/541887ded6cb8dafadeed3ee838ca77e967afcb6))
* **api:** record opens through /open redirects ([6309707](https://github.com/tkabala/brzask/commit/6309707b0124cc42e31a0acfff1d8ae09f4b1157))
* **api:** serve the HTTP API with problem details, cursors and probes ([ab5c133](https://github.com/tkabala/brzask/commit/ab5c1331a030e6da2c31bcd5c48a1e014951f931))
* **auth:** API tokens with read and write scopes ([01af217](https://github.com/tkabala/brzask/commit/01af2176a57719bbce6bd5a2f2d929a9b032957c))
* **auth:** log in with a password, with sessions, CSRF and throttling ([ba66d46](https://github.com/tkabala/brzask/commit/ba66d463a1fc8e6ab8fecc33453c51be5d812e99))
* **auth:** trust the user header from TRUSTED_PROXIES only ([aac66bb](https://github.com/tkabala/brzask/commit/aac66bbff0271de6db4cda1039368c1c897f549d))
* **cli:** add run, status, sources, interests, pause and resume commands ([33cd713](https://github.com/tkabala/brzask/commit/33cd713776611e6d49599ba4f6851c17e4e31c2c))
* **config:** add settings read from environment variables ([b1bc804](https://github.com/tkabala/brzask/commit/b1bc8044530fba041c4788e30e4c4143f5a7b28d))
* **db:** add database models ([39ce0b4](https://github.com/tkabala/brzask/commit/39ce0b458c9c38127b979df0b2ba38738674f005))
* **db:** add migrations and the migrate command ([b053741](https://github.com/tkabala/brzask/commit/b05374150944a32d65c6f4dfe770e29cbd80c66f))
* **db:** add repositories for every aggregate ([587a422](https://github.com/tkabala/brzask/commit/587a422816031bdf2051ff73239404b49f67df1e))
* **dedup:** judge the grey zone by default ([a254ce7](https://github.com/tkabala/brzask/commit/a254ce7462d628ea891d5ee4dc99fc74208ec459))
* **dedup:** let a judge decide same-day pairs in the grey zone ([112c2c2](https://github.com/tkabala/brzask/commit/112c2c2f807b0180d30f48750b975a51d37ec8c1))
* **demo:** a month of invented data shared by seed-demo, stories and tests ([59292bd](https://github.com/tkabala/brzask/commit/59292bd0a540b725da9dd17d3aa855f305a68e0b))
* **deploy:** compose file with setup, healthchecks and optional services ([35e2ebe](https://github.com/tkabala/brzask/commit/35e2ebe53c5c52db56be2787f8b1076486d33e8b))
* **digest:** build the candidate pool from fresh entries and carry-over ([a782bf3](https://github.com/tkabala/brzask/commit/a782bf3840cd88da56d4da2e743fbfc0d24ab3dc))
* **digest:** drop repeats of shown articles and same-day duplicates by embedding ([e43ceae](https://github.com/tkabala/brzask/commit/e43ceae13f41743c83f46eb720b23e948cd044f1))
* **digest:** extract and embed the top of the ranking ([ae570b1](https://github.com/tkabala/brzask/commit/ae570b10ae336b8a784d24afb0e7edf62d490043))
* **digest:** rank the pool with the LLM and keep the top 15, at most two per source ([cbafeb9](https://github.com/tkabala/brzask/commit/cbafeb965dd9f1feeee60e5f9045a0e686f2aa61))
* **digest:** select the day's 7 and run the digest pipeline ([7a2b47a](https://github.com/tkabala/brzask/commit/7a2b47acb215eab4eae39585c56fa02375cb7598))
* **discovery:** find new sources by web search per interest and an LLM judge ([38ab657](https://github.com/tkabala/brzask/commit/38ab65734dd4b403e0d451d6f0e440b9ed7199ff))
* **discovery:** vet feeds with the judge instead of a 0-10 prompt ([1d2b634](https://github.com/tkabala/brzask/commit/1d2b634115d7d8cfb4c00b6b9051601be3e7c496))
* **embeddings:** add an embedder with per-model query/document handling ([d147ae8](https://github.com/tkabala/brzask/commit/d147ae86e811408a5cd5163927fa7dc159497bd1))
* **embeddings:** move stored vectors to another model with reembed ([0cd9d47](https://github.com/tkabala/brzask/commit/0cd9d4792a7d9c10c3767063c82b40d90fc3e81b))
* **extract-bench:** compare extractors on a sample of stored links ([32d48f9](https://github.com/tkabala/brzask/commit/32d48f92131a3326497806bf99a5f6913bc6e6ff))
* **extraction:** add the extractor chain with robots.txt and site rules ([e50c725](https://github.com/tkabala/brzask/commit/e50c72535129b5a39c7d41e61473cc80a77aca80))
* **extractors:** send a Crawl4AI API token ([8fbcd4f](https://github.com/tkabala/brzask/commit/8fbcd4fa200b4bfaefb80d82d0840ce1e78235c6))
* **feeds:** fetch RSS and Atom feeds in parallel with conditional GET ([b0d8208](https://github.com/tkabala/brzask/commit/b0d820818835ded7adef50cb5a2ef5fc33b168b1))
* **feeds:** find a site's feed from any of its pages ([2d90b21](https://github.com/tkabala/brzask/commit/2d90b21d3c55d0f06f88e4950fd44e3b942ceb5c))
* **frontend:** app shell with generated client, login and i18n ([30361ce](https://github.com/tkabala/brzask/commit/30361ce5b49dcbf48eac9a4227157e78ded71580))
* **frontend:** demo API with MSW for Storybook and tests ([23d5a24](https://github.com/tkabala/brzask/commit/23d5a24ea0199e7e0994bcd43c21454d262b1e8e))
* **frontend:** screens for the digest, archive, search, sources, interests and status ([dc90976](https://github.com/tkabala/brzask/commit/dc90976fd1c9e7c742ecfd883395b4782118fd6c))
* **judge:** judge-bench compares judges on what the reader opened ([cbf914f](https://github.com/tkabala/brzask/commit/cbf914fa48eae4e5dd87680beaecf1107d3f7fd3))
* **judge:** typed judgements through System One or a chat model ([c83700d](https://github.com/tkabala/brzask/commit/c83700d135a95f330384d4685104bf7b6b8edbe7))
* **llm:** add an OpenAI-compatible LLM client with retries and usage accounting ([8d2d84a](https://github.com/tkabala/brzask/commit/8d2d84a052f401128ac95803c78516bf0f6bed93))
* **log:** add structured logging with request and run IDs ([521f97b](https://github.com/tkabala/brzask/commit/521f97bc9ce805f98e3ce67ab430382739254292))
* **prompts:** keep prompts as Jinja templates loaded by name ([28eb406](https://github.com/tkabala/brzask/commit/28eb406ed7e074810bcd27c4357c61d8a2aca2fb))
* **ranking:** rank the pool by a composite of judged scores ([b05a011](https://github.com/tkabala/brzask/commit/b05a011c51f361b6ecc18616a33a4418fe6f145a))
* **replay:** choose past digests again and score the picks by opens ([ee75fa3](https://github.com/tkabala/brzask/commit/ee75fa37b66067159d83e12dea9b63351a5db296))
* **review:** mute ignored sources and mark failing feeds dead ([486ccdc](https://github.com/tkabala/brzask/commit/486ccdcb70053396ab6f388ea028a026b0f3a35b))
* **search:** add web search over SearXNG, Brave or an online LLM ([1bede1a](https://github.com/tkabala/brzask/commit/1bede1af84a842bb1f9f34db7fac667cf0b2735f))
* **services:** add source, interest, pause, status and run services ([265a090](https://github.com/tkabala/brzask/commit/265a0903d3590f362775a7bd52b7220db09eea4c))
* **sources:** record fetch health and tell temporary feed errors from permanent ones ([3163b3b](https://github.com/tkabala/brzask/commit/3163b3b7ebaa111e0b29dee3bfb4863e8308fc26))
* **sources:** survival stats of added sources by origin and search adapter ([1625fa4](https://github.com/tkabala/brzask/commit/1625fa409e582a213699a4bb8ee061b5d4c21b88))
* **telemetry:** add OpenTelemetry traces and metrics, and Sentry error reports ([a2501ab](https://github.com/tkabala/brzask/commit/a2501abc7e9ed8b545a7b75ffd6c29b2a1311883))
* **visited:** propose sources for sites reached through opened links ([fce3502](https://github.com/tkabala/brzask/commit/fce3502293aac1c8bec22ecded8595ebe30e0f32))
* **weights:** fit composite weights to opens and keep the hand-set ones ([3da9b61](https://github.com/tkabala/brzask/commit/3da9b61225de72ad6f5c7a1de1b85367f84141a0))
* **worker:** run the pipelines on their schedule, one run per pipeline at a time ([35b0c4f](https://github.com/tkabala/brzask/commit/35b0c4fc7959c08bb296497ac1b62a63bf557bf1))


### Bug Fixes

* **api:** check the login in a transaction of its own ([18f1866](https://github.com/tkabala/brzask/commit/18f18660a475d2797e480a974b6e0d2015f54342))
* **api:** commit a route's transaction before its response is sent ([e7d6619](https://github.com/tkabala/brzask/commit/e7d6619e002f7e318d43546e90d16599a968293f))
* **api:** count parallel wrong passwords against the login limit ([22ccd1a](https://github.com/tkabala/brzask/commit/22ccd1a23e65252fa9e98750cbaba2ffbd15f7a0))
* **api:** keep openapi.json stable when the release bumps its version ([b598c2e](https://github.com/tkabala/brzask/commit/b598c2ee14ddacfde7d3845651fb2847fe8a05c1))
* **articles:** insert new articles in batches below the bind parameter limit ([803cf5e](https://github.com/tkabala/brzask/commit/803cf5e71d9c5b952123c25cc614d5a1868c54ac))
* **auth:** ignore a proxy's own Authorization; drop the CSRF cookie ([6e9fa97](https://github.com/tkabala/brzask/commit/6e9fa97e44ec8389f94b4d165e02528ea4fab25a))
* **auth:** mark the session cookie Secure only for HTTPS logins ([603c9b0](https://github.com/tkabala/brzask/commit/603c9b088311721a233de0ae805da79cefb9cb1f))
* **clients:** survive malformed URLs, meta-tag charsets and flaky robots.txt ([c13b4c8](https://github.com/tkabala/brzask/commit/c13b4c83e0d9d0e4a48215990eaaf8ff0d65d616))
* **cli:** report an invalid setting by its variable instead of a traceback ([c981587](https://github.com/tkabala/brzask/commit/c981587095c36af9b5034c0bd08abd1b7d1ac23c))
* **config:** drop the LLM budget settings until a limit is enforced ([ec69540](https://github.com/tkabala/brzask/commit/ec695404d7a47c106918c57733d2dca47b51ea3d))
* **config:** let a secret file win over an empty variable and build the database URL with SQLAlchemy ([630f876](https://github.com/tkabala/brzask/commit/630f87604715dca2ae274fcddadae7653297b7b3))
* **dedup:** spend the survivor floor on the closest duplicates first ([d9e77b8](https://github.com/tkabala/brzask/commit/d9e77b8f4bff6e295bfb945e90e29993f37718c0))
* **deps:** update certifi; drop pip from the image ([18a5e04](https://github.com/tkabala/brzask/commit/18a5e0436de89a280d1e41020e15555c53c47527))
* **digest:** name the project in titles of release notes ([58bb2d1](https://github.com/tkabala/brzask/commit/58bb2d1c0aacd187a08a814b57794b498273d156))
* **discovery:** close the web search client after a run ([e61e0f7](https://github.com/tkabala/brzask/commit/e61e0f72ea27367e2cbd0b90039bb6c328cc4393))
* **discovery:** fail the run when the judge gives no verdict at all ([5fe5ab0](https://github.com/tkabala/brzask/commit/5fe5ab03e42c0850bc0f2c9aa8c70c13f1a332c0))
* **embeddings:** send gemini-embedding-001 without a task type ([3fe207f](https://github.com/tkabala/brzask/commit/3fe207fd6fc987f928dcb07e9570bae0b8e2e5b6))
* **feeds:** count a 404 from YouTube's feed endpoint as temporary ([e633f5c](https://github.com/tkabala/brzask/commit/e633f5cf5c461a9ba877f44942c83bb7b37d8e9b))
* **feeds:** do not take a post's comment feed for the site's feed ([6973206](https://github.com/tkabala/brzask/commit/69732061139e495414e317d37a393cd7a49ad6b5))
* **frontend:** mark an article opened on a middle click only ([464b78a](https://github.com/tkabala/brzask/commit/464b78aa20f0e946671bab5a252005e18089543b))
* **frontend:** offer only future pause days; keep a mistyped archive day ([bcbd2bc](https://github.com/tkabala/brzask/commit/bcbd2bc559e0300b75faa8434504db2649f2b15c))
* **interests:** make topics unique ignoring case and reject numeric topics ([13e4bf5](https://github.com/tkabala/brzask/commit/13e4bf5db6b6f656da6144774af71a4ba8f90ce7))
* **judge-bench:** keep scoring past a failed day and ask LLM_MODEL where it is served ([f7bb440](https://github.com/tkabala/brzask/commit/f7bb440558ce999ef0896ee2347930ba73268355))
* **just:** quote migration messages, keep .env.example on generator errors, sync with the lockfile ([d7b6f14](https://github.com/tkabala/brzask/commit/d7b6f14d88e13a833d86ec608260fca4473307c3))
* **log:** reject request IDs with a trailing newline ([1247643](https://github.com/tkabala/brzask/commit/1247643bf4ef752220cae19accbaf73ff04c5d68))
* quiet the httpx2 request logs and ignore blank source names ([b06f2ed](https://github.com/tkabala/brzask/commit/b06f2ed15cf3eabfb04c1d50c3edac348c57ad03))
* **ranking:** let the LLM rank when the judge answers for no candidate ([b9e1f62](https://github.com/tkabala/brzask/commit/b9e1f6223483a402204da9de14aaf41450882a99))
* **reembed:** count missing vectors once and say to update EMBEDDING_MODEL ([9116e7d](https://github.com/tkabala/brzask/commit/9116e7d02784ac4bcd84be9c8655d0e64ad5397b))
* **replay:** rebuild pools up to the run's end and compare with its own picks ([afa4ff4](https://github.com/tkabala/brzask/commit/afa4ff440366e5bfaa9ba44efaec533e72eceb79))
* **review:** count a feed's failures from the first failed fetch to the last ([2a9efa1](https://github.com/tkabala/brzask/commit/2a9efa1b967def820dc676bbbb40416bb84a0bf9))
* **runs:** close interrupted runs and log run IDs as stored ([2f2080f](https://github.com/tkabala/brzask/commit/2f2080f23b40f0576a860e5398af8371ab51b6db))
* **runs:** do not fail a finished run when the lock connection is lost ([e9de77c](https://github.com/tkabala/brzask/commit/e9de77c025183ec20280c9ffea54687447af7208))
* **services:** report known URLs first and treat out-of-range IDs as not found ([c3f70cb](https://github.com/tkabala/brzask/commit/c3f70cb4f6b325850b3a9fae439f2fc03fe0470d))
* **sources:** make names unique ignoring case and name release feeds by project ([2f786f2](https://github.com/tkabala/brzask/commit/2f786f2598a241092a22d648ddd7689ed6854a65))
* **sources:** name sources sensibly from blank or numeric titles and report name conflicts from concurrent adds ([07c51d6](https://github.com/tkabala/brzask/commit/07c51d6d25e6f10b37cf2a1783b37bfcaf4e46d2))
* **visited:** propose GitHub repositories and YouTube channels behind opened links ([9baee74](https://github.com/tkabala/brzask/commit/9baee7435baf901084be6904b4b1566ccb95fd8a))
* **worker:** stop without deadlocking when a signal arrives as a job starts ([ef485ca](https://github.com/tkabala/brzask/commit/ef485ca825aff52f03e5c773558311d632be714c))


### Performance

* **digest:** normalize shown embeddings once per cross-day check ([5990199](https://github.com/tkabala/brzask/commit/5990199210388e69927486073c18e46e27880a0e))
* **search:** load the sources of similar articles in the same query ([9a64532](https://github.com/tkabala/brzask/commit/9a64532ad62332656c183c5420d4fca1004159f5))
* **sources:** count recent articles only for the sources shown ([4c1dfb7](https://github.com/tkabala/brzask/commit/4c1dfb79d5c92cd6b8486a19e0df65fbfb44e343))


### Documentation

* add documentation site skeleton and first ADR ([df4af4f](https://github.com/tkabala/brzask/commit/df4af4fe4476d7deb7b43ff517d3a24efc92ca18))
* ADRs for the core ideas and the stack ([b4a6296](https://github.com/tkabala/brzask/commit/b4a629690611a46ed38c1b6b088b572995861dfa))
* **articles:** count the state default among the insert parameters ([9bb0430](https://github.com/tkabala/brzask/commit/9bb04309658b9c93a0c2c02b04e172e49ac0b799))
* **decisions:** LLM ranking stays the default over composite scores ([ad7de52](https://github.com/tkabala/brzask/commit/ad7de523fe79fc91a39715b1a3ff35dea7ec6bf8))
* **decisions:** no vector index until the history needs one ([47ea2a9](https://github.com/tkabala/brzask/commit/47ea2a97c4053e1e7354426d53a2fc0c8fd63386))
* **decisions:** System One judgements over one HTTP client ([cf98e0e](https://github.com/tkabala/brzask/commit/cf98e0e79c495ec0564c4242ed16e56ac6cdbe31))
* documentation site on GitHub Pages ([2f384f0](https://github.com/tkabala/brzask/commit/2f384f05b7ea8105d81b41d89e3103d1344afaee))
* **measuring:** judge_model applies to every method set to judge ([c05299b](https://github.com/tkabala/brzask/commit/c05299bb1dfbdda8c31e7ec14059f71f4c2e3f9a))
* point the home page at the quickstart ([136a449](https://github.com/tkabala/brzask/commit/136a44965d5948b5a460534c7c0c29cd0e24c733))
* point to the packageManager field for the pnpm version ([65ec9f3](https://github.com/tkabala/brzask/commit/65ec9f39f2635bae1fed4bae38783c355db09c8e))
* README with screenshot, demo, pipeline, quickstart and decisions ([935331b](https://github.com/tkabala/brzask/commit/935331bb394a71a9e0d5a6a0912f1568da059d67))
* **replay:** baseline measured again with pools up to each run's end ([7e5be63](https://github.com/tkabala/brzask/commit/7e5be6375fa1d7a5b5ea8ae37b20480ce39f7109))
* **worker:** say that a worker started late does not catch up on missed runs ([2175bc2](https://github.com/tkabala/brzask/commit/2175bc2c17ce365e1f41478016c56c824aaafce1))
