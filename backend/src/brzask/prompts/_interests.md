{# Shared block: the reader's interests. Notes come after keywords and outrank them. #}
{% if interests %}
{% for interest in interests %}
- {{ interest.topic }}{% if interest.keywords %}: {{ interest.keywords | join(", ") }}{% endif %}{% if interest.notes %} [reader note: {{ interest.notes }}]{% endif %}

{% endfor %}
{% else %}
(no interests configured: fall back to general technology news)
{% endif %}
