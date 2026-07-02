from strands import Agent

from model.load import load_model


class BaseAgent:

    def __init__(
        self,
        system_prompt,
        tools,
    ):

        self._agent = Agent(
            model=load_model(),
            system_prompt=system_prompt,
            tools=tools,
        )

    async def invoke(
        self,
        question,
    ):

        stream = self._agent.stream_async(question)

        response = ""

        async for event in stream:

            if (
                "data" in event
                and isinstance(
                    event["data"],
                    str,
                )
            ):

                response += event["data"]

        return response