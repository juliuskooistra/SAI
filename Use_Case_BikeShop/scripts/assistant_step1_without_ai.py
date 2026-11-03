"""
STEP 1: Test the tools WITHOUT any AI.

A tool is just a normal function. Before connecting an AI, make sure the
functions give the right answers. No key needed, but a seeded database
(python -m scripts.seed). This script books nothing.

    python -m scripts.assistant_step1_without_ai

We call run_tool(), exactly as the chat will: the results below are exactly
what the AI will get to read.
"""
import json
from datetime import timedelta

from sqlmodel import Session

from api.database import engine, init_database
from api.timeutils import to_local, utcnow
from api.tools.brankas_great_tools import run_tool
from scripts.assistant_step3_chat import signed_in_customer

today = to_local(utcnow()).date()
saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)  # next Saturday
sunday = saturday + timedelta(days=1)


def show(title, name, inputs):
    print(f"\n{title}\n   run_tool({name!r}, {inputs})")
    print("  ", json.dumps(run_tool(name, inputs, db, user_id), indent=2, default=str).replace("\n", "\n   "))


init_database()
with Session(engine) as db:
    user_id = signed_in_customer(db, "customer")

    show(f"1) Look up: which e-bikes are free on Saturday {saturday}, 10:00-14:00?",
         "check_availability", {"start_at": f"{saturday}T10:00", "end_at": f"{saturday}T14:00", "category": "ebike"})

    first = run_tool("check_availability", {"start_at": f"{saturday}T10:00", "end_at": f"{saturday}T14:00",
                                            "category": "ebike"}, db, user_id)["bikes"]
    if first:
        show("2) Compute: what does the first one cost for the whole weekend (Sat 10:00 to Mon 10:00)?",
             "quote_rental", {"bike_id": first[0]["bike_id"], "start_at": f"{saturday}T10:00",
                              "end_at": f"{sunday + timedelta(days=1)}T10:00"})

    show("3) Act (rule check): try to book on a Sunday",
         "book_rental", {"bike_id": first[0]["bike_id"] if first else 1,
                         "start_at": f"{sunday}T10:00", "end_at": f"{sunday}T12:00"})

    show("4) Wrong input: a category that doesn't exist",
         "check_availability", {"start_at": f"{saturday}T10:00", "end_at": f"{saturday}T14:00", "category": "tandem"})

    show("5) Hand off", "escalate_to_staff",
         {"reason": "complaint", "customer_message": "My bike had a flat tyre yesterday."})

    show(f"6) Predict: I'd rather just walk in for an e-bike on Saturday {saturday}. Will there be one?\n"
         "   (needs the model: run python -m scripts.train_demand_model first)",
         "demand_forecast", {"category": "ebike", "date": saturday.isoformat()})

print("\nAll of this is our code and our rules. The AI will only decide WHEN to")
print("call these tools and WITH WHICH inputs.")
