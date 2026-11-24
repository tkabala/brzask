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

## Asking about an article

"Ask" on a brief or a report opens the article's conversation: one per
article, kept with it and continued whenever you come back. An empty one
offers three starters ("Explain it more simply", "What does this mean for
me?", "What are the weak points?"); every answer suggests up to three
follow-ups, and the field takes your own questions (up to 1,000 characters).

An answer comes from what brzask already stored: the article, its brief, its
deep dives and the sources found earlier in the conversation. It cites them by
number (tap a number for the title and link) and arrives whole, usually within
a few seconds and always within about 45. When the material does not answer
the question, the answer says what is missing, and "Search the web and the
archive" becomes the main button. Questions about the present (the latest
version, a price today) are answered as of the article.

A search runs only when you tap it: up to two web searches and one archive
search, five pages read, then the answer is written again with the new sources.
It takes 25-50 seconds; the page updates when it is done. When nothing new
turned up, or nothing new answered the question, the answer says so. Without
`WEB_SEARCH` the round searches the archive only.

Measured on a copy of real data: an answer costs $0.0002-0.0016, a search
round about $0.013 with `WEB_SEARCH=llm-online`. Conversations count towards
the same spending limits as reports; over a limit, asking is refused with the
reason. The conversation exports like a report (Share, Copy as Markdown,
Download .md), with the cited sources listed under their numbers. See
[ADR 0027](decisions/0027-a-conversation-answers-from-stored-material-and-searching-is-the-readers-action.md).
