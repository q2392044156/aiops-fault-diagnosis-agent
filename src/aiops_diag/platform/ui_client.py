"""模块说明：封装 Streamlit 调用 FastAPI 的客户端。"""

from pathlib import Path

import httpx


# 类说明：`ApiClient` 封装本模块内聚的数据和行为。
class ApiClient:
    # 方法说明：`__init__` 完成当前步骤的业务处理；参数为 `base_url`、`timeout`、`transport`。
    def __init__(self, base_url, timeout=30.0, transport=None):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout, transport=transport,
                                   trust_env=False)

    # 方法说明：`_value` 完成当前步骤的业务处理；参数为 `response`。
    @staticmethod
    def _value(response):
        response.raise_for_status()
        return response.json()

    # 方法说明：`health` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def health(self):
        return self._value(self.client.get("/api/v1/health/ready"))

    # 方法说明：`release` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def release(self):
        return self._value(self.client.get("/api/v1/releases/current"))

    # 方法说明：`operations` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def operations(self):
        return self._value(self.client.get("/api/v1/operations/summary"))

    # 方法说明：`upload` 完成当前步骤的业务处理；参数为 `name`、`content`、`content_type`、`idempotency_key`。
    def upload(self, name, content, content_type="text/plain", idempotency_key=None):
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._value(self.client.post(
            "/api/v1/batches/uploads", files={"file": (Path(name).name, content, content_type)},
            headers=headers,
        ))

    # 方法说明：`registered` 完成当前步骤的业务处理；参数为 `registered_id`、`idempotency_key`。
    def registered(self, registered_id, idempotency_key=None):
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._value(self.client.post(
            "/api/v1/batches/registered", json={"registered_id": registered_id}, headers=headers,
        ))

    # 方法说明：`registered_options` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def registered_options(self):
        return self._value(self.client.get("/api/v1/batches/registered"))["items"]

    # 方法说明：`task` 完成当前步骤的业务处理；参数为 `task_id`。
    def task(self, task_id):
        return self._value(self.client.get(f"/api/v1/tasks/{task_id}"))

    # 方法说明：`events` 完成当前步骤的业务处理；参数为 `batch_id`、`limit`、`cursor`。
    def events(self, batch_id=None, limit=50, cursor=None):
        params = {"limit": limit}
        if batch_id:
            params["batch_id"] = batch_id
        if cursor:
            params["cursor"] = cursor
        return self._value(self.client.get("/api/v1/events", params=params))

    # 方法说明：`event` 完成当前步骤的业务处理；参数为 `event_id`。
    def event(self, event_id):
        return self._value(self.client.get(f"/api/v1/events/{event_id}"))

    # 方法说明：`logs` 完成当前步骤的业务处理；参数为 `batch_id`、`session_id`、`limit`、`cursor`。
    def logs(self, batch_id, session_id, limit=100, cursor=None):
        params = {"session_id": session_id, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._value(self.client.get(f"/api/v1/batches/{batch_id}/logs", params=params))

    # 方法说明：`knowledge_release` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def knowledge_release(self):
        return self._value(self.client.get("/api/v1/knowledge/releases/current"))

    # 方法说明：`retrieve` 完成当前步骤的业务处理；参数为 `query`、`top_k`、`mode`、`component`、`product_version`。
    def retrieve(self, query, top_k=None, mode="frozen", component=None, product_version=None):
        payload = {"query": query, "mode": mode, "top_k": top_k,
                   "component": component, "product_version": product_version}
        return self._value(self.client.post("/api/v1/retrieval/search", json=payload))

    # 方法说明：`knowledge_chunk` 完成当前步骤的业务处理；参数为 `chunk_id`。
    def knowledge_chunk(self, chunk_id):
        return self._value(self.client.get(f"/api/v1/knowledge/chunks/{chunk_id}"))

    # 方法说明：`rag_release` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def rag_release(self):
        return self._value(self.client.get("/api/v1/rag/releases/current"))

    # 方法说明：`create_report` 完成当前步骤的业务处理；参数为 `query`、`mode`、`component`、`product_version`、`idempotency_key`。
    def create_report(self, query, mode="auto", component=None, product_version=None,
                      idempotency_key=None):
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._value(self.client.post(
            "/api/v1/rag/reports",
            json={"query": query, "mode": mode, "component": component,
                  "product_version": product_version}, headers=headers,
        ))

    # 方法说明：`report` 完成当前步骤的业务处理；参数为 `report_id`。
    def report(self, report_id):
        return self._value(self.client.get(f"/api/v1/rag/reports/{report_id}"))

    # 方法说明：`agent_release` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def agent_release(self):
        return self._value(self.client.get("/api/v1/agent/releases/current"))

    # 方法说明：`create_diagnosis` 完成当前步骤的业务处理；参数为 `event_id`、`mode`、`idempotency_key`。
    def create_diagnosis(self, event_id, mode="auto", idempotency_key=None):
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        return self._value(self.client.post(
            "/api/v1/diagnoses", json={"event_id": event_id, "mode": mode}, headers=headers))

    # 方法说明：`diagnosis` 完成当前步骤的业务处理；参数为 `diagnosis_id`。
    def diagnosis(self, diagnosis_id):
        return self._value(self.client.get(f"/api/v1/diagnoses/{diagnosis_id}"))

    # 方法说明：`diagnosis_tools` 完成当前步骤的业务处理；参数为 `diagnosis_id`。
    def diagnosis_tools(self, diagnosis_id):
        return self._value(self.client.get(f"/api/v1/diagnoses/{diagnosis_id}/tool-calls"))

    # 方法说明：trace 读取一次诊断的调用瀑布（span 列表）。
    def trace(self, diagnosis_id):
        return self._value(self.client.get(f"/api/v1/diagnoses/{diagnosis_id}/trace"))

    # 方法说明：`incident_report` 完成当前步骤的业务处理；参数为 `report_id`。
    def incident_report(self, report_id):
        return self._value(self.client.get(f"/api/v1/reports/{report_id}"))

    # 方法说明：`approvals` 完成当前步骤的业务处理；参数为 `status`。
    def approvals(self, status="PENDING"):
        return self._value(self.client.get("/api/v1/approvals", params={"status": status}))

    # 方法说明：`approval` 完成当前步骤的业务处理；参数为 `approval_id`。
    def approval(self, approval_id):
        return self._value(self.client.get(f"/api/v1/approvals/{approval_id}"))

    # 方法说明：`decide_approval` 完成当前步骤的业务处理；参数为 `approval_id`、`decision`、`report_hash`、`revision`、`reason`、`reviewer_token`、`idempotency_key`。
    def decide_approval(self, approval_id, decision, report_hash, revision, reason,
                        reviewer_token, idempotency_key):
        return self._value(self.client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": decision, "report_hash": report_hash,
                  "revision": revision, "reason": reason},
            headers={"Authorization": f"Bearer {reviewer_token}",
                     "Idempotency-Key": idempotency_key},
        ))

    # 方法说明：`close` 完成当前步骤的业务处理；参数为 无显式业务参数。
    def close(self):
        self.client.close()

