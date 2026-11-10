from __future__ import annotations

import os


os.environ.setdefault("GOOGLE_API_KEY", "test-key")
# PgCheckpointer connects lazily, so these only need to be well-formed to import the graph.
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/agent")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
# The task broker (worker.tasks) also connects lazily; the URL only has to be set.
os.environ.setdefault("BROKER_URL", "amqp://guest:guest@localhost:5672/")
