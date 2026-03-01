"""
FastAPI Backend for AI Interview Platform
Wraps the existing InterviewEngine with REST endpoints.
"""

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import tempfile
import copy
import os
import uuid
from datetime import datetime

from interview_platform import InterviewEngine, Config

app = FastAPI(title="InterviewAI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions: dict = {}


# ── MODELS ────────────────────────────────────────────────────────
class StartSessionResponse(BaseModel):
    session_id: str
    mode: str
    max_questions: int
    persona: str
    duration: int
    resume_summary: dict
    jd_summary: dict

class AnswerRequest(BaseModel):
    answer: str

class AnswerResponse(BaseModel):
    question_id: int
    is_dont_know: bool
    technical_score: float
    clarity_score: float
    confidence_score: float
    overall_score: float
    feedback: str
    interview_complete: bool

class NextQuestionResponse(BaseModel):
    question_id: int
    question: str
    total_questions: int
    interview_complete: bool

class ReportResponse(BaseModel):
    session_id: str
    overall_rating: float
    individual_ratings: dict
    final_report: str
    performance_metrics: dict
    weaknesses: list


# ── HELPERS ───────────────────────────────────────────────────────

def _delete_session_data(engine: InterviewEngine, session_id: str):
    """
    Fix 4: Delete all data for this session from both Neo4j and Qdrant.
    Called when the session ends so no stale data accumulates.
    """
    # ── Neo4j: delete all nodes related to this session ───────────
    try:
        driver = engine.neo4j._new_driver()
        with driver.session() as neo_session:
            neo_session.run("""
                MATCH (u:User {session_id: $session_id})
                OPTIONAL MATCH (u)-[:ASKED]->(q:Question)-[:ANSWERED_BY]->(a:Answer)
                OPTIONAL MATCH (a)-[:REVEALS]->(w:Weakness)-[:SUGGESTS]->(i:Improvement)
                OPTIONAL MATCH (u)-[:TARGETS]->(r:Requirement)
                DETACH DELETE u, q, a, w, i, r
            """, session_id=session_id)
            neo_session.run("""
                MATCH (s:Skill)
                WHERE NOT (s)--()
                DELETE s
            """)
            print(f"[cleanup] Neo4j data deleted for {session_id}")
        driver.close()
    except Exception as e:
        print(f"[cleanup] Neo4j delete warning for {session_id}: {e}")

    # ── Qdrant: delete all points with matching session_id ─────────
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        filter_condition = Filter(
            must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))]
        )
        for collection in ["resume_embeddings", "jd_embeddings", "qa_context"]:
            try:
                engine.qdrant.client.delete(
                    collection_name=collection,
                    points_selector=filter_condition,
                )
            except Exception as e:
                print(f"[cleanup] Qdrant delete warning ({collection}): {e}")
    except Exception as e:
        print(f"[cleanup] Qdrant cleanup warning for {session_id}: {e}")


# ── ENDPOINTS ─────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}


@app.post("/session/start", response_model=StartSessionResponse)
async def start_session(
    resume: UploadFile = File(...),
    jd_text: str = Form(...),
    mode: str = Form("standard"),
):
    if mode not in Config.INTERVIEW_MODES:
        raise HTTPException(400, f"Invalid mode. Choose from: {list(Config.INTERVIEW_MODES.keys())}")

    suffix = os.path.splitext(resume.filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await resume.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        mode_config = Config.INTERVIEW_MODES[mode]

        engine = InterviewEngine()
        resume_text = engine.resume_parser.extract_text_from_pdf(tmp_path)

        initial_state = {
            "resume_text": resume_text,
            "jd_text": jd_text,
            "interview_mode": mode,
            "resume_data": None,
            "jd_requirements": None,
            "current_question_num": 0,
            "max_questions": 0,
            "questions_asked": [],
            "qa_history": [],
            "session_id": session_id,
            "user_id": "web_user",
            "current_question": "",
            "current_answer": "",
            "final_report": None,
            "overall_rating": None,
            "individual_ratings": None,
        }

        state = engine.parse_resume_node(initial_state)
        state = engine.parse_jd_node(state)
        state = engine.plan_interview_node(state)
        state = engine.generate_question_node(state)

        sessions[session_id] = {"engine": engine, "state": state, "mode": mode}

        return StartSessionResponse(
            session_id=session_id,
            mode=mode,
            max_questions=state["max_questions"],
            persona=mode_config["persona"],
            duration=mode_config["duration"],
            resume_summary={
                "skills": state["resume_data"]["skills"],
                "experience_years": state["resume_data"]["experience_years"],
                "summary": state["resume_data"]["summary"],
            },
            jd_summary={
                "required_skills": state["jd_requirements"]["required_skills"],
                "experience_level": state["jd_requirements"]["experience_level"],
                "summary": state["jd_requirements"]["summary"],
            },
        )
    finally:
        os.unlink(tmp_path)


@app.get("/session/{session_id}/question", response_model=NextQuestionResponse)
def get_current_question(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    sess = sessions[session_id]
    state = sess["state"]
    return NextQuestionResponse(
        question_id=state["current_question_num"],
        question=state["current_question"],
        total_questions=state["max_questions"],
        interview_complete=state["current_question_num"] > state["max_questions"],
    )


@app.post("/session/{session_id}/answer", response_model=AnswerResponse)
def submit_answer(session_id: str, body: AnswerRequest):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")

    sess = sessions[session_id]
    engine: InterviewEngine = sess["engine"]
    state = copy.deepcopy(sess["state"])

    state["current_answer"] = body.answer
    state = engine.evaluate_answer_node(state)

    latest_qa = state["qa_history"][-1]
    is_done = state["current_question_num"] >= state["max_questions"]

    if not is_done:
        state = engine.adaptation_node(state)
        state = engine.generate_question_node(state)

    sess["state"] = state

    return AnswerResponse(
        question_id=latest_qa["question_id"],
        is_dont_know=engine._is_dont_know_response(body.answer),
        technical_score=latest_qa["technical_score"],
        clarity_score=latest_qa["clarity_score"],
        confidence_score=latest_qa["confidence_score"],
        overall_score=latest_qa["overall_score"],
        feedback=latest_qa["feedback"],
        interview_complete=is_done,
    )


@app.get("/session/{session_id}/report", response_model=ReportResponse)
def get_report(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")

    sess = sessions[session_id]
    engine: InterviewEngine = sess["engine"]
    state = copy.deepcopy(sess["state"])

    state = engine.generate_feedback_node(state)
    sess["state"] = state

    performance = engine.neo4j.get_performance_summary(session_id)
    weaknesses = engine.neo4j.get_weaknesses_and_improvements(session_id)

    return ReportResponse(
        session_id=session_id,
        overall_rating=state["overall_rating"] or 0,
        individual_ratings=state["individual_ratings"] or {},
        final_report=state["final_report"] or "",
        performance_metrics=performance,
        weaknesses=weaknesses,
    )


@app.delete("/session/{session_id}")
def end_session(session_id: str):
    """
    Fix 4: Clean up session — delete all data from Neo4j + Qdrant,
    then remove from in-memory store.
    """
    if session_id in sessions:
        engine = sessions[session_id]["engine"]
        # Delete all persisted data for this session
        _delete_session_data(engine, session_id)
        del sessions[session_id]
    return {"deleted": True, "session_id": session_id}