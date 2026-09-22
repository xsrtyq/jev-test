# Contributing

This repository is an independent research harness, not a production Jev integration.

Useful contributions include:
- reproducible baselines against deterministic retrieval, embeddings, small/local models, or vendor-native context features;
- held-out long-agent or coding-continuation tasks;
- cache/cost accounting improvements;
- audits of methodology, leakage, correlated samples, censoring, or pricing assumptions;
- protocol adapters for compatible decision-model backends.

Please keep these rules:

1. Do not commit API keys, private customer code, personal data, or proprietary traces.
2. Separate authored/synthetic fixtures from independent or production-derived evidence.
3. State sample size, model/backend identity, pricing snapshot date, and whether upstream identity is independently verified.
4. Do not convert censored/failed calls into successful outcomes.
5. Preserve negative results and known methodological flaws.
6. Any paid workflow must remain manual and bounded.
7. A semantic score must not become permission to delete evidence or authorize high-impact actions.

Before submitting a change, run:

~~~bash
python -m unittest discover -s tests -v
~~~

For benchmark changes, include a short note describing the hypothesis, baseline, success metric, and stop condition.
