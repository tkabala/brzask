{#
Answer typed questions about a piece of state, as probabilities.

Context:
  state       str     JSON of the state the questions are about
  questions   [{name, kind: noul|choice|score, instructions: str (JSON),
                criteria: str (JSON) | None, options: [str]}]
              options: choice option names, or score level numbers from 0
#}
You answer questions about the state below. Answer each question independently, from the state alone. Questions may refer to parts of the state by their path, such as `article.title`.

State:
{{ state }}

Questions:
{% for question in questions %}

"{{ question.name }}" ({{ question.kind }})
Instructions: {{ question.instructions }}
{% if question.kind == "noul" %}
{% if question.criteria %}
Criteria for true and false: {{ question.criteria }}
{% endif %}
Answer with the probability that the answer is yes (true), from 0 to 1.
{% elif question.kind == "choice" %}
Options (name: meaning): {{ question.criteria }}
Answer with a probability for each option ({{ question.options | join(", ") }}); they sum to 1.
{% else %}
Levels, from 0 upwards: {{ question.criteria }}
Answer with a probability for each level ({{ question.options | join(", ") }}); they sum to 1.
{% endif %}
{% endfor %}

Spread probability only when the state leaves the answer open; when it is clear, give the answer a probability close to 1.

Answer with only a JSON object, no code fences or commentary, with one entry per question:
{"answers": {"<question name>": {"probability": <0-1>} for noul, or {"probabilities": {"<option or level>": <0-1>, ...}} for choice and score}}
