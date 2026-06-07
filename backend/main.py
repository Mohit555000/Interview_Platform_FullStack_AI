"""
FastAPI Backend for AI Interview Platform - Version 2
Multi-provider LLM, time-based sessions, OpenAI TTS (fable), backend STT, JD PDF upload.
"""

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional
import tempfile
import copy
import os
import io
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
        raise HTTPException(400, f"Unsupported provider: {provider}.")


def inject_llm(engine: InterviewEngine, provider: str, model: str, api_key: str):
    if not api_key:
        return
    llm = build_llm(provider, model, api_key)
    if hasattr(engine, 'llm'):
        engine.llm = llm
    if hasattr(engine, '_build_chains'):
        engine._build_chains()
    print(f"[llm] Using {provider} / {model}")


# ── PDF TEXT EXTRACTION ───────────────────────────────────────────

def extract_pdf_text(file_path: str) -> str:
    """Extract text from a PDF file using PyPDF2."""
    import PyPDF2
    with open(file_path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        return "".join(page.extract_text() or "" for page in reader.pages)


# ── MODELS ────────────────────────────────────────────────────────

class StartSessionResponse(BaseModel):
    session_id: str
    mode: str
    duration: int
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

class TTSRequest(BaseModel):
    text: str


# ── CLEANUP ───────────────────────────────────────────────────────

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


# ── TTS: OpenAI gpt-4o-mini-tts with fable voice ─────────────────
@app.post("/tts")
async def text_to_speech(body: TTSRequest):
    """
    Convert text to speech using OpenAI TTS (gpt-4o-mini-tts, fable voice).
    Returns MP3 audio stream.
    """
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice="fable",
        input=body.text,
        response_format="mp3",
    )

    audio_bytes = response.content
    return StreamingResponse(
        io.BytesIO(audio_bytes),
        media_type="audio/mpeg",
        headers={"Content-Disposition": "inline; filename=speech.mp3"}
    )


# ── STT: Google Speech Recognition via speech_recognition lib ─────
@app.post("/session/{session_id}/transcribe")
async def transcribe_audio(session_id: str, audio: UploadFile = File(...)):
    """
    Transcribe audio blob using Google Speech Recognition.
    Accepts WebM audio from MediaRecorder, converts to WAV via pydub (requires ffmpeg).
    """
    import traceback
    import shutil
    import speech_recognition as sr
    import speech_recognition.audio as sr_audio
    from pydub import AudioSegment
    from pydub.utils import which

    # Explicitly set ffmpeg path for pydub (Homebrew on Apple Silicon)
    AudioSegment.converter = which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"
    AudioSegment.ffprobe   = which("ffprobe") or "/opt/homebrew/bin/ffprobe"

    # Override bundled x86 flac-mac with Homebrew ARM64 native binary
    system_flac = shutil.which("flac") or "/opt/homebrew/bin/flac"
    sr_audio.get_flac_converter = lambda: system_flac

    if session_id not in sessions:
        raise HTTPException(404, "Session not found")

    suffix = os.path.splitext(audio.filename)[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        content = await audio.read()
        tmp.write(content)
        tmp_path = tmp.name

    wav_path = tmp_path + ".wav"
    try:
        # Convert WebM → WAV using pydub
        audio_seg = AudioSegment.from_file(tmp_path)
        audio_seg = audio_seg.set_channels(1).set_frame_rate(16000)
        audio_seg.export(wav_path, format="wav")

        # Transcribe with Google Speech Recognition (free)
        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_path) as source:
            audio_data = recognizer.record(source)

        transcript = recognizer.recognize_google(audio_data)
        return {"transcript": transcript}

    except sr.UnknownValueError:
        return {"transcript": ""}  # Nothing recognized — frontend handles empty
    except sr.RequestError as e:
        raise HTTPException(503, f"Google Speech Recognition unavailable: {e}")
    except Exception as e:
        print(f"[TRANSCRIBE ERROR] {type(e).__name__}: {e}")
        traceback.print_exc()
        raise HTTPException(500, f"Transcription error: {str(e)}")
    finally:
        os.unlink(tmp_path)
        if os.path.exists(wav_path):
            os.unlink(wav_path)


# ── SESSION START ─────────────────────────────────────────────────
@app.post("/session/start", response_model=StartSessionResponse)
async def start_session(
    resume: UploadFile = File(...),
    jd_file: UploadFile = File(...),          # ← JD is now a PDF upload
    mode: str = Form("standard"),
    custom_duration: Optional[int] = Form(None),
    llm_provider: Optional[str] = Form(None),
    llm_model: Optional[str] = Form(None),
    llm_api_key: Optional[str] = Form(None),
):
    valid_modes = list(Config.INTERVIEW_MODES.keys()) + ["custom"]
    if mode not in valid_modes:
        raise HTTPException(400, f"Invalid mode. Choose from: {valid_modes}")

    if mode == "custom":
        if not custom_duration or not (5 <= custom_duration <= 60):
            raise HTTPException(400, "custom_duration must be between 5 and 60 minutes.")
        duration = custom_duration
    else:
        duration = custom_duration if (custom_duration and 5 <= custom_duration <= 60) \
                   else Config.INTERVIEW_MODES.get(mode, {}).get("duration", 20)

    max_questions = 999

    # Save resume PDF
    resume_suffix = os.path.splitext(resume.filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=resume_suffix) as tmp:
        tmp.write(await resume.read())
        resume_path = tmp.name

    # Save JD PDF and extract text
    jd_suffix = os.path.splitext(jd_file.filename)[1] or ".pdf"
    with tempfile.NamedTemporaryFile(delete=False, suffix=jd_suffix) as tmp:
        tmp.write(await jd_file.read())
        jd_path = tmp.name

    try:
        jd_text = extract_pdf_text(jd_path)
        if not jd_text.strip():
            raise HTTPException(400, "Could not extract text from JD PDF. Please ensure it is a text-based PDF.")

        session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"

        engine = InterviewEngine()
        inject_llm(engine, llm_provider or 'openai', llm_model or '', llm_api_key or '')

        resume_text = engine.resume_parser.extract_text_from_pdf(resume_path)

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
            "current_answer_enhanced": None,
            "interviewer_persona": None,
            "translated_queries": None,
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
        os.unlink(resume_path)
        os.unlink(jd_path)


@app.get("/session/{session_id}/question", response_model=NextQuestionResponse)
def get_current_question(session_id: str):
    if session_id not in sessions:
        raise HTTPException(404, "Session not found")
    state = sessions[session_id]["state"]
    return NextQuestionResponse(
        question_id=state["current_question_num"],
        question=state["current_question"],
        total_questions=state["max_questions"],
        interview_complete=False,
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
    state["current_answer_enhanced"] = None

    state = engine.enhance_answer_node(state)   # ← semantic normalization
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
        interview_complete=False,
    )


@app.post("/session/{session_id}/end")
def end_interview_early(session_id: str):
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
    if not state.get("final_report"):
        state = engine.generate_feedback_node(state)
        sess["state"] = state
    performance = engine.neo4j.get_performance_summary(session_id)
    weaknesses  = engine.neo4j.get_weaknesses_and_improvements(session_id)
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
    sess = sessions.pop(session_id, None)   # safe — no KeyError
    if sess:
        # Session still in memory — full cleanup
        _delete_session_data(sess["engine"], session_id)
    else:
        # Session already removed from memory (e.g. by /end endpoint)
        # but DB data may still exist — create a temp engine to clean up
        try:
            engine = InterviewEngine()
            _delete_session_data(engine, session_id)
        except Exception as e:
            print(f"[cleanup] Fallback cleanup warning: {e}")
    return {"deleted": True, "session_id": session_id}