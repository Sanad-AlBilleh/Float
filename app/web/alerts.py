"""The alert centre and the personal activity feed (FR-32, FR-33)."""

import sqlite3

from fastapi import APIRouter, Depends, Request

from app.application import activity, alerts
from app.identity.api import Session
from app.web.deps import actor_for, get_conn, require_ready_session, verify_csrf
from app.web.rendering import redirect, render

router = APIRouter()


@router.get("/alerts")
def alert_centre(request: Request, session: Session = Depends(require_ready_session),
                 conn: sqlite3.Connection = Depends(get_conn)):
    alerts.evaluate(conn, session.user.id, request.app.state.clock)
    return render(request, "alerts.html", {"alerts": alerts.list_alerts(conn, actor_for(request, session))})


@router.post("/alerts/{alert_id}/read", dependencies=[Depends(verify_csrf)])
def read(alert_id: int, request: Request, session: Session = Depends(require_ready_session),
         conn: sqlite3.Connection = Depends(get_conn)):
    alerts.mark_read(conn, actor_for(request, session), alert_id, request.app.state.clock)
    return redirect("/alerts")


@router.post("/alerts/{alert_id}/dismiss", dependencies=[Depends(verify_csrf)])
def dismiss(alert_id: int, request: Request, session: Session = Depends(require_ready_session),
            conn: sqlite3.Connection = Depends(get_conn)):
    alerts.dismiss(conn, actor_for(request, session), alert_id, request.app.state.clock)
    return redirect("/alerts")


@router.get("/activity")
def personal_activity(request: Request, session: Session = Depends(require_ready_session),
                      conn: sqlite3.Connection = Depends(get_conn)):
    return render(request, "activity.html", {"items": activity.personal_activity(conn, actor_for(request, session))})
