{#
What discovery searches the web for, for one interest. An online LLM gets a
request in plain language; a search engine (SearXNG, Brave) gets keywords.
Reader notes are left out: "skip: ..." cannot be searched for.

Context:
  topic          str
  keywords       [str]
  conversational bool   true for an online LLM
#}
{% if conversational %}
Currently active, high-quality blogs, news sites and newsletters for staying up to date on {{ topic }}{% if keywords %} ({{ keywords | join(", ") }}){% endif %}, plus 2-3 active YouTube channels and 2-3 actively maintained GitHub repositories if relevant ones exist. Give homepage, channel or repository URLs, not single articles or videos, and no aggregators or listicles.
{% else %}
{{ topic }}{% if keywords %} {{ keywords | join(" ") }}{% endif %} blog
{% endif %}
