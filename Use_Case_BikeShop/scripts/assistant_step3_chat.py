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

from sqlmodel import Session, select

from api.database import engine, init_database
from api.models.models import User
from api.tools.assistant_tools import TOOLS, system_prompt
from api.services.chat_service import chat_turn   # the loop itself: one turn, also used by the website
from api.services.llm_service import NotConfigured, connect


def signed_in_customer(db: Session, username: str) -> str:
    """The user_id of `username`. It goes to run_tool(), never to the AI."""
    user = db.exec(select(User).where(User.username == username)).first()
    if not user:
        raise SystemExit(f"No user '{username}'. Seed the database first: python -m scripts.seed")
    return user.user_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--user", default="customer", help="username of the signed-in customer")
    args = parser.parse_args()

    init_database()
    with Session(engine) as db:
        user_id = signed_in_customer(db, args.user)
        try:
            ai = connect(system_prompt(), TOOLS)
        except NotConfigured as e:   # something missing in .env: say what, and stop
            raise SystemExit(str(e))
        print(f"(Using {ai.provider}, model {ai.model})\n")
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
