"""
STEP 2: Send ONE question plus the tool menu to the AI, and look at what comes back.

The key insight: the AI does NOT answer. It sends back a REQUEST:
"please run tool X with these inputs". Nothing runs yet; we only print it.

Which AI? Whatever ASSISTANT_PROVIDER says in .env (default: BFH). See api/tools/llm.py.

    python -m scripts.assistant_step2_see_the_request
    python -m scripts.assistant_step2_see_the_request "your own question"
"""
import sys

from api.tools.assistant_tools import TOOLS, system_prompt
from api.tools.llm import AIError, connect

question = " ".join(sys.argv[1:]) or "Is an e-bike free next Saturday from 10:00 to 14:00?"

ai = connect(system=system_prompt(), tools=TOOLS)                       # <- the menu
try:
    reply = ai.ask([{"role": "user", "content": question}])
except AIError as e:
    raise SystemExit(str(e))

print("QUESTION:", question)
if reply.text:
    print("\nThe AI says:", reply.text)
for call in reply.tool_calls:
    print("\nThe AI asks us to run a tool:")
    print("   tool name :", call.name)
    print("   inputs    :", call.input)
    print("   request id:", call.id)

print("\nThe raw reply, exactly as the provider sent it (compare providers!):")
print("  ", reply.raw)

print("\nNothing has been run. In step 3, our code runs the tool and sends back the result.")
