"""
Score the Workshop agent on the planted cases D1-D10 (SPEC §14.11, §14.12).

    python -m scripts.workshop_evaluate                 # all cases
    python -m scripts.workshop_evaluate R-ROAD-03       # one bike

It runs the real model (WORKSHOP_MODEL) in this process, without the worker, and
checks each brief against the answer key. It CHANGES the database (the cases
move on), so run it on a local copy: seed again to start over.

The lesson: change the prompt in workshop_tools.py, run this again, and compare.
A number in the agent's words that no tool gave it counts as invented.
"""
import re
import sys
import time

from sqlmodel import Session, select

from api import config
from api.database import engine
from api.models.models import Bike, WorkshopCase
from api.services import workshop_agent as agent, workshop_service as shop

# code: (case, the words a right diagnosis should use, the option kinds a good recommendation has)
ANSWER_KEY = {
    "R-EBIKE-08": ("D1", ("frame", "crack"), ("repair_and_sell", "scrap", "repair")),
    "R-CITY-05": ("D2", ("brake",), ("repair",)),
    "R-MTB-04": ("D3", ("bearing", "hub"), ("keep_watch", "repair")),
    "R-ROAD-03": ("D4", ("rim", "wheel"), ("repair",)),
    "R-EBIKE-09": ("D5", ("battery",), ("repair_and_sell", "scrap")),
    "R-GRAV-03": ("D6", ("brake", "pad", "rotor"), ("repair",)),
    "R-ROAD-04": ("D7", ("bottom bracket", "crank"), ("repair",)),
    "R-GRAV-04": ("D8", ("brake",), ("repair",)),
    "R-CARGO-03": ("D9", ("hub", "bearing", "wheel"), ("repair",)),
    "R-CITY-07": ("D10", ("chain", "tyre", "tire"), ("repair_and_sell",)),
}


def run_analysis(db: Session, case: WorkshopCase) -> float:
    """Rounds until the brief is in, or the agent stops. Returns the seconds it took."""
    started = time.time()
    case.stage = shop.ANALYSING
    db.add(case)
    db.commit()
    ai = agent.connect_agent(case.stage)
    while case.stage == shop.ANALYSING and case.agent_state != "failed":
        wait = agent.budget_wait(db, case)
        if wait:
            print(f"   ... the budget says wait {wait} s")
            time.sleep(wait)
        try:
            agent.one_round(db, case, ai)
            db.commit()
        except agent.Busy:      # BFH is full: wait, as the worker does
            db.rollback()
            print("   ... BFH is full, waiting")
            time.sleep(config.WORKSHOP_RETRY_SECONDS)
    return time.time() - started


def invented_numbers(db: Session, case: WorkshopCase) -> list[str]:
    """CHF amounts in the brief's own words that no tool result contains."""
    from_tools = " ".join(str(e.data) for e in shop.events_of(db, case.id) if e.kind == "tool")
    brief = case.brief or {}
    words = " ".join([brief.get("what_is_wrong", ""), brief.get("recommended_why", "")]
                     + [o["what_we_do"] for o in brief.get("options", [])])
    return [n for n in re.findall(r"CHF\s*(\d[\d']*)", words) if n.replace("'", "") not in from_tools]


def score(db: Session, code: str, case: WorkshopCase) -> dict:
    name, words, good_kinds = ANSWER_KEY[code]
    if not case.brief:
        return {"case": name, "code": code, "diagnosis": False, "recommendation": False, "invented": [], "tokens": 0,
                "note": case.agent_note or "no brief"}
    text = f"{case.brief['verdict_sentence']} {case.brief['what_is_wrong']}".lower()
    best = next(o for o in case.brief["options"] if o["key"] == case.brief["recommended"])
    events = shop.events_of(db, case.id)
    return {"case": name, "code": code, "diagnosis": any(w in text for w in words),
            "recommendation": best["kind"] in good_kinds, "kind": best["kind"], "invented": invented_numbers(db, case),
            "tokens": sum(e.tokens for e in events), "rounds": sum(e.kind == "round" for e in events), "note": ""}


def main() -> None:
    wanted = sys.argv[1:] or list(ANSWER_KEY)
    print(f"Model: {config.WORKSHOP_MODEL}\n")
    results = []
    with Session(engine) as db:
        for code in wanted:
            bike = db.exec(select(Bike).where(Bike.code == code)).first()
            case = shop.open_case_for(db, bike.id) if bike else None
            if case is None or case.stage != shop.OPEN:
                print(f"{code}: no case at stage 'open'. Seed again to start over.")
                continue
            seconds = run_analysis(db, case)
            result = {**score(db, code, case), "seconds": round(seconds)}
            results.append(result)
            print(f"{result['case']:>4} {code:<11} diagnosis {'yes' if result['diagnosis'] else 'NO ':<3}  "
                  f"recommendation {'yes' if result['recommendation'] else 'NO ':<3} ({result.get('kind', '-')})  "
                  f"invented {len(result['invented'])}  {result.get('rounds', 0)} rounds  {result['tokens']} tokens  "
                  f"{result['seconds']} s  {result['note']}")
    if results:
        good = sum(r["diagnosis"] and r["recommendation"] and not r["invented"] for r in results)
        print(f"\n{good} of {len(results)} fully right, {sum(r['tokens'] for r in results)} tokens.")


if __name__ == "__main__":
    main()
