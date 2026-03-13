import asyncio

from context_engineering import AgentContextManager, ContextHandoff


async def main():
    print("=== Multi-Agent Context Hand-off Demo ===")

    researcher = AgentContextManager(agent_id="researcher_beta", default_budget=200)
    researcher.set_system_prompt("You are a researcher. Find facts about Mars.")

    researcher.add_temporary_context("Mars is known as the Red Planet.", id="fact_1", priority=8.0)
    researcher.add_temporary_context(
        "It has two moons: Phobos and Deimos.", id="fact_2", priority=7.0
    )

    print("\n[Researcher] Gathering facts and preparing hand-off...")
    handoff_packet = researcher.export_handoff(target_agent_id="writer_gamma")

    handoff_json = handoff_packet.model_dump_json(by_alias=True)
    print(f"Handoff Packet Size: {len(handoff_json)} bytes")

    writer = AgentContextManager(agent_id="writer_gamma")
    received_packet = ContextHandoff.model_validate_json(handoff_json)

    print("\n[Writer] Importing hand-off from researcher...")
    writer.import_handoff(received_packet)
    writer.set_system_prompt("You are a writer. Write a poem based on the provided context.")

    messages = writer.build_messages()

    print("\n[Writer] Messages generated from Researcher context:")
    for msg in messages:
        print(f"\n[{msg.role.upper()}]")
        print(msg.content)

    if any("Mars" in m.content for m in messages):
        print("\nSuccess: Writer agent successfully resumed context gathered by Researcher.")


if __name__ == "__main__":
    asyncio.run(main())
