{#
What discovery searches the web for, for one interest. An online LLM gets a
request in plain language; a search engine (SearXNG, Brave) gets keywords.
Reader notes are left out: "skip: ..." cannot be searched for.
GitHub repositories are asked for by their releases: asked only for "actively
maintained" ones, one run over 9 interests proposed 16 repositories without a
release in 60 days (awesome-lists, roadmaps, interview notes) and 2 with.

Context:
  topic          str
  keywords       [str]
  conversational bool   true for an online LLM
#}
{% if conversational %}
Currently active, high-quality blogs, news sites and newsletters for staying up to date on {{ topic }}{% if keywords %} ({{ keywords | join(", ") }}){% endif %}, plus 2-3 active YouTube channels and 2-3 GitHub repositories of tools that publish releases, if relevant ones exist (only their release notes are followed, so no lists, tutorials or roadmaps). Give homepage, channel or repository URLs, not single articles or videos, and no aggregators or listicles.
{% else %}
{{ topic }}{% if keywords %} {{ keywords | join(" ") }}{% endif %} blog
{% endif %}
