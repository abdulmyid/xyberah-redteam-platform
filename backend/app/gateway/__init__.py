"""Xyberah AI Firewall: an LLM reverse proxy with guardrails, DLP, rate limiting,
response caching and a hash-chained JSON audit trail.

The detection engine (``detectors``, ``injection``, ``toxicity``, ``engine``) is pure
Python with no web dependencies, so the platform backend reuses it for the policy
playground and the gateway runs it in a process pool.
"""
