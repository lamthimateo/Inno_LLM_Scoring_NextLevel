"""Execution drivers.

- ``file_runner``  — load saved model replies from ``imports/model_outputs/*.txt``
- ``api_runner``   — invoke provider adapters and collect ``ModelResult``s

The CLI picks one of these per subcommand (``run-file`` vs ``run-openai``).
"""
