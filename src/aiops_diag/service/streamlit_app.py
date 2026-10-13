import os
import time

import httpx
import streamlit as st

from aiops_diag.service.ui_client import ApiClient


st.set_page_config(page_title="AIOps 异常事件复核台", page_icon="🔎", layout="wide")
st.title("AIOps 异常事件复核台")
st.caption("W7 · 冻结异常检测 + 可追溯混合检索 · 只读证据浏览")

api_url = os.environ.get("AIOPS_API_URL", "http://127.0.0.1:8000")
public_api_url = os.environ.get("AIOPS_PUBLIC_API_URL", "http://127.0.0.1:8000").rstrip("/")
client = ApiClient(api_url, timeout=60)

try:
    health = client.health()
    release = client.release()
    operations = client.operations()
    st.success(f"服务就绪 · {release['deployment_release']} · {release['release_id']}")
    cols = st.columns(5)
    for column, label, value in zip(
        cols,
        ("排队", "运行", "成功", "失败", "Worker"),
        (operations["queued"], operations["running"], operations["succeeded"],
         operations["failed"], "正常" if operations["worker_ready"] else "异常"),
    ):
        column.metric(label, value)
except (httpx.HTTPError, KeyError) as exc:
    st.error(f"API 暂不可用：{exc}")
    st.stop()

tab_submit, tab_task, tab_events, tab_knowledge = st.tabs(
    ("提交日志", "任务状态", "异常事件", "知识检索"))

with tab_submit:
    upload = st.file_uploader("上传原始 HDFS 文本日志", type=("log", "txt"))
    idempotency = st.text_input("幂等键（可选，1–128个安全字符）")
    if st.button("提交上传", disabled=upload is None):
        try:
            result = client.upload(upload.name, upload.getvalue(), idempotency_key=idempotency or None)
            st.session_state["task_id"] = result["task_id"]
            st.session_state["batch_id"] = result["batch_id"]
            st.json(result)
        except httpx.HTTPStatusError as exc:
            st.error(exc.response.text)
    st.divider()
    registered_options = client.registered_options()
    registered_id = st.selectbox("登记批次", registered_options,
                                 disabled=not registered_options)
    if st.button("提交登记批次", disabled=not registered_options):
        try:
            result = client.registered(registered_id, idempotency or None)
            st.session_state["task_id"] = result["task_id"]
            st.session_state["batch_id"] = result["batch_id"]
            st.json(result)
        except httpx.HTTPStatusError as exc:
            st.error(exc.response.text)

with tab_task:
    task_id = st.text_input("任务 ID", value=st.session_state.get("task_id", ""))
    auto_refresh = st.checkbox("任务运行时每2秒自动刷新")
    if task_id:
        try:
            task = client.task(task_id)
            st.json(task)
            if auto_refresh and task["status"] in ("QUEUED", "RUNNING"):
                time.sleep(2)
                st.rerun()
        except httpx.HTTPStatusError as exc:
            st.error(exc.response.text)

with tab_events:
    batch_id = st.text_input("批次 ID", value=st.session_state.get("batch_id", ""))
    if batch_id and st.button("加载异常事件"):
        try:
            page = client.events(batch_id=batch_id)
            st.session_state["events"] = page["items"]
            st.session_state["event_cursor"] = page["next_cursor"]
        except httpx.HTTPStatusError as exc:
            st.error(exc.response.text)
    events = st.session_state.get("events", [])
    if not events:
        st.info("当前没有已加载的异常事件。")
    else:
        labels = {f"{item['event_id']} · {item['session_count']}会话 · "
                  f"分数{item['max_anomaly_score']:.3f}": item["event_id"] for item in events}
        selected = st.selectbox("选择事件", labels)
        detail = client.event(labels[selected])
        st.json(detail["event"])
        sessions = detail["sessions"]
        st.dataframe(sessions, use_container_width=True)
        if sessions:
            session_id = st.selectbox("查看会话脱敏日志",
                                      [row["session_id"] for row in sessions])
            logs = client.logs(detail["event"]["batch_id"], session_id, limit=200)
            st.dataframe(logs["items"], use_container_width=True)
        if st.session_state.get("event_cursor") and st.button("加载下一页事件"):
            page = client.events(batch_id=batch_id, cursor=st.session_state["event_cursor"])
            st.session_state["events"].extend(page["items"])
            st.session_state["event_cursor"] = page["next_cursor"]
            st.rerun()

with tab_knowledge:
    try:
        kb = client.knowledge_release()
        st.caption(f"知识版本 {kb['kb_release_id']} · {kb['default_mode']} · Top-{kb['default_k']}")
        query = st.text_area("输入HDFS或通用运维问题", max_chars=500)
        mode = st.selectbox("检索方式", ("frozen", "bm25", "dense", "hybrid"))
        top_k = st.select_slider("返回条数", options=(1, 2, 3, 4, 5, 6, 7, 8, 9, 10),
                                 value=kb["default_k"])
        if st.button("检索证据", disabled=not query.strip()):
            st.session_state["retrieval"] = client.retrieve(query.strip(), top_k, mode)
        result = st.session_state.get("retrieval")
        if result:
            if result["status"] == "insufficient_evidence":
                st.warning("当前知识库没有达到证据门禁的适用内容。")
            for item in result["items"]:
                with st.expander(f"#{item['rank']} {item['title']} · {item['section_path']}"):
                    st.write(item["excerpt"])
                    st.caption(f"BM25={item['bm25_score']:.4f} · Dense="
                               f"{item['dense_score']:.4f} · RRF={item['rrf_score']:.6f}")
                    st.markdown(f"[打开本地证据]({public_api_url}{item['evidence_url']})")
                    if item.get("source_url"):
                        st.markdown(f"[打开官方来源]({item['source_url']})")
    except httpx.HTTPError as exc:
        st.error(f"知识检索暂不可用：{exc}")

