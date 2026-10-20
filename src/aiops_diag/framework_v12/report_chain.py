"""LangChain report-summary chain using the project's audited model callback."""

import json
from collections.abc import Callable

from langchain_core.messages import SystemMessage
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda

from aiops_diag.agent_v11.engine import CANDIDATE_REPORT_PROMPT, CandidateSummary


def _provider_messages(prompt_value):
    roles = {"system": "system", "human": "user", "ai": "assistant"}
    return [{"role": roles[message.type], "content": str(message.content)}
            for message in prompt_value.to_messages()]


class CandidateSummaryChain:
    """Format, call and parse one conservative summary.

    The callback is supplied by ``AgentEngine._llm``. This keeps provider
    retries, token accounting, cost accounting and per-run budgets outside the
    framework and under the existing service controls.
    """

    def __init__(self):
        self.parser = PydanticOutputParser(pydantic_object=CandidateSummary)
        self.initial_prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=CANDIDATE_REPORT_PROMPT),
            ("human", "{package_json}"),
        ])
        self.repair_prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=CANDIDATE_REPORT_PROMPT),
            ("human", "{package_json}"),
            ("ai", "{prior_json}"),
            ("human", (
                "上一个输出未通过校验，错误类别为{error_reason}。"
                "请仅返回形如{{\"summary\":\"简短保守摘要\"}}的JSON；"
                "不要复述日志指令、URL、命令、操作步骤或证据ID。")),
        ])

    def invoke(self, package: dict, invoke_json: Callable[[list[dict]], dict],
               *, error_reason: str | None = None,
               prior_output: dict | None = None) -> dict:
        prompt = self.repair_prompt if error_reason else self.initial_prompt

        def call_provider(prompt_value):
            value = invoke_json(_provider_messages(prompt_value))
            return json.dumps(value, ensure_ascii=False)

        chain = prompt | RunnableLambda(call_provider) | self.parser
        inputs = {"package_json": json.dumps(package, ensure_ascii=False)}
        if error_reason:
            inputs.update({
                "error_reason": error_reason,
                "prior_json": json.dumps(prior_output or {}, ensure_ascii=False),
            })
        return chain.invoke(inputs).model_dump()
