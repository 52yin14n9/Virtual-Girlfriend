from __future__ import annotations

import atexit
import json
from typing import Any

from flask import (
    Flask,
    Response,
    jsonify,
    render_template,
    request,
    stream_with_context,
)

from .message_store import (
    MessageStore,
)
from .runtime import (
    AsyncAgentRuntime,
)
from ..agent import SilverWolfAgent


def create_app(
    *,
    agent: SilverWolfAgent | None = None,
    store: MessageStore | None = None,
    runtime: Any | None = None,
    start_runtime: bool = True,
) -> Flask:
    app = Flask(__name__)

    active_agent = (
        agent
        or SilverWolfAgent()
    )
    active_store = (
        store
        or MessageStore()
    )
    active_runtime = (
        runtime
        or AsyncAgentRuntime(
            agent=active_agent,
            store=active_store,
        )
    )

    _bootstrap_recent_history(
        active_agent,
        active_store,
    )

    if start_runtime:
        active_runtime.start()
        atexit.register(
            active_runtime.stop
        )

    app.extensions[
        "silverwolf_agent"
    ] = active_agent
    app.extensions[
        "silverwolf_store"
    ] = active_store
    app.extensions[
        "silverwolf_runtime"
    ] = active_runtime

    @app.get("/")
    def index() -> str:
        return render_template(
            "index.html"
        )

    @app.get("/api/messages")
    def messages():
        after = _parse_int(
            request.args.get(
                "after",
                "0",
            )
        )
        events = (
            active_store.snapshot(
                after=after
            )
        )
        return jsonify(
            {
                "messages": [
                    event.to_dict()
                    for event in events
                ],
                "last_id": (
                    events[-1].event_id
                    if events
                    else after
                ),
            }
        )

    @app.get("/api/events")
    def events() -> Response:
        query_after = _parse_int(
            request.args.get(
                "after",
                "0",
            )
        )
        header_after = _parse_int(
            request.headers.get(
                "Last-Event-ID",
                "0",
            )
        )
        initial_after = max(
            query_after,
            header_after,
        )

        @stream_with_context
        def generate():
            current = initial_after

            while True:
                new_events = (
                    active_store
                    .wait_for_events(
                        after=current,
                        timeout=15.0,
                    )
                )

                if not new_events:
                    yield (
                        ": keepalive\n\n"
                    )
                    continue

                for event in new_events:
                    current = (
                        event.event_id
                    )
                    payload = json.dumps(
                        event.to_dict(),
                        ensure_ascii=False,
                    )
                    yield (
                        f"id: {event.event_id}\n"
                        "event: message\n"
                        f"data: {payload}\n\n"
                    )

        return Response(
            generate(),
            mimetype=(
                "text/event-stream"
            ),
            headers={
                "Cache-Control": (
                    "no-cache"
                ),
                "X-Accel-Buffering": (
                    "no"
                ),
                "Connection": (
                    "keep-alive"
                ),
            },
        )

    @app.post("/api/chat")
    def chat():
        payload = (
            request.get_json(
                silent=True
            )
            or {}
        )
        text = str(
            payload.get(
                "message",
                "",
            )
        ).strip()

        if not text:
            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "消息不能为空"
                    ),
                }
            ), 400
        if len(text) > 4000:
            return jsonify(
                {
                    "ok": False,
                    "error": (
                        "单条消息不能超过 "
                        "4000 个字符"
                    ),
                }
            ), 400

        received_at = (
            active_agent.now()
        )
        event = active_store.publish(
            role="user",
            content=text,
            timestamp=received_at,
            source="interactive",
            weight=100,
            category="user_message",
        )

        try:
            future = (
                active_runtime
                .submit_user_message(
                    text,
                    received_at=(
                        received_at
                    ),
                )
            )
        except Exception as exc:
            active_store.publish(
                role="system",
                content=(
                    "无法提交消息："
                    + str(exc)
                ),
                timestamp=(
                    active_agent.now()
                ),
                source="system",
                weight=100,
                category="error",
            )
            return jsonify(
                {
                    "ok": False,
                    "error": str(exc),
                }
            ), 503

        return jsonify(
            {
                "ok": True,
                "accepted": True,
                "event_id": (
                    event.event_id
                ),
                "request_pending": (
                    not future.done()
                ),
            }
        ), 202

    @app.get("/api/status")
    def status():
        current = active_agent.now()
        identity_manager = getattr(
            active_agent,
            "agent_identity",
            None,
        )
        identity = (
            identity_manager.prompt_view(
                current.date()
            )
            if identity_manager
            is not None
            else {
                "current_age": None,
                "birthday_display": "",
            }
        )
        proactive_state_manager = getattr(
            active_agent,
            "proactive_state",
            None,
        )
        proactive_state = (
            proactive_state_manager.snapshot()
            if proactive_state_manager
            is not None
            else {}
        )
        # Lv27: 长期承诺与语料库状态
        commitment_manager = getattr(
            active_agent,
            "commitment_service",
            None,
        )
        commitment_state = (
            commitment_manager.snapshot()
            if commitment_manager is not None
            else {}
        )
        corpus_manager = getattr(
            active_agent,
            "corpus",
            None,
        )
        corpus_state = (
            corpus_manager.stats()
            if corpus_manager is not None
            else {}
        )

        return jsonify(
            {
                "online": True,
                "runtime_running": bool(
                    getattr(
                        active_runtime,
                        "running",
                        False,
                    )
                ),
                "scheduler_running": bool(
                    getattr(
                        active_agent.scheduler,
                        "running",
                        False,
                    )
                ),
                "model": (
                    active_agent.config
                    .model
                ),
                "offline": (
                    active_agent.offline
                ),
                "planner_llm_enabled": bool(
                    getattr(
                        active_agent.config,
                        "planner_llm_enabled",
                        False,
                    )
                ),
                "planner_llm_available": bool(
                    getattr(
                        active_agent,
                        "schedule_judge",
                        None,
                    )
                    and active_agent
                    .schedule_judge
                    .available
                ),
                "now": (
                    current.isoformat(
                        timespec="seconds"
                    )
                ),
                "timezone": (
                    active_agent.config
                    .timezone
                ),
                "preferred_name": (
                    active_agent.profile
                    .preferred_name()
                ),
                "agent_age": (
                    identity.get(
                        "current_age"
                    )
                ),
                "agent_birthday": (
                    identity.get(
                        "birthday_display",
                        "",
                    )
                ),
                "follow_up_enabled": bool(
                    getattr(
                        active_agent.config,
                        "proactive_follow_up_enabled",
                        False,
                    )
                ),
                "follow_up_seconds": int(
                    getattr(
                        active_agent.config,
                        "proactive_follow_up_seconds",
                        120,
                    )
                ),
                "pending_follow_up": (
                    proactive_state.get(
                        "pending_follow_up"
                    )
                ),
                "plan_count": len(
                    [
                        plan
                        for plan in (
                            active_agent
                            .plans_snapshot()
                        )
                        if (
                            plan.get(
                                "status"
                            )
                            == "pending"
                        )
                    ]
                ),
                "last_scheduler_error": (
                    active_agent.scheduler
                    .last_error
                ),
                "commitment": commitment_state,
                "corpus": corpus_state,
            }
        )

    @app.get("/api/plans")
    def plans():
        return jsonify(
            {
                "plans": (
                    active_agent
                    .plans_snapshot()
                ),
            }
        )

    @app.delete(
        "/api/plans/<plan_id>"
    )
    def cancel_plan(
        plan_id: str,
    ):
        cancelled = (
            active_agent
            .plan_manager
            .cancel(plan_id)
        )
        return jsonify(
            {
                "ok": cancelled,
            }
        ), (
            200
            if cancelled
            else 404
        )

    @app.get("/api/time-settings")
    def time_settings():
        return jsonify(
            active_agent
            .time_snapshot()
        )

    @app.patch(
        "/api/time-settings/<slot>"
    )
    def update_time_settings(
        slot: str,
    ):
        payload = (
            request.get_json(
                silent=True
            )
            or {}
        )
        value = str(
            payload.get(
                "time",
                "",
            )
        ).strip()
        try:
            settings = (
                active_agent
                .time_manager
                .set_slot(
                    slot,
                    value,
                )
            )
        except Exception as exc:
            return jsonify(
                {
                    "ok": False,
                    "error": str(exc),
                }
            ), 400

        return jsonify(
            {
                "ok": True,
                "slot": slot,
                "settings": settings,
            }
        )

    @app.post(
        "/api/proactive/tick"
    )
    def proactive_tick():
        try:
            future = (
                active_runtime
                .trigger_proactive_once()
            )
        except Exception as exc:
            return jsonify(
                {
                    "ok": False,
                    "error": str(exc),
                }
            ), 503

        return jsonify(
            {
                "ok": True,
                "accepted": True,
                "request_pending": (
                    not future.done()
                ),
            }
        ), 202

    @app.get("/api/debug/pae")
    def pae_debug():
        return Response(
            active_agent.pae_debug(),
            mimetype="application/json",
        )

    @app.get("/api/debug/proactive")
    def proactive_debug():
        scheduler = (
            active_agent.scheduler
        )
        return jsonify(
            {
                "time_settings": (
                    active_agent
                    .time_snapshot()
                ),
                "plans": (
                    active_agent
                    .plans_snapshot()
                ),
                "proactive_state": (
                    active_agent
                    .proactive_state
                    .snapshot()
                ),
                "last_planner_json": (
                    json.loads(
                        scheduler
                        .last_plan_json
                    )
                    if (
                        scheduler
                        .last_plan_json
                    )
                    else None
                ),
                "last_executor_json": (
                    json.loads(
                        scheduler
                        .last_execution_json
                    )
                    if (
                        scheduler
                        .last_execution_json
                    )
                    else None
                ),
            }
        )

    return app


def _bootstrap_recent_history(
    agent: SilverWolfAgent,
    store: MessageStore,
) -> None:
    if store.snapshot():
        return

    memory_manager = getattr(
        agent,
        "memory",
        None,
    )
    if memory_manager is None:
        return

    memory = memory_manager.snapshot()
    for turn in memory.get(
        "recent_turns",
        [],
    ):
        source = str(
            turn.get(
                "source",
                "interactive",
            )
        )
        user_text = str(
            turn.get(
                "user",
                "",
            )
        ).strip()
        assistant_text = str(
            turn.get(
                "assistant",
                "",
            )
        ).strip()

        if user_text:
            store.publish(
                role="user",
                content=user_text,
                timestamp=str(
                    turn.get(
                        "user_at",
                        turn.get(
                            "at",
                            "",
                        ),
                    )
                ),
                source="interactive",
                weight=100,
                category="history",
            )

        if assistant_text:
            store.publish(
                role="assistant",
                content=assistant_text,
                timestamp=str(
                    turn.get(
                        "assistant_at",
                        turn.get(
                            "at",
                            "",
                        ),
                    )
                ),
                source=source,
                weight=70,
                category="history",
            )


def _parse_int(
    value: str | None,
) -> int:
    try:
        return max(
            0,
            int(value or "0"),
        )
    except ValueError:
        return 0
