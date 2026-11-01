NOTE_PROMPT = """You are writing the incident note. The searches have already run.

Use at most eight short lines, in this order: Impact, Leading cause, Alternative, Confidence, Next checks, Safest mitigation.
One sentence each. Do not use headings or bullet lists. Do not write a tool call.
If a source says it was not checked, say that. If a fact is not in the brief or the search results, say it is unknown.
Do not invent metrics, stack traces, or customer impact.
"""
