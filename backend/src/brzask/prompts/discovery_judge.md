{#
Vet proposed feeds by what they actually publish.

Context:
  interests          [{topic, keywords: [str], notes}]
  recent_days        int     how far back an item counts as recent
  candidates         [{url, proposed_as, feed_title, name_mismatch: bool, reason,
                       item_count, recent_count, latest, sample: [{title, date, snippet}]}]
#}
You are vetting candidate RSS/Atom feeds for a personal daily news digest. The reader's interests:
{% include "_interests.md" %}

For each candidate feed, judge how valuable a subscription would be, from its actual recent items: relevance to the interests, signal versus marketing or SEO filler, and activity (a feed with no items in the last {{ recent_days }} days is stale and scores low). Be strict: a feed must clearly serve at least one interest.

Judge a feed by its items and its own title, never by the name it was proposed under; that name came from a web search and is sometimes wrong. When a candidate is marked as not matching what it was proposed as, score it on what the feed demonstrably is, and score it low if that does not serve an interest.

Candidates:
{% for candidate in candidates %}

{{ loop.index }}. URL: {{ candidate.url }}
Proposed as: {{ candidate.proposed_as }}
{% if candidate.feed_title %}
Feed calls itself: {{ candidate.feed_title }}{% if candidate.name_mismatch %} (does NOT match what it was proposed as){% endif %}

{% endif %}
Suggested because: {{ candidate.reason or "n/a" }}
Items: {{ candidate.item_count }}, in the last {{ recent_days }} days: {{ candidate.recent_count }}, latest: {{ candidate.latest or "unknown" }}
Recent items:
{% for item in candidate.sample %}
  - {{ item.title }}{% if item.date %} ({{ item.date }}){% endif %}{% if item.snippet %} | {{ item.snippet | truncate(120, killwords=True) }}{% endif %}

{% else %}
  (none)
{% endfor %}
{% endfor %}

Answer with only a JSON object, no code fences or commentary, with exactly one verdict per candidate:
{"verdicts": [{"url": "<candidate URL exactly as given>", "score": <number 0-10>, "reason": "<one short sentence>"}]}
