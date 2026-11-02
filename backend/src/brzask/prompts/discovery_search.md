{#
What discovery searches the web for, for one interest. An online LLM gets a
request in plain language; a search engine (SearXNG, Brave) gets keywords.
Reader notes are left out: "skip: ..." cannot be searched for.
GitHub repositories are not asked for (a repository the search returns anyway is
still followed through its release notes). Over one instance's runs, release
notes were opened for 3 of 102 shown items against 57 of 675 for articles, and
searches asked for repositories returned mostly ones without a release in 60
days: 16 of 18 asked for "actively maintained" ones, 14 of 19 asked for tools
that publish releases (the word pulled in release-note generators), and asking
for official tool repositories filled half the results with personal dotfiles
and course projects, crowding out blogs.

Context:
  topic          str
  keywords       [str]
  conversational bool   true for an online LLM
#}
{% if conversational %}
Currently active, high-quality blogs, news sites and newsletters for staying up to date on {{ topic }}{% if keywords %} ({{ keywords | join(", ") }}){% endif %}, plus 2-3 active YouTube channels. Give homepage or channel URLs, not single articles or videos, and no aggregators or listicles.
{% else %}
{{ topic }}{% if keywords %} {{ keywords | join(" ") }}{% endif %} blog
{% endif %}
