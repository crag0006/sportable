"""The Access Assistant (contract v0.3 section 8): one use case, ``AssistantService.ask``.

``prompt`` holds the system prompt, ``tools`` the eight read-only tools and
the ``final_answer`` output tool over the existing services, ``retrieval`` the
hybrid search and its acceptance rule, ``builder`` the response assembly
(links from tool results only, trace, sources, calendar proposal) and
``service`` the bounded tool loop. Nothing here imports FastAPI or the SDK.
"""
