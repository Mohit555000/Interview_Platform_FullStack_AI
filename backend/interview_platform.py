import os
import json
from typing import TypedDict, List, Dict, Any, Optional
from enum import Enum
import click
from pydantic import BaseModel, Field
import PyPDF2
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser, JsonOutputParser
from langgraph.graph import StateGraph, END
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from neo4j import GraphDatabase
import numpy as np
from datetime import datetime
from qdrant_client.models import Filter, FieldCondition, MatchValue
from dotenv import load_dotenv
import uuid
load_dotenv()

# ===================================================================
# CONFIGURATION
# ===================================================================

class Config:
    """Global configuration"""
    #OpenAi Configurations
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-api-key-here")
    #Qdrant Configurations
    QDRANT_HOST = os.getenv("QDRANT_HOST", "localhost")
    QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
    #NEO4j Configurations
    NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
    NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

    # ── V2: Removed hardcoded personas from INTERVIEW_MODES ──────
    # Persona is now generated dynamically from the JD in plan_interview_node
    INTERVIEW_MODES = {
        "quick":    {"duration": 10, "questions": 7},
        "standard": {"duration": 20, "questions": 12},
    }

    # Model settings
    LLM_MODEL = "gpt-4o-mini"
    EMBEDDING_MODEL = "text-embedding-3-small"
    EMBEDDING_DIMENSION = 1536

# ===================================================================
# DATA MODELS
# ===================================================================

class InterviewMode(str, Enum):
    QUICK = "quick"
    STANDARD = "standard"

class ResumeData(BaseModel):
    """Structured resume data"""
    skills: List[str]
    experience_years: int
    projects: List[str]
    education: str
    summary: str

class JDRequirements(BaseModel):
    """Structured job description data"""
    required_skills: List[str]
    preferred_skills: List[str]
    responsibilities: List[str]
    experience_level: str
    summary: str

class QuestionAnswer(BaseModel):
    """Q&A pair with evaluation"""
    question_id: int
    question: str
    answer: str
    technical_score: float
    clarity_score: float
    confidence_score: float
    overall_score: float
    feedback: str
    is_off_topic: bool = False

class InterviewState(TypedDict):
    """LangGraph state schema"""
    # Input data
    resume_text: str
    jd_text: str
    interview_mode: str
    current_answer_cleaned: Optional[str] 
    current_answer_enhanced:Optional[str];

    # Parsed data
    resume_data: Optional[Dict[str, Any]]
    jd_requirements: Optional[Dict[str, Any]]

    # Interview progress
    current_question_num: int
    max_questions: int
    questions_asked: List[str]
    qa_history: List[Dict[str, Any]]

    # Session data
    session_id: str
    user_id: str

    # Current interaction
    current_question: str
    current_answer: str

    # ── V2: Dynamic interviewer persona ──────────────────────────
    interviewer_persona: Optional[str]

    # Final output
    final_report: Optional[str]
    overall_rating: Optional[float]
    individual_ratings: Optional[Dict[str, float]]

# ===================================================================
# DATABASE MANAGERS
# ===================================================================

class QdrantManager:
    """Manages Qdrant vector database operations"""

    def __init__(self):
        self.client = QdrantClient(
            url=f"https://{Config.QDRANT_HOST}",
            api_key=Config.QDRANT_API_KEY,
            timeout=60
        )
        self.embeddings = OpenAIEmbeddings(
            model=Config.EMBEDDING_MODEL,
            openai_api_key=Config.OPENAI_API_KEY
        )
        self._setup_collections()

    def _setup_collections(self):
        """Create collections if they don't exist"""
        collections = ["resume_embeddings", "jd_embeddings", "qa_context"]
        for collection in collections:
            if not self.client.collection_exists(collection):
                self.client.create_collection(
                    collection_name=collection,
                    vectors_config=VectorParams(
                        size=Config.EMBEDDING_DIMENSION,
                        distance=Distance.COSINE
                    )
                )
            self.client.create_payload_index(
                collection_name=collection,
                field_name="session_id",
                field_schema="keyword"
            )

    def _batch_upsert(self, collection_name, points, batch_size=50):
        """Upsert points in batches to avoid timeout"""
        for i in range(0, len(points), batch_size):
            batch = points[i:i + batch_size]
            self.client.upsert(collection_name=collection_name, points=batch)

    def store_resume_data(self, session_id: str, resume_data: Dict[str, Any]):
        """Store resume embeddings"""
        points = []
        for skill in resume_data.get("skills", []):
            vector = self.embeddings.embed_query(skill)
            points.append(PointStruct(
                id=str(uuid.uuid4()), vector=vector,
                payload={"session_id": session_id, "type": "skill", "content": skill}
            ))
        for project in resume_data.get("projects", []):
            vector = self.embeddings.embed_query(project)
            points.append(PointStruct(
                id=str(uuid.uuid4()), vector=vector,
                payload={"session_id": session_id, "type": "project", "content": project}
            ))
        if points:
            self._batch_upsert("resume_embeddings", points)

    def store_jd_requirements(self, session_id: str, jd_requirements: Dict[str, Any]):
        """Store JD embeddings"""
        points = []
        for skill in jd_requirements.get("required_skills", []):
            vector = self.embeddings.embed_query(skill)
            points.append(PointStruct(
                id=str(uuid.uuid4()), vector=vector,
                payload={"session_id": session_id, "type": "requirement", "content": skill, "priority": "high"}
            ))
        if points:
            self._batch_upsert("jd_embeddings", points)

    def store_qa(self, session_id: str, qa_id: int, question: str, answer: str, score: float):
        """Store Q&A for context"""
        context = f"Q: {question}\nA: {answer}"
        vector = self.embeddings.embed_query(context)
        self.client.upsert(
            collection_name="qa_context",
            points=[PointStruct(
                id=str(uuid.uuid4()), vector=vector,
                payload={"session_id": session_id, "question": question, "answer": answer, "score": score}
            )]
        )

    def search_relevant_topics(self, query: str, session_id: str, limit: int = 3):
        query_vector = self.embeddings.embed_query(query)
        results = self.client.query_points(
            collection_name="jd_embeddings",
            query=query_vector,
            limit=limit,
            query_filter=Filter(must=[FieldCondition(key="session_id", match=MatchValue(value=session_id))])
        )
        return [r.payload.get("content") for r in results.points]


class Neo4jManager:
    """Manages Neo4j graph database operations"""

    def __init__(self):
        print("NEO4J_URI:", Config.NEO4J_URI)
        self.uri = Config.NEO4J_URI
        self.auth = (Config.NEO4J_USER, Config.NEO4J_PASSWORD)
        self._setup_constraints()

    def _new_driver(self):
        return GraphDatabase.driver(
            self.uri, auth=self.auth,
            max_connection_lifetime=100, connection_timeout=30,
        )

    def _get_session(self):
        return self._new_driver().session()

    def close(self):
        pass

    def _setup_constraints(self):
        driver = self._new_driver()
        try:
            with driver.session() as session:
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (u:User) REQUIRE u.session_id IS UNIQUE")
                session.run("CREATE CONSTRAINT IF NOT EXISTS FOR (s:Skill) REQUIRE s.name IS UNIQUE")
        finally:
            driver.close()

    def create_user_session(self, session_id: str, resume_data: Dict[str, Any]):
        driver = self._new_driver()
        try:
            with driver.session() as session:
                session.run(
                    "CREATE (u:User {session_id: $session_id, created_at: datetime()})",
                    session_id=session_id
                )
                for skill in resume_data.get("skills", []):
                    session.run("""
                        MERGE (s:Skill {name: $skill})
                        WITH s
                        MATCH (u:User {session_id: $session_id})
                        CREATE (u)-[:HAS_SKILL {proficiency: 0.7}]->(s)
                    """, skill=skill, session_id=session_id)
        finally:
            driver.close()

    def create_jd_requirements(self, session_id: str, jd_requirements: Dict[str, Any]):
        driver = self._new_driver()
        try:
            with driver.session() as session:
                for skill in jd_requirements.get("required_skills", []):
                    session.run("""
                        MERGE (s:Skill {name: $skill})
                        WITH s
                        MATCH (u:User {session_id: $session_id})
                        MERGE (r:Requirement {session_id: $session_id, skill: $skill, priority: 'high'})
                        CREATE (r)-[:REQUIRES]->(s)
                        CREATE (u)-[:TARGETS]->(r)
                    """, skill=skill, session_id=session_id)
        finally:
            driver.close()

    def store_qa_evaluation(self, session_id: str, qa_data: Dict[str, Any]):
        driver = self._new_driver()
        try:
            with driver.session() as session:
                session.run("""
                    MATCH (u:User {session_id: $session_id})
                    CREATE (q:Question {id: $qa_id, text: $question, asked_at: datetime()})
                    CREATE (a:Answer {
                        text: $answer,
                        technical_score: $technical_score,
                        clarity_score: $clarity_score,
                        confidence_score: $confidence_score,
                        overall_score: $overall_score
                    })
                    CREATE (u)-[:ASKED]->(q)
                    CREATE (q)-[:ANSWERED_BY]->(a)
                """,
                    session_id=session_id,
                    qa_id=qa_data["question_id"],
                    question=qa_data["question"],
                    answer=qa_data["answer"],
                    technical_score=qa_data["technical_score"],
                    clarity_score=qa_data["clarity_score"],
                    confidence_score=qa_data["confidence_score"],
                    overall_score=qa_data["overall_score"]
                )
                if qa_data["overall_score"] < 3.0:
                    weakness_area = qa_data.get("question", "Unknown topic")[:200]
                    score = qa_data["overall_score"]
                    if score <= 1.0:
                        recommendation = f"No answer provided. Study this topic from scratch: '{weakness_area[:80]}'"
                    elif score < 2.0:
                        recommendation = f"Very weak answer. Deep dive into: '{weakness_area[:80]}'"
                    else:
                        recommendation = f"Partial understanding. Revisit and practice: '{weakness_area[:80]}'"
                    session.run("""
                        MATCH (a:Answer)<-[:ANSWERED_BY]-(q:Question {id: $qa_id})
                        CREATE (w:Weakness {area: $weakness_area, severity: $severity})
                        CREATE (a)-[:REVEALS]->(w)
                        CREATE (w)-[:SUGGESTS]->(i:Improvement {recommendation: $recommendation})
                    """,
                        qa_id=qa_data["question_id"],
                        weakness_area=weakness_area,
                        severity="high" if score < 2.0 else "medium",
                        recommendation=recommendation
                    )
        finally:
            driver.close()

    def get_performance_summary(self, session_id: str) -> Dict[str, Any]:
        driver = self._new_driver()
        try:
            with driver.session() as session:
                result = session.run("""
                    MATCH (u:User {session_id: $session_id})-[:ASKED]->(q:Question)-[:ANSWERED_BY]->(a:Answer)
                    RETURN
                        AVG(a.technical_score) as avg_technical,
                        AVG(a.clarity_score) as avg_clarity,
                        AVG(a.confidence_score) as avg_confidence,
                        AVG(a.overall_score) as avg_overall,
                        COUNT(a) as total_questions
                """, session_id=session_id)
                record = result.single()
                if record:
                    return {
                        "avg_technical": round(record["avg_technical"] or 0, 2),
                        "avg_clarity": round(record["avg_clarity"] or 0, 2),
                        "avg_confidence": round(record["avg_confidence"] or 0, 2),
                        "avg_overall": round(record["avg_overall"] or 0, 2),
                        "total_questions": record["total_questions"]
                    }
                return {}
        finally:
            driver.close()

    def get_weaknesses_and_improvements(self, session_id: str) -> List[Dict[str, str]]:
        driver = self._new_driver()
        try:
            with driver.session() as session:
                result = session.run("""
                    MATCH (u:User {session_id: $session_id})-[:ASKED]->(:Question)-[:ANSWERED_BY]->(:Answer)-[:REVEALS]->(w:Weakness)
                    MATCH (w)-[:SUGGESTS]->(i:Improvement)
                    RETURN w.area as weakness, w.severity as severity, i.recommendation as improvement
                    ORDER BY w.severity DESC
                """, session_id=session_id)
                return [
                    {"weakness": r["weakness"], "severity": r["severity"], "improvement": r["improvement"]}
                    for r in result
                ]
        finally:
            driver.close()

# ===================================================================
# PARSERS
# ===================================================================

class ResumeParser:
    def __init__(self, llm):
        self.llm = llm

    def extract_text_from_pdf(self, pdf_path: str) -> str:
        try:
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                return "".join(page.extract_text() for page in reader.pages)
        except Exception as e:
            raise Exception(f"Error reading PDF: {str(e)}")

    def parse(self, resume_text: str) -> ResumeData:
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a resume parser. Extract the following information from the resume:
            - skills: List of technical skills
            - experience_years: Total years of experience (estimate if not explicit)
            - projects: List of key projects mentioned
            - education: Highest degree
            - summary: Brief 2-line summary of candidate's profile
            Return ONLY a valid JSON object with these exact keys."""),
            ("user", "{resume_text}")
        ])
        chain = prompt | self.llm | JsonOutputParser()
        result = chain.invoke({"resume_text": resume_text})
        return ResumeData(**result)


class JDParser:
    def __init__(self, llm):
        self.llm = llm

    def parse(self, jd_text: str) -> JDRequirements:
        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a job description parser. Extract:
            - required_skills: Must-have technical skills
            - preferred_skills: Nice-to-have skills
            - responsibilities: Key job responsibilities
            - experience_level: junior/mid/senior
            - summary: Brief 2-line summary of the role
            Return ONLY a valid JSON object with these exact keys."""),
            ("user", "{jd_text}")
        ])
        chain = prompt | self.llm | JsonOutputParser()
        result = chain.invoke({"jd_text": jd_text})
        return JDRequirements(**result)

# ===================================================================
# INTERVIEW ENGINE (LangGraph State Machine)
# ===================================================================

class InterviewEngine:
    """Main interview orchestration using LangGraph"""

    def __init__(self):
        self.llm = ChatOpenAI(
            model=Config.LLM_MODEL,
            openai_api_key=Config.OPENAI_API_KEY,
            temperature=0.7
        )
        self.qdrant = QdrantManager()
        self.neo4j = Neo4jManager()
        self.resume_parser = ResumeParser(self.llm)
        self.jd_parser = JDParser(self.llm)
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(InterviewState)
        workflow.add_node("parse_resume", self.parse_resume_node)
        workflow.add_node("parse_jd", self.parse_jd_node)
        workflow.add_node("plan_interview", self.plan_interview_node)
        workflow.add_node("generate_question", self.generate_question_node)
        workflow.add_node("get_answer", self.get_answer_node)
        workflow.add_node("evaluate_answer", self.evaluate_answer_node)
        workflow.add_node("adapt", self.adaptation_node)
        workflow.add_node("generate_feedback", self.generate_feedback_node)
        workflow.add_node("clean_response", self.clean_response_node)
        workflow.add_node("enhance_answer", self.enhance_answer_node)
        workflow.set_entry_point("parse_resume")
        workflow.add_edge("parse_resume", "parse_jd")
        workflow.add_edge("parse_jd", "plan_interview")
        workflow.add_edge("plan_interview", "generate_question")
        workflow.add_edge("generate_question", "get_answer")
        workflow.add_edge("get_answer", "clean_response")
        workflow.add_edge("clean_response", "enhance_answer")
        workflow.add_edge("enhance_answer", "evaluate_answer")
        workflow.add_edge("evaluate_answer", "adapt")
        workflow.add_conditional_edges(
            "adapt", self.should_continue,
            {"continue": "generate_question", "end": "generate_feedback"}
        )
        workflow.add_edge("generate_feedback", END)
        return workflow.compile()

    def parse_resume_node(self, state: InterviewState) -> InterviewState:
        click.echo("\n📄 Parsing resume...")
        resume_data = self.resume_parser.parse(state["resume_text"])
        state["resume_data"] = resume_data.dict()
        self.qdrant.store_resume_data(state["session_id"], state["resume_data"])
        self.neo4j.create_user_session(state["session_id"], state["resume_data"])
        click.echo(f"✓ Found {len(resume_data.skills)} skills, {resume_data.experience_years} years experience")
        return state

    def parse_jd_node(self, state: InterviewState) -> InterviewState:
        click.echo("\n📋 Analyzing job requirements...")
        jd_requirements = self.jd_parser.parse(state["jd_text"])
        state["jd_requirements"] = jd_requirements.dict()
        self.qdrant.store_jd_requirements(state["session_id"], state["jd_requirements"])
        self.neo4j.create_jd_requirements(state["session_id"], state["jd_requirements"])
        click.echo(f"✓ Identified {len(jd_requirements.required_skills)} required skills")
        return state

    def plan_interview_node(self, state: InterviewState) -> InterviewState:
        """Node: Plan interview — dynamically generate role-agnostic interviewer persona from JD"""
        mode_config = Config.INTERVIEW_MODES[state["interview_mode"]]
        state["max_questions"] = mode_config["questions"]
        state["current_question_num"] = 0
        state["qa_history"] = []
        state["questions_asked"] = []

        # ── V2: Generate persona dynamically from JD ─────────────
        # Works for any role: Data Scientist, DevOps, PM, ML Engineer, etc.
        persona_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert at identifying job roles and seniority levels.
Given a job description, return a short interviewer persona title (3–6 words).
Examples:
- 'Senior Data Scientist'
- 'ML Engineering Lead'
- 'DevOps Architect'
- 'Product Manager'
- 'Frontend Engineering Lead'
- 'Backend Software Engineer'
- 'Cloud Infrastructure Engineer'
- 'AI Research Scientist'

Return ONLY the title. No explanation, no punctuation, no extra words."""),
            ("user", f"Job Description:\n{state['jd_text'][:800]}\n\nInterviewer persona title:")
        ])
        persona_chain = persona_prompt | self.llm | StrOutputParser()
        persona = persona_chain.invoke({}).strip()

        # Fallback in case LLM returns something weird
        if not persona or len(persona) > 60:
            persona = f"{state['jd_requirements']['experience_level'].title()} Technical Interviewer"

        state["interviewer_persona"] = persona

        click.echo(f"\n🎯 Starting {mode_config['duration']}-minute interview as {persona}")
        click.echo(f"   Total questions: {mode_config['questions']}\n")

        return state

    def generate_question_node(self, state: InterviewState) -> InterviewState:
        """Node: Generate next question using dynamic persona"""
        mode_config = Config.INTERVIEW_MODES[state["interview_mode"]]

        # ── V2: Use dynamic persona from state ───────────────────
        persona = state.get("interviewer_persona") or "Technical Interviewer"

        # Get context from previous Q&As
        context = "\n".join([
            f"Q{i+1}: {qa['question']}\nA: {qa['answer'][:100]}... (Score: {qa['overall_score']})"
            for i, qa in enumerate(state["qa_history"][-3:])
        ])

        # Search relevant JD topics not yet covered
        covered_topics = [qa["question"] for qa in state["qa_history"]]
        relevant_topics = self.qdrant.search_relevant_topics(
            " ".join(covered_topics) if covered_topics else "general interview",
            state["session_id"]
        )

        # Check if last answer was weak — generate easier follow-up
        is_follow_up = False
        if state["qa_history"] and state["qa_history"][-1]["overall_score"] < 3.0:
            is_follow_up = True

        prompt = ChatPromptTemplate.from_messages([
            ("system", f"""You are a {persona} conducting a technical interview.

Candidate Profile:
- Skills: {', '.join(state['resume_data']['skills'])}
- Experience: {state['resume_data']['experience_years']} years
- Summary: {state['resume_data']['summary']}

Job Requirements:
- Required Skills: {', '.join(state['jd_requirements']['required_skills'])}
- Level: {state['jd_requirements']['experience_level']}
- Role Summary: {state['jd_requirements']['summary']}

Interview Progress: Question {state['current_question_num'] + 1}/{state['max_questions']}
Previous Q&As:
{context if context else 'None yet'}

{'IMPORTANT: The candidate struggled with the last question. Ask an EASIER follow-up on the same topic.' if is_follow_up else 'Ask a balanced question covering: ' + ', '.join(relevant_topics[:2]) if relevant_topics else 'Ask a relevant question based on the job requirements.'}

Generate ONE focused question relevant to this specific role. Be direct and clear. No preamble."""),
            ("user", "Generate the next interview question.")
        ])

        chain = prompt | self.llm | StrOutputParser()
        question = chain.invoke({}).strip()

        state["current_question"] = question
        state["current_question_num"] += 1
        state["questions_asked"].append(question)

        return state

    def get_answer_node(self, state: InterviewState) -> InterviewState:
        """Node: Get answer from user (CLI input)"""
        click.echo(f"\n{'='*70}")
        click.echo(f"Question {state['current_question_num']}/{state['max_questions']}")
        click.echo(f"{'='*70}")
        click.echo(f"\n{state['current_question']}\n")
        answer = click.prompt("Your answer", type=str)
        state["current_answer"] = answer
        return state

    def _is_dont_know_response(self, answer: str) -> bool:
        """Detect if the user is admitting they don't know the answer"""
        dont_know_phrases = [
            "i don't know", "i do not know", "i dont know",
            "i have no idea", "no idea", "not sure", "i'm not sure",
            "i am not sure", "i didn't understand", "i did not understand",
            "i don't understand", "i do not understand", "i cant answer",
            "i can't answer", "i cannot answer", "no clue", "beats me",
            "not familiar", "i'm unfamiliar", "never heard", "no knowledge",
            "i skip", "skip", "pass", "i pass"
        ]
        answer_lower = answer.strip().lower()
        return any(phrase in answer_lower for phrase in dont_know_phrases)

    def clean_response_node(self, state: InterviewState) -> InterviewState:
        """V2: Query Optimization — cleans filler words before evaluation."""
        original = state["current_answer"].strip()

        # Skip for short answers or don't-know responses
        if self._is_dont_know_response(original) or len(original.split()) < 10:
            state["current_answer_cleaned"] = original
            return state

        clean_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a technical interview response optimizer.
            Clean the candidate's answer by:
            1. Removing filler words: um, uh, like, you know, basically, literally, kind of, sort of
            2. Fixing obvious speech-to-text errors and typos
            3. Completing clearly incomplete sentences
            4. Preserving ALL technical content and meaning exactly
            5. Do NOT add new information or correct technical mistakes

            Return ONLY the cleaned answer text. No explanation."""),
            ("user", "Original answer:\n{answer}\n\nCleaned answer:")
        ])

        try:
            clean_chain = clean_prompt | self.llm | StrOutputParser()
            cleaned = clean_chain.invoke({"answer": original}).strip()
            if not cleaned or len(cleaned) < len(original) * 0.3:
                cleaned = original
            state["current_answer_cleaned"] = cleaned
        except Exception:
            state["current_answer_cleaned"] = original

        return state
    def enhance_answer_node(self, state: InterviewState) -> InterviewState:
        """
        Normalize and expand user answer for semantic evaluation.
        - Corrects STT terminology errors using question context
        - Maps equivalent concepts (e.g. 'event loop' ↔ 'async processing')
        - Expands implicit knowledge into explicit statements
        - Does NOT add information the user didn't convey
        """
        answer  = state.get("current_answer_cleaned") or state["current_answer"]
        question = state["current_question"]

        prompt = ChatPromptTemplate.from_messages([
            ("system", """You are a technical interview answer normalizer.

        Given a question and a candidate's spoken answer, produce an enhanced version that:
        1. Corrects likely speech-to-text errors using the question as context
        (e.g. "a vent loop" → "event loop", "use state" → "useState")
        2. Maps informal or equivalent terminology to standard technical terms
        (e.g. "that thing where functions remember stuff" → "closures/lexical scoping")
        3. Makes implicit correct knowledge explicit
        (e.g. if they describe how promises work without saying "promise" — add the term)
        4. Preserves the candidate's actual knowledge level — do NOT add concepts they didn't mention
        5. Preserves their gaps — if they missed something, keep it missing
    
        Return ONLY the enhanced answer. No explanation."""),
            ("user", f"Question: {question}\n\nCandidate's answer: {answer}\n\nEnhanced answer:")
        ])
    
        try:
            chain = prompt | self.llm | StrOutputParser()
            enhanced = chain.invoke({}).strip()
            if not enhanced or len(enhanced) < len(answer) * 0.3:
                enhanced = answer
            state["current_answer_enhanced"] = enhanced
        except Exception:
            state["current_answer_enhanced"] = answer

        return state
    def evaluate_answer_node(self, state: InterviewState) -> InterviewState:
        """Node: Evaluate answer quality"""
        click.echo("\n⏳ Evaluating your answer...")

        if self._is_dont_know_response(state["current_answer"]):
            click.echo("\n📝 No worries — noted that you weren't familiar with this topic.")
            qa_record = {
                "question_id": state["current_question_num"],
                "question": state["current_question"],
                "answer": state["current_answer"],
                "technical_score": 1.0,
                "clarity_score": 1.0,
                "confidence_score": 1.0,
                "overall_score": 1.0,
                "feedback": "Candidate indicated they did not know the answer. This topic may need further study.",
                "is_off_topic": False
            }
            state["qa_history"].append(qa_record)
            self.qdrant.store_qa(
                state["session_id"], state["current_question_num"],
                state["current_question"], state["current_answer"], 1.0
            )
            self.neo4j.store_qa_evaluation(state["session_id"], qa_record)
            click.echo("✓ Score: 1.0/5.0")
            return state
        eval_answer = (
            state.get("current_answer_enhanced")
            or state.get("current_answer_cleaned")
            or state["current_answer"]
        )
        # Check for off-topic
        off_topic_prompt = ChatPromptTemplate.from_messages([
            ("system", """Determine if the answer addresses the question.
Return ONLY a JSON with: {{"is_off_topic": true/false, "reason": "brief explanation"}}"""),
            ("user", "Question: {question}\n\nAnswer: {answer}")
        ])
        off_topic_chain = off_topic_prompt | self.llm | JsonOutputParser()
        off_topic_result = off_topic_chain.invoke({
            "question": state["current_question"],
            "answer": eval_answer
        })

        if off_topic_result.get("is_off_topic"):
            click.echo(f"\n⚠️  Off-topic detected: {off_topic_result['reason']} (continuing anyway)")

        # Evaluate answer
        eval_prompt = ChatPromptTemplate.from_messages([
            ("system", """Evaluate this interview answer on a scale of 1-5:

1. Technical Accuracy (40% weight): Correctness, depth, best practices
2. Clarity (30% weight): Structure, examples, conciseness
3. Confidence (20% weight): Fluency, terminology usage
4. Problem-Solving (10% weight): Logical thinking, edge cases

Return ONLY a JSON:
{{
    "technical_score": float,
    "clarity_score": float,
    "confidence_score": float,
    "problem_solving_score": float,
    "overall_score": float,
    "feedback": "Brief feedback on what was good/missing"
}}"""),
            ("user", "Question: {question}\n\nAnswer: {answer}")
        ])
        eval_chain = eval_prompt | self.llm | JsonOutputParser()
        evaluation = eval_chain.invoke({
            "question": state["current_question"],
            "answer": eval_answer
        })

        qa_record = {
            "question_id": state["current_question_num"],
            "question": state["current_question"],
            "answer": state["current_answer"],
            "technical_score": evaluation["technical_score"],
            "clarity_score": evaluation["clarity_score"],
            "confidence_score": evaluation["confidence_score"],
            "overall_score": evaluation["overall_score"],
            "feedback": evaluation["feedback"],
            "is_off_topic": off_topic_result.get("is_off_topic", False)
        }

        state["qa_history"].append(qa_record)
        self.qdrant.store_qa(
            state["session_id"], state["current_question_num"],
            state["current_question"], state["current_answer"],
            evaluation["overall_score"]
        )
        self.neo4j.store_qa_evaluation(state["session_id"], qa_record)
        click.echo(f"✓ Score: {evaluation['overall_score']:.1f}/5.0")
        return state

    def adaptation_node(self, state: InterviewState) -> InterviewState:
        return state

    def should_continue(self, state: InterviewState) -> str:
        if state["current_question_num"] >= state["max_questions"]:
            return "end"
        return "continue"

    def generate_feedback_node(self, state: InterviewState) -> InterviewState:
        """Node: Generate final comprehensive feedback"""
        click.echo("\n\n" + "="*70)
        click.echo("📊 GENERATING PERFORMANCE REPORT")
        click.echo("="*70 + "\n")

        performance = self.neo4j.get_performance_summary(state["session_id"])
        weaknesses = self.neo4j.get_weaknesses_and_improvements(state["session_id"])

        # ── V2: Include persona in feedback prompt for role-specific advice ──
        persona = state.get("interviewer_persona", "Technical Interviewer")

        qa_summary = "\n".join([
            f"Q{qa['question_id']}: {qa['question']}\nScore: {qa['overall_score']}/5\nFeedback: {qa['feedback']}\n"
            for qa in state["qa_history"]
        ])
        weakness_summary = "\n".join([
            f"- {w['weakness']} (Severity: {w['severity']})\n  → {w['improvement']}"
            for w in weaknesses
        ]) if weaknesses else "None identified"

        avg_technical = performance.get("avg_technical", 0)
        avg_clarity   = performance.get("avg_clarity", 0)
        avg_confidence = performance.get("avg_confidence", 0)
        avg_overall   = performance.get("avg_overall", 0)

        # ── Fix: build user message as f-string to avoid ChatPromptTemplate
        # variable substitution issues ({{}} rendering as literal {}) ──────
        feedback_prompt = ChatPromptTemplate.from_messages([
            ("system", f"""You are an interview coach providing detailed feedback for a {persona} interview.

Create a comprehensive feedback report with:
1. Overall performance summary
2. Strengths (specific examples from their answers)
3. Areas for improvement (detailed, actionable)
4. Specific study recommendations relevant to this role
5. Interview readiness assessment

Be encouraging but honest. Provide actionable next steps tailored to the {persona} role."""),
            ("user", f"""Interview Results:

Performance Metrics:
- Technical Accuracy: {avg_technical}/5
- Clarity: {avg_clarity}/5
- Confidence: {avg_confidence}/5
- Overall: {avg_overall}/5

Q&A History:
{qa_summary}

Identified Weaknesses:
{weakness_summary}

Generate detailed feedback report.""")
        ])

        feedback_chain = feedback_prompt | self.llm | StrOutputParser()
        detailed_feedback = feedback_chain.invoke({})

        state["final_report"] = detailed_feedback
        state["overall_rating"] = performance.get("avg_overall", 0)
        state["individual_ratings"] = {
            "technical": performance.get("avg_technical", 0),
            "clarity": performance.get("avg_clarity", 0),
            "confidence": performance.get("avg_confidence", 0)
        }
        return state

    def run_interview(self, resume_path: str, jd_text: str, mode: str, session_id: str) -> Dict[str, Any]:
        resume_text = self.resume_parser.extract_text_from_pdf(resume_path)
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
            "user_id": "cli_user",
            "current_question": "",
            "current_answer": "",
            "interviewer_persona": None,
            "final_report": None,
            "overall_rating": None,
            "individual_ratings": None
        }
        return self.graph.invoke(initial_state)

# ===================================================================
# CLI APPLICATION
# ===================================================================

@click.command()
@click.option('--mode', type=click.Choice(['quick', 'standard']), default='standard')
@click.option('--resume', type=click.Path(exists=True), required=True)
@click.option('--jd', type=str, required=True)
def main(mode: str, resume: str, jd: str):
    """AI-Powered Interview Platform - CLI Tool"""
    click.clear()
    click.echo("="*70)
    click.echo("🤖 AI-POWERED INTERVIEW PLATFORM - V2.0")
    click.echo("="*70)
    click.echo(f"\nMode: {mode.upper()}")
    click.echo(f"Resume: {resume}")
    click.echo(f"Duration: {Config.INTERVIEW_MODES[mode]['duration']} minutes")
    click.echo(f"Questions: {Config.INTERVIEW_MODES[mode]['questions']}")
    click.echo(f"Interviewer Persona: [Generated dynamically from JD]\n")

    if not click.confirm("Ready to start the interview?"):
        click.echo("Interview cancelled.")
        return

    if os.path.isfile(jd):
        with open(jd, 'r', encoding='utf-8') as f:
            jd_text = f.read()
    else:
        jd_text = jd

    session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    try:
        engine = InterviewEngine()
        final_state = engine.run_interview(resume, jd_text, mode, session_id)

        click.echo("\n" + "="*70)
        click.echo("📋 FINAL PERFORMANCE REPORT")
        click.echo("="*70 + "\n")
        click.echo(f"Interviewer Persona: {final_state.get('interviewer_persona', 'N/A')}")
        click.echo(f"Overall Score: {final_state['overall_rating']:.1f}/5.0\n")
        click.echo("Individual Ratings:")
        click.echo(f"  • Technical Accuracy: {final_state['individual_ratings']['technical']:.1f}/5.0")
        click.echo(f"  • Clarity: {final_state['individual_ratings']['clarity']:.1f}/5.0")
        click.echo(f"  • Confidence: {final_state['individual_ratings']['confidence']:.1f}/5.0")
        click.echo("\n" + "-"*70 + "\n")
        click.echo(final_state['final_report'])
        click.echo("\n" + "="*70)
        engine.neo4j.close()

    except Exception as e:
        click.echo(f"\n❌ Error: {str(e)}", err=True)
        import traceback
        traceback.print_exc()


@click.command()
def setup():
    """Initialize Qdrant and Neo4j databases"""
    click.echo("🔧 Setting up databases...\n")
    try:
        qdrant = QdrantManager()
        click.echo("✓ Qdrant connected and collections created")
    except Exception as e:
        click.echo(f"❌ Qdrant error: {e}")
        return
    try:
        neo4j = Neo4jManager()
        click.echo("✓ Neo4j connected and constraints created")
        neo4j.close()
    except Exception as e:
        click.echo(f"❌ Neo4j error: {e}")
        return
    click.echo("\n✅ All databases initialized successfully!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        setup()
    else:
        main()
