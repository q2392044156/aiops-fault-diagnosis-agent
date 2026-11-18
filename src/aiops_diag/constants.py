"""跨层共享的稳定取值：受控工具白名单及其预算裁剪顺序。"""

# `ROUTER_TOOLS` 是路由器与评测共同认可的工具集合，顺序即超预算时的保留顺序。
ROUTER_TOOLS: tuple[str, ...] = ("query_metrics", "search_similar_incidents")
