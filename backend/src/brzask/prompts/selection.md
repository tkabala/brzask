{#
Pick the digest from the deduplicated top of the ranking and write it in the
digest language.

Context:
  interests    [{topic, keywords: [str], notes}]
  candidates   [{title, link, source, published, rank, text}]   best ranked first
  digest_size  int
  language     {name, fallback_topic}
#}
The reader's standing interests:
{% include "_interests.md" %}

From the candidates below (already ranked, best first, and deduplicated so one story appears once), select exactly {{ digest_size }} articles, or all of them if there are fewer.

Spread the selection across as many sources and subjects as the candidates allow: prefer at most one article per source, and never pick two articles about the same underlying story or announcement, even when they are worded differently. Take a second article from one source only when the alternative is clearly weaker.

Answer with only a JSON object, no code fences or commentary:
{"articles": [{"link": string, "title": string, "summary": string, "whyItMatters": string, "topic": string}]}

Rules:
- "link": copied exactly from the list below; never change or invent a URL.
- "title": the headline in {{ language.name }}, translated when it is in another language. Keep product names, company names and other proper nouns as they are.
- "summary": 2-3 sentences in {{ language.name }}.
- "whyItMatters": one sentence in {{ language.name }}, on why this reader should care.
- "topic": the interest topic above that best matches the article, copied exactly; if none fits, "{{ language.fallback_topic }}". The digest groups articles by this field, so choose consistently.

Candidates:
{% for candidate in candidates %}

{{ loop.index }}. [{{ candidate.title }}]({{ candidate.link }})
   Source: {{ candidate.source }}
   Published: {{ candidate.published or "unknown" }}
   Rank: {{ candidate.rank }}
{% if candidate.text %}
   {{ candidate.text }}
{% endif %}
{% endfor %}
