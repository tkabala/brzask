# Deep dives

A deep dive is a report on one digest article, written when you ask for it:
the background that led to the article and the terms it assumes, steps you
could take in practice, and three to five things worth reading next. Every
claim names the sources it rests on, by number, and the report lists them.

## Asking for one

Under an article's brief, "Go deeper" takes an optional line saying what to
focus on ("for Proxmox", "does it work with local models") and starts the
report. It is written in the background, usually within one or two minutes;
"Deep dives" in the navigation counts the finished ones you have not opened,
and a notification says when one is ready (see [Notifications](notifications.md)).
A report that could not be written says why and can be tried again.

Only digest articles can be deep-dived, because a report starts from the
article's stored text. One report per article and focus is written at a time;
a different focus is a different report.

## What it reads

1. Its plan: one LLM call turns the article (and your focus) into up to six
   web searches and two searches of your archive.
2. Up to three earlier articles from your archive that match by meaning.
3. The first eight readable pages the web searches return, fetched like
   article pages (robots rules, the private-address guard and `FETCH_PROXY`
   apply). Without `WEB_SEARCH` the report uses the article and the archive
   only, and says so.
4. One more LLM call writes the report from those numbered sources.

Text from pages is treated as data: it cannot make brzask search or fetch
anything else, and every link in a report is one of its sources
([ADR 0026](decisions/0026-deep-dives-follow-a-fixed-pipeline-and-cite-only-gathered-sources.md)).
A command shown under "In practice" is quoted from the source next to it;
brzask never runs it, and you should read it before you do.

## What it costs

Measured on five real reports: about $0.04 each with `WEB_SEARCH=llm-online`
(the six searches are most of it; the two writing calls cost under a cent)
and 45-95 seconds. Reports count towards `LLM_BUDGET_DAILY_USD` and
`LLM_BUDGET_MONTHLY_USD`: a request over a limit is refused with the reason.

## Taking it elsewhere

A finished report has three buttons: **Share** (the system share sheet, on
phones), **Copy as Markdown** and **Download .md**. The Markdown keeps the
source numbers and lists the sources with their links, so it reads the same
in a notes app.
