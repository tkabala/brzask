# Changelog

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
