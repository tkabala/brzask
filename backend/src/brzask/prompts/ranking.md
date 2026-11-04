{#
Rank candidates against each other instead of scoring each one: asked for
0-10 scores, models give most articles the same score (196 of 294 top
articles got exactly 8), so ties decided the outcome.

Ages: on an instance following news topics, undated candidates let a bomb
evacuation and a "pre-order today" post reach the digest 8 and 9 days late.
Replayed over 28 days of a mostly blog-and-release reader, the ages changed
nothing that was lost: 24 and 27 opened picks of 196, against 19 and 24
without them.

Context:
  interests       [{topic, keywords: [str], notes}]
  opened_titles   [str]                titles the reader opened recently, newest first
  opened_topics   [{name, count}]      most opened topics
  opened_sources  [{name, count}]      most opened sources
  candidates      [{id, source, title, snippet, release: bool, age: str | None}]
  rank_limit      int
#}
The reader's standing interests:
{% include "_interests.md" %}

A [reader note: ...] is the reader's own guidance for that topic and outranks its keywords: rank anything a note says to skip low, even when the keywords match.

Articles the reader opened from recent digests (a click is a positive signal; not opening an article is not evidence of dislike):
{% for title in opened_titles %}
- {{ title }}
{% else %}
(none yet)
{% endfor %}

Topics opened most:
{% for topic in opened_topics %}
- {{ topic.name }} ({{ topic.count }})
{% else %}
(none yet)
{% endfor %}

Sources opened most:
{% for source in opened_sources %}
- {{ source.name }} ({{ source.count }})
{% else %}
(none yet)
{% endfor %}

Below are {{ candidates | length }} candidate articles. Rank them by how much this reader would want to read them today. The interests are the primary signal; what the reader opens is a secondary one, a nudge between comparable candidates, never a filter that crowds out the other interests.

Candidates marked [RELEASE] are release notes. Judge them on substance, not on the fact that a version shipped: rank one high only if it brings a genuinely new feature or a change the reader would want to know about. Routine version bumps, dependency or security patches and small bugfix batches rank low, even when the project matches an interest.

Each candidate shows its age where the feed dates it. Age matters only for news tied to a date: results, schedules, launches or events announced for "today", and breaking local news lose most of their value within a day or two, and an old one ranks below a fresh one on the same subject. Essays, guides, research, recipes and other lasting pieces do not age that way: never rank them lower for age alone.

Return the ids of the best {{ rank_limit }} candidates in strict order, best first. Be decisive: no ties, and do not pad the list. Returning fewer than {{ rank_limit }} is right when the rest are not worth the reader's time. Use only ids from the list, each at most once.

Answer with only a JSON object, no code fences or commentary:
{"ranking": [id, id, ...]}

Candidates:
{% for candidate in candidates %}
{{ candidate.id }}. {% if candidate.release %}[RELEASE] {% endif %}[{{ candidate.source }}] {{ candidate.title }}{{ " (" ~ candidate.age ~ ")" if candidate.age else "" }}
{% if candidate.snippet %}
   {{ candidate.snippet | truncate(300, killwords=True) }}
{% endif %}
{% endfor %}
