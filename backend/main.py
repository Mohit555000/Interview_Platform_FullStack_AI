"""
FastAPI Backend for AI Interview Platform - Version 2
Adds multi-provider LLM support (OpenAI, Anthropic, Gemini)
and time-based interview sessions with custom duration.
"""

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import tempfile
import copy
import os
import uuid
from datetime import datetime

from interview_platform import InterviewEngine, Config

app = FastAPI(title="InterviewAI API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions: dict = {}


# ── LLM FACTORY ───────────────────────────────────────────────────

def build_llm(provider: str, model: str, api_key: str):
    provider = (provider or 'openai').lower()
    if provider == 'openai':
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model or 'gpt-4o', api_key=api_key or os.getenv('OPENAI_API_KEY'), temperature=0.7)
    elif provider == 'anthropic':
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model or 'claude-sonnet-4-5', api_key=api_key or os.getenv('ANTHROPIC_API_KEY'), temperature=0.7)
    elif provider == 'gemini':
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model or 'gemini-1.5-pro', google_api_key=api_key or os.getenv('GOOGLE_API_KEY'), temperature=0.7)
    else:
        raise HTTPException(400, f"Unsupported provider: {provider}. Choose openai, anthropic, or gemini.")


def inject_llm(engine: InterviewEngine, provider: str, model: str, api_key: str):
    if not api_key:
        return
    llm = build_llm(provider, model, api_key)
    if hasattr(engine, 'llm'):
        engine.llm = llm
    if hasattr(engine, '_build_chains'):
        engine._build_chains()
    print(f"[llm] Using {provider} / {model}")


# ── MODELS ────────────────────────────────────────────────────────

class StartSessionResponse(BaseModel):
    session_id: str
    mode: str
    duration: int          # minutes — used by frontend timer
    persona: str
    resume_summary: dict
    jd_summary: dict
    llm_provider: str
    llm_model: str

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


# ── CLEANUP HELPER ────────────────────────────────────────────────

def _delete_session_data(engine: InterviewEngine, session_id: str):
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
            neo_session.run("MATCH (s:Skill) WHERE NOT (s)--() DELETE s")
        driver.close()
        print(f"[cleanup] Neo4j cleared for {session_id}")
    except Exception as e:
        print(f"[cleanup] Neo4j warning: {e}")
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        f = Filter(must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))])
        for col in ["resume_embeddings", "jd_embeddings", "qa_context"]:
            try:
                engine.qdrant.client.delete(collection_name=col, points_selector=f)
            except Exception as e:
                print(f"[cleanup] Qdrant warning ({col}): {e}")
        print(f"[cleanup] Qdrant cleared for {session_id}")
    except Exception as e:
        print(f"[cleanup] Qdrant warning: {e}")


# ── ENDPOINTS ─────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@app.post("/session/start", response_model=StartSessionResponse)
async def start_session(
    resume: UploadFile = File(...),
    jd_text: str = Form(...),
    mode: str = Form("standard"),
    custom_duration: Optional[int] = Form(None),
    llm_provider: Optional[str] = Form(None),
    llm_model: Optional[str] = Form(None),
    llm_api_key: Optional[str] = Form(None),
):
    valid_modes = list(Config.INTERVIEW_MODES.keys()) + ["custom"]
    if mode not in valid_modes:
        raise HTTPException(400, f"Invalid mode. Choose from: {valid_modes}")

    # Resolve duration
    if mode == "custom":
        if not custom_duration or not (5 <= custom_duration <= 60):
            raise HTTPException(400, "custom_duration must be between 5 and 60 minutes.")
        duration = custom_duration
    else:
        duration = custom_duration if (custom_duration and 5 <= custom_duration <= 60) \
                   else Config.INTERVIEW_MODES[mode]["duration"]

    # V2: time-based — no question ceiling
    max_questions = 999

    suffix = os.path.splitext(resume.filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await resume.read()
        tmp.write(content)
        tmp_path = tmp.name

    try:
        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        engine = InterviewEngine()
        inject_llm(engine, llm_provider or 'openai', llm_model or '', llm_api_key or '')

        resume_text = engine.resume_parser.extract_text_from_pdf(tmp_path)

        initial_state = {
            "resume_text": resume_text,
            "jd_text": jd_text,
            "interview_mode": mode if mode != "custom" else "standard",
            "resume_data": None,
            "jd_requirements": None,
            "current_question_num": 0,
            "max_questions": max_questions,
            "questions_asked": [],
            "qa_history": [],
            "session_id": session_id,
            "user_id": "web_user",
            "current_question": "",
            "current_answer": "",
            "current_answer_cleaned": None,
            "interviewer_persona": None,
            "final_report": None,
            "overall_rating": None,
            "individual_ratings": None,
        }

        state = engine.parse_resume_node(initial_state)
        state = engine.parse_jd_node(state)
        state = engine.plan_interview_node(state)
        state = engine.generate_question_node(state)

        sessions[session_id] = {
            "engine": engine,
            "state": state,
            "mode": mode,
            "duration": duration,
            "llm_provider": llm_provider or 'openai',
            "llm_model": llm_model or '',
        }

        return StartSessionResponse(
            session_id=session_id,
            mode=mode,
            duration=duration,
            persona=state.get("interviewer_persona", "Technical Interviewer"),
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
            llm_provider=llm_provider or 'openai',
            llm_model=llm_model or '',
        )
    finally:
        os.unlink(tmp_path)


@app.get("/session/{session_id}/question", response_model=NextQuestionResponse)
def get_current_question(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    state = sessions[session_id]["state"]
    return NextQuestionResponse(
        question_id=state["current_question_num"],
        question=state["current_question"],
        total_questions=state["max_questions"],
        interview_complete=False,  # V2: timer-driven, not question-count driven
    )


@app.post("/session/{session_id}/answer", response_model=AnswerResponse)
def submit_answer(session_id: str, body: AnswerRequest):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")

    sess = sessions[session_id]
    engine: InterviewEngine = sess["engine"]
    state = copy.deepcopy(sess["state"])

    state["current_answer"] = body.answer
    state["current_answer_cleaned"] = None

    # V2: clean → evaluate → next question (always — timer controls the end)
    state = engine.clean_response_node(state)
    state = engine.evaluate_answer_node(state)
    state = engine.adaptation_node(state)
    state = engine.generate_question_node(state)

    sess["state"] = state
    latest_qa = state["qa_history"][-1]

    return AnswerResponse(
        question_id=latest_qa["question_id"],
        is_dont_know=engine._is_dont_know_response(body.answer),
        technical_score=latest_qa["technical_score"],
        clarity_score=latest_qa["clarity_score"],
        confidence_score=latest_qa["confidence_score"],
        overall_score=latest_qa["overall_score"],
        feedback=latest_qa["feedback"],
        interview_complete=False,  # V2: always false — frontend timer decides
    )


@app.post("/session/{session_id}/end")
def end_interview_early(session_id: str):
    """
    V2: Called by frontend when user clicks End Interview OR timer expires after final answer.
    Pre-generates the report so /report returns instantly.
    """
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")

    sess = sessions[session_id]
    engine: InterviewEngine = sess["engine"]
    state = copy.deepcopy(sess["state"])

    state = engine.generate_feedback_node(state)
    sess["state"] = state

    print(f"[end] {session_id} — {len(state['qa_history'])} questions answered")
    return {"ended": True, "session_id": session_id, "questions_answered": len(state["qa_history"])}


@app.get("/session/{session_id}/report", response_model=ReportResponse)
def get_report(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")

    sess = sessions[session_id]
    engine: InterviewEngine = sess["engine"]
    state = copy.deepcopy(sess["state"])

    # If /end was already called, report is pre-generated — skip regeneration
    if not state.get("final_report"):
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
def delete_session(session_id: str):
    if session_id in sessions:
        engine = sessions[session_id]["engine"]
        _delete_session_data(engine, session_id)
        del sessions[session_id]
    return {"deleted": True, "session_id": session_id}