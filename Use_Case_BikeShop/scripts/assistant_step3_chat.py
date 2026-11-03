"""
STEP 3: The full loop. A small chat with the BikeShop assistant (SPEC §13.3).

  1. Send the conversation + tool menu to the AI.
  2. If the AI asks for tools: run them, send the results back, go to 1.
  3. If the AI answers with text: show it to the customer.

Every tool call is printed as [TOOL CALL] / [RESULT] so you can SEE what happens.
Which AI? Whatever ASSISTANT_PROVIDER says in .env (default: BFH). This loop is the same for all.

    python -m scripts.assistant_step3_chat --user customer      (type 'quit' to stop)

--user picks the signed-in customer from the database. The AI never sees who it is.
"""
import argparse
import json

from sqlmodel import Session, select

from api.database import engine, init_database
from api.models.models import User
from api.tools.brankas_great_tools import TOOLS, run_tool, system_prompt
from api.tools.llm import AIError, connect


def signed_in_customer(db: Session, username: str) -> str:
    """The user_id of `username`. It goes to run_tool(), never to the AI."""
    user = db.exec(select(User).where(User.username == username)).first()
    if not user:
        raise SystemExit(f"No user '{username}'. Seed the database first: python -m scripts.seed")
    return user.user_id


def chat_turn(ai, messages: list, db: Session, user_id: str, show=print) -> str:
    """One customer message -> tools as often as the AI asks -> the answer.
    `messages` is the whole conversation; the AI has no memory, we resend it each time."""
    try:
        reply = ai.ask(messages)

        # As long as the AI asks for tools, run them and send the results back.
        while reply.tool_calls:
            messages += ai.assistant_message(reply)

            results = []
            for call in reply.tool_calls:
                show(f"   [TOOL CALL] {call.name}({json.dumps(call.input)})")
                result = run_tool(call.name, call.input, db, user_id)   # <- OUR code runs here
                show(f"   [RESULT]    {json.dumps(result, default=str)}")
                results.append(result)

            messages += ai.tool_result_messages(reply.tool_calls, results)  # matched by id
            reply = ai.ask(messages)
    except AIError as e:  # busy, unreachable, wrong key: keep the conversation, try again
        return str(e)

    # The AI is done with tools: its answer.
    messages += ai.assistant_message(reply)
    return reply.text


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", default="customer", help="username of the signed-in customer")
    args = parser.parse_args()

    init_database()
    with Session(engine) as db:
        user_id = signed_in_customer(db, args.user)
        ai = connect(system_prompt(), TOOLS)
        messages = []
        print("BikeShop assistant. Type 'quit' to stop.\n")

        while True:
            user_text = input("You: ").strip()
            if user_text.lower() in {"quit", "exit"}:
                break
            if not user_text:
                continue
            messages.append({"role": "user", "content": user_text})
            print(f"\nAssistant: {chat_turn(ai, messages, db, user_id)}\n")


if __name__ == "__main__":
    main()
