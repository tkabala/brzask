{#
Web search through an LLM with web access.

Context:
  query  str
  limit  int
#}
Search the web for: {{ query }}

List up to {{ limit }} of the most relevant pages, one per line, as: Title - URL - one short sentence about the page. Only real, currently existing pages.
