from pathlib import Path

import httpx


class ApiClient:
    def __init__(self, base_url, timeout=30.0, transport=None):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport,
                                   trust_env=False)

    @staticmethod
    def _value(response):
        response.raise_for_status()
        return response.json()

    def health(self):
        return self._value(self.client.get("/api/v1/health/ready"))

    def release(self):
        return self._value(self.client.get("/api/v1/releases/current"))

    def operations(self):
        return self._value(self.client.get("/api/v1/operations/summary"))

    def upload(self, name, content, content_type="text/plain", idempotency_key=None):
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._value(self.client.post(
            "/api/v1/batches/uploads", files={"file": (Path(name).name, content, content_type)},
            headers=headers,
        ))

    def registered(self, registered_id, idempotency_key=None):
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._value(self.client.post(
            "/api/v1/batches/registered", json={"registered_id": registered_id}, headers=headers,
        ))

    def registered_options(self):
        return self._value(self.client.get("/api/v1/batches/registered"))["items"]

    def task(self, task_id):
        return self._value(self.client.get(f"/api/v1/tasks/{task_id}"))

    def events(self, batch_id=None, limit=50, cursor=None):
        params = {"limit": limit}
        if batch_id:
            params["batch_id"] = batch_id
        if cursor:
            params["cursor"] = cursor
        return self._value(self.client.get("/api/v1/events", params=params))

    def event(self, event_id):
        return self._value(self.client.get(f"/api/v1/events/{event_id}"))

    def logs(self, batch_id, session_id, limit=100, cursor=None):
        params = {"session_id": session_id, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._value(self.client.get(f"/api/v1/batches/{batch_id}/logs", params=params))

    def knowledge_release(self):
        return self._value(self.client.get("/api/v1/knowledge/releases/current"))

    def retrieve(self, query, top_k=None, mode="frozen", component=None, product_version=None):
        payload = {"query": query, "mode": mode, "top_k": top_k,
                   "component": component, "product_version": product_version}
        return self._value(self.client.post("/api/v1/retrieval/search", json=payload))

    def knowledge_chunk(self, chunk_id):
        return self._value(self.client.get(f"/api/v1/knowledge/chunks/{chunk_id}"))

    def close(self):
        self.client.close()

