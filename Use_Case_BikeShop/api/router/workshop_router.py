"""
The Workshop for staff (SPEC §14): /staff/workshop.

Everything that changes the shop is an endpoint here, and the agent can't reach
any of them: its tools only read. Authentication and the staff role are checked
by middleware; /staff calls are free and not rate limited.
"""
from datetime import date, datetime
from decimal import Decimal
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field as PField
from sqlmodel import Session

from ..config import WORKSHOP_MODEL
from ..database import get_db
from ..models.models import BikeResponse, LocalTimes, RentalResponse
from ..services import scan_service, workshop_service as shop
from ..services.rental_service import RentalService
from ..timeutils import to_local


class WaitingBike(BaseModel):
    bike_id: int
    code: str
    name: str
    returned_at: Optional[datetime] = None


class CaseSummary(BaseModel):
    id: int
    bike_id: int
    code: str
    name: str
    category: str
    bike_status: str
    stage: str
    agent_state: str
    verdict: str
    ready_estimate: Optional[date] = None
    next_booking: Optional[datetime] = PField(default=None, description="The bike's next booked pick-up")


class WorkshopOverview(BaseModel):
    waiting: List[WaitingBike] = PField(description="Returned bikes that haven't been through the machine")
    cases: List[CaseSummary]
    closed: int = PField(description="Cases closed so far")
    mechanic_hours: dict = PField(description="Booked mechanic hours per day")
    model: str = PField(description="The AI model the agent uses")


class ScanResponse(LocalTimes):
    id: int
    bike_id: int
    scanned_at: Optional[datetime] = None
    verdict: Optional[str] = None
    groups: List[dict] = PField(description="One line per group of parts")
    readings: List[dict] = PField(description="Every reading, with its limits and status")
    case_id: Optional[int] = PField(default=None, description="The case it opened or fed, if any")


class EventResponse(LocalTimes):
    id: int
    stage: str
    author: str
    kind: str
    content: str
    data: Optional[dict] = None
    reasoning: Optional[str] = None
    tokens: int
    created_at: datetime


class ActionResponse(BaseModel):
    id: int
    rental_id: int
    kind: str
    why: str
    draft: str
    status: str
    outcome: Optional[str] = None
    customer: Optional[str] = PField(default=None, description="Username, for staff only; the agent never sees it")
    start_at: Optional[datetime] = None


class CaseDetail(CaseSummary):
    agent_note: Optional[str] = None
    brief: Optional[dict] = None
    chosen_option: Optional[str] = None
    agent_agreed: Optional[bool] = None
    plan: Optional[dict] = None
    plan_version: int = 0
    outcome: Optional[str] = None
    staff_can_agree: bool = PField(description="True once the agent has answered the staff's choice")
    groups: List[dict]
    events: List[EventResponse]
    actions: List[ActionResponse]
    tokens_used: int


class ChooseRequest(BaseModel):
    option: Literal["A", "B", "C", "D"]


class MessageRequest(BaseModel):
    text: str = PField(min_length=1, max_length=2000, examples=["The customer is a regular. Can we use the cheaper part?"])


class ProgressRequest(BaseModel):
    step: Literal["ordered", "arrived", "repaired"]


class ReadyEstimateRequest(BaseModel):
    ready_estimate: Optional[date] = None


class ListForSaleRequest(BaseModel):
    price_chf: Decimal = PField(gt=0, max_digits=10, decimal_places=2)


class EmailRequest(BaseModel):
    text: str = PField(min_length=1, max_length=4000)


class FinishRequest(BaseModel):
    outcome: str = PField(min_length=1, max_length=300, examples=["Called: they take the other bike."])


class MoveRequest(BaseModel):
    bike_id: int


class SaleResult(BaseModel):
    case: CaseSummary
    sale_bike: BikeResponse


def _summary(db: Session, case) -> dict:
    bike = shop.get_bike(db, case.bike_id)
    bookings = shop.upcoming_bookings(db, bike.id)
    return dict(id=case.id, bike_id=bike.id, code=bike.code, name=bike.name, category=bike.category.value,
                bike_status=bike.status.value, stage=case.stage, agent_state=case.agent_state,
                verdict=shop.case_scan(db, case).verdict, ready_estimate=case.ready_estimate,
                next_booking=to_local(bookings[0].start_at) if bookings else None)


def _action(db: Session, action) -> ActionResponse:
    rental = shop.db_rental(db, action.rental_id)
    return ActionResponse(id=action.id, rental_id=action.rental_id, kind=action.kind, why=action.why, draft=action.draft,
                          status=action.status, outcome=action.outcome, customer=shop.customer_of(db, rental),
                          start_at=to_local(rental.start_at))


def _detail(db: Session, case) -> CaseDetail:
    shop.notice_lost_agent(db, case)
    events = shop.events_of(db, case.id)
    scan = shop.case_scan(db, case)
    return CaseDetail(**_summary(db, case), agent_note=case.agent_note, brief=case.brief, chosen_option=case.chosen_option,
                      agent_agreed=case.agent_agreed, plan=case.plan, plan_version=case.plan_version, outcome=case.outcome,
                      staff_can_agree=case.stage == shop.DISCUSSING and case.agent_state in ("idle", "failed"),
                      groups=scan_service.overview(scan, scan_service.previous_scan(db, scan)),
                      events=[EventResponse.model_validate(e) for e in events],
                      actions=[_action(db, a) for a in shop.actions_of(db, case.id)],
                      tokens_used=sum(e.tokens for e in events))


class WorkshopRouter:
    """The function names are the operation_ids (SPEC §6, §8)."""

    def __init__(self):
        self.router = APIRouter()
        self.rental_service = RentalService()
        r = self.router
        r.get("/workshop", response_model=WorkshopOverview, summary="Bikes waiting for a scan, and open cases")(self.workshop_overview)
        r.post("/workshop/bikes/{bike_id}/scan", response_model=ScanResponse, summary="Run the diagnostic machine")(self.run_scan)
        r.get("/workshop/scans/{scan_id}", response_model=ScanResponse, summary="One scan, every reading")(self.get_scan)
        r.get("/workshop/cases/{case_id}", response_model=CaseDetail, summary="One case, with every step")(self.get_case)
        r.post("/workshop/cases/{case_id}/analyse", response_model=CaseDetail, summary="Let the agent analyse the scan")(self.analyse_case)
        r.post("/workshop/cases/{case_id}/choose", response_model=CaseDetail, summary="Pick an option")(self.choose_option)
        r.post("/workshop/cases/{case_id}/messages", response_model=CaseDetail, summary="Write to the agent")(self.send_message)
        r.post("/workshop/cases/{case_id}/agree", response_model=CaseDetail, summary="Agreed: write the plan")(self.agree_choice)
        r.post("/workshop/cases/{case_id}/approve-plan", response_model=CaseDetail, summary="Approve the plan")(self.approve_plan)
        r.post("/workshop/cases/{case_id}/retry", response_model=CaseDetail, summary="Hand a stuck case back to the agent")(self.retry_case)
        r.post("/workshop/cases/{case_id}/maintenance", response_model=CaseDetail, summary="Put the bike in maintenance")(self.put_in_maintenance)
        r.post("/workshop/cases/{case_id}/ready-estimate", response_model=CaseDetail, summary="Set when the bike is expected back")(self.set_ready_estimate)
        r.post("/workshop/cases/{case_id}/progress", response_model=CaseDetail, summary="Parts ordered, arrived, repair done")(self.record_progress)
        r.post("/workshop/cases/{case_id}/back-in-service", response_model=CaseDetail, summary="Rent the bike again")(self.back_in_service)
        r.post("/workshop/cases/{case_id}/list-for-sale", response_model=SaleResult, summary="Sell the bike")(self.list_for_sale)
        r.post("/workshop/cases/{case_id}/scrap", response_model=CaseDetail, summary="Scrap the bike")(self.scrap_bike)
        r.get("/workshop/actions/{action_id}/alternatives", summary="Free bikes and other dates for a booking")(self.booking_alternatives)
        r.post("/workshop/actions/{action_id}/email", response_model=ActionResponse, summary="Send the customer the email")(self.send_customer_email)
        r.post("/workshop/actions/{action_id}/done", response_model=ActionResponse, summary="Tick off a to-do")(self.finish_customer_action)
        r.post("/workshop/actions/{action_id}/move", response_model=RentalResponse, summary="Move the booking to another bike")(self.move_customer_booking)
        r.post("/workshop/actions/{action_id}/cancel", response_model=RentalResponse, summary="Cancel the booking")(self.cancel_customer_booking)

    def workshop_overview(self, db: Session = Depends(get_db)) -> WorkshopOverview:
        """Use this for the Workshop page: bikes waiting for the machine, open cases, the mechanic's week."""
        waiting = []
        for scan in scan_service.waiting_bikes(db):
            bike = shop.get_bike(db, scan.bike_id)
            rental = shop.db_rental(db, scan.rental_id) if scan.rental_id else None
            waiting.append(WaitingBike(bike_id=bike.id, code=bike.code, name=bike.name,
                                       returned_at=to_local(rental.returned_at) if rental else None))
        return WorkshopOverview(waiting=waiting, cases=[CaseSummary(**_summary(db, c)) for c in shop.list_cases(db)],
                                closed=len(shop.list_cases(db, active_only=False)) - len(shop.list_cases(db)),
                                mechanic_hours={d.isoformat(): str(h) for d, h in sorted(shop.mechanic_load(db).items())},
                                model=WORKSHOP_MODEL)

    def _scan_response(self, db: Session, scan, case_id: Optional[int]) -> ScanResponse:
        return ScanResponse(id=scan.id, bike_id=scan.bike_id, scanned_at=scan.scanned_at, verdict=scan.verdict,
                            groups=scan_service.overview(scan, scan_service.previous_scan(db, scan)),
                            readings=scan.readings, case_id=case_id)

    def run_scan(self, bike_id: int, db: Session = Depends(get_db)) -> ScanResponse:
        """Puts a bike through the machine. Takes no AI call; the agent starts only on analyse_case."""
        scan, case = shop.run_scan(db, bike_id)
        return self._scan_response(db, scan, case.id if case else None)

    def get_scan(self, scan_id: int, db: Session = Depends(get_db)) -> ScanResponse:
        """Every reading of one scan, with its limits."""
        return self._scan_response(db, scan_service.get_scan(db, scan_id), None)

    def get_case(self, case_id: int, db: Session = Depends(get_db)) -> CaseDetail:
        """The whole case; the page polls this while the agent works."""
        return _detail(db, shop.get_case(db, case_id))

    def analyse_case(self, case_id: int, db: Session = Depends(get_db)) -> CaseDetail:
        """Starts the agent. It works in the background; poll get_case."""
        return _detail(db, shop.analyse(db, case_id))

    def choose_option(self, case_id: int, request: ChooseRequest, db: Session = Depends(get_db)) -> CaseDetail:
        """Picks an option, or changes it during the discussion. The agent then has to answer."""
        return _detail(db, shop.choose(db, case_id, request.option))

    def send_message(self, case_id: int, request: MessageRequest, db: Session = Depends(get_db)) -> CaseDetail:
        """Writes to the agent during a discussion or a plan review."""
        return _detail(db, shop.say(db, case_id, request.text))

    def agree_choice(self, case_id: int, db: Session = Depends(get_db)) -> CaseDetail:
        """Ends the discussion and starts the plan. Works only after the agent has answered."""
        return _detail(db, shop.agree(db, case_id))

    def approve_plan(self, case_id: int, db: Session = Depends(get_db)) -> CaseDetail:
        """Approves the current plan; its bookings become to-dos."""
        return _detail(db, shop.approve_plan(db, case_id))

    def retry_case(self, case_id: int, db: Session = Depends(get_db)) -> CaseDetail:
        """Use this when the agent failed or seems stuck."""
        return _detail(db, shop.retry(db, case_id))

    def put_in_maintenance(self, case_id: int, db: Session = Depends(get_db)) -> CaseDetail:
        """Takes the bike out of service at once. Doesn't wait for the AI."""
        return _detail(db, shop.put_in_maintenance(db, case_id))

    def set_ready_estimate(self, case_id: int, request: ReadyEstimateRequest, db: Session = Depends(get_db)) -> CaseDetail:
        """Sets the date customers see. An estimate, not a promise."""
        return _detail(db, shop.set_ready_estimate(db, case_id, request.ready_estimate))

    def record_progress(self, case_id: int, request: ProgressRequest, db: Session = Depends(get_db)) -> CaseDetail:
        """Records parts ordered, parts arrived, or repair done. Nothing is really ordered."""
        return _detail(db, shop.progress(db, case_id, request.step))

    def back_in_service(self, case_id: int, db: Session = Depends(get_db)) -> CaseDetail:
        """Makes the bike rentable again. Refused while the last scan is unfit."""
        return _detail(db, shop.back_in_service(db, case_id))

    def list_for_sale(self, case_id: int, request: ListForSaleRequest, db: Session = Depends(get_db)) -> SaleResult:
        """Retires the rental bike and creates a linked sale bike. Needs no open bookings."""
        case, bike = shop.list_for_sale(db, case_id, request.price_chf)
        return SaleResult(case=CaseSummary(**_summary(db, case)), sale_bike=BikeResponse.model_validate(bike))

    def scrap_bike(self, case_id: int, db: Session = Depends(get_db)) -> CaseDetail:
        """Retires the bike for good. Needs no open bookings."""
        return _detail(db, shop.scrap(db, case_id))

    def booking_alternatives(self, action_id: int, db: Session = Depends(get_db)) -> dict:
        """Other free bikes for the booking, with the price change, and other dates."""
        action = shop.get_action(db, action_id)
        return shop.alternatives(db, action.rental_id, shop.get_case(db, action.case_id).ready_estimate)

    def send_customer_email(self, action_id: int, request: EmailRequest, db: Session = Depends(get_db)) -> ActionResponse:
        """Queues the staff's email to the booking's customer. Goes out through the worker."""
        return _action(db, shop.send_email(db, action_id, request.text))

    def finish_customer_action(self, action_id: int, request: FinishRequest, db: Session = Depends(get_db)) -> ActionResponse:
        """Ticks off a to-do, e.g. a phone call, with what came of it."""
        return _action(db, shop.finish_action(db, action_id, request.outcome))

    def move_customer_booking(self, action_id: int, request: MoveRequest, db: Session = Depends(get_db)) -> RentalResponse:
        """Moves the booking to another free bike at that bike's price. After the customer agreed."""
        _, rental = shop.move_booking(db, action_id, request.bike_id)
        return RentalResponse(**self.rental_service.describe(db, rental, True))

    def cancel_customer_booking(self, action_id: int, db: Session = Depends(get_db)) -> RentalResponse:
        """Cancels the booking."""
        _, rental = shop.cancel_booking(db, action_id)
        return RentalResponse(**self.rental_service.describe(db, rental, True))
