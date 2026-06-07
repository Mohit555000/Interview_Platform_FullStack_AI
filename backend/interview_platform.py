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
import numpy as np
from datetime import datetime
from dotenv import load_dotenv
import uuid
from pinecone_manager import PineconeManager
from kuzu_manager import KuzuManager
load_dotenv()

# ===================================================================
# CONFIGURATION
# ===================================================================

class Config:
    """Global configuration"""
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "your-api-key-here")

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
    current_answer_cleaned: Optional[str]   # after filler removal
    current_answer_enhanced: Optional[str]  # after semantic normalization

    # ── V2: Dynamic interviewer persona ──────────────────────────
    interviewer_persona: Optional[str]

    # ── V2: Query translation results (multi-query retrieval) ────
    translated_queries: Optional[List[str]]

    # Final output
    final_report: Optional[str]
    overall_rating: Optional[float]
    individual_ratings: Optional[Dict[str, float]]

# ===================================================================
# DATABASE MANAGERS  (PineconeManager / KuzuManager — imported above)
# ===================================================================

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

    def __init__(self, openai_api_key: str = None):
        key = openai_api_key or Config.OPENAI_API_KEY
        self.llm = ChatOpenAI(
            model=Config.LLM_MODEL,
            openai_api_key=key,
            temperature=0.7
        )
        self.qdrant = PineconeManager(openai_api_key=key)
        self.neo4j = KuzuManager()
        self.resume_parser = ResumeParser(self.llm)
        self.jd_parser = JDParser(self.llm)
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        workflow = StateGraph(InterviewState)
        workflow.add_node("parse_resume", self.parse_resume_node)
        workflow.add_node("parse_jd", self.parse_jd_node)
        workflow.add_node("plan_interview", self.plan_interview_node)
        workflow.add_node("translate_query", self.translate_query_node)   # ← new
        workflow.add_node("generate_question", self.generate_question_node)
        workflow.add_node("get_answer", self.get_answer_node)
        workflow.add_node("evaluate_answer", self.evaluate_answer_node)
        workflow.add_node("adapt", self.adaptation_node)
        workflow.add_node("generate_feedback", self.generate_feedback_node)
        workflow.set_entry_point("parse_resume")
        workflow.add_edge("parse_resume", "parse_jd")
        workflow.add_edge("parse_jd", "plan_interview")
        workflow.add_edge("plan_interview", "translate_query")            # ← new
        workflow.add_edge("translate_query", "generate_question")         # ← new
        workflow.add_edge("generate_question", "get_answer")
        workflow.add_edge("get_answer", "evaluate_answer")
        workflow.add_edge("evaluate_answer", "adapt")
        workflow.add_conditional_edges(
            "adapt", self.should_continue,
            {"continue": "translate_query", "end": "generate_feedback"}  # ← loops back to translate
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

    def translate_query_node(self, state: InterviewState) -> InterviewState:
        """
        Node: Query Translation/Enhancement Layer (Retrieval Side)

        Sits before generate_question_node.

        Simple explanation:
        We want to find JD topics not yet covered. Instead of one search,
        we generate 3 different search queries from different angles:

        1. Direct gap query — what topics from JD haven't been asked yet?
        2. Prerequisite query — what foundational skills relate to what's been asked?
        3. Advanced query — what deeper topics build on the candidate's strong answers?

        Then we run all 3 searches in parallel and merge using RRF reranking.
        Topics that appear highly in multiple searches bubble to the top.

        Also applies sub-query decomposition — if covered topics are complex
        (e.g. "React performance optimization"), breaks into atomic sub-queries
        (e.g. "React memo", "useMemo", "re-render prevention") for better recall.
        """
        covered_topics  = [qa["question"] for qa in state["qa_history"]]
        strong_topics   = [qa["question"] for qa in state["qa_history"] if qa["overall_score"] >= 3.5]
        weak_topics     = [qa["question"] for qa in state["qa_history"] if qa["overall_score"] < 3.0]
        jd_skills       = state["jd_requirements"]["required_skills"]
        resume_skills   = state["resume_data"]["skills"]
        experience      = state["resume_data"]["experience_years"]

        # ── If no history yet, return simple starter queries ─────────
        if not covered_topics:
            state["translated_queries"] = [
                " ".join(jd_skills[:3]),
                state["jd_requirements"]["summary"],
                state["jd_requirements"]["experience_level"] + " " + " ".join(jd_skills[:2])
            ]
            return state

        # ── Use LLM to generate 3 query variations ───────────────────
        translation_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert technical interview query translator.

        Given the interview context, generate exactly 3 different search queries
        to find the most relevant JD topics not yet covered.

        Each query should approach the topic gap from a DIFFERENT angle:
        Query 1 (Gap-based): Focus on JD required skills not yet asked about
        Query 2 (Prerequisite-based): Focus on foundational concepts that support already-covered topics
        Query 3 (Progression-based): Focus on advanced topics that build on the candidate's strong answers

        Rules:
        - Each query must be 3-8 words max
        - Each query must be meaningfully different from the others
        - Use technical terminology from the JD and resume
        - Return ONLY a JSON array of 3 strings: ["query1", "query2", "query3"]"""),
                ("user", f"""JD Required Skills: {', '.join(jd_skills)}
        Candidate Skills: {', '.join(resume_skills[:8])}
        Experience: {experience} years
        Already covered topics: {', '.join(covered_topics[-5:]) if covered_topics else 'None'}
        Strong areas (score >= 3.5): {', '.join(strong_topics[-3:]) if strong_topics else 'None'}
        Weak areas (score < 3.0): {', '.join(weak_topics[-3:]) if weak_topics else 'None'}

        Generate 3 search queries to find uncovered relevant topics:""")
            ])

        try:
            translation_chain = translation_prompt | self.llm | JsonOutputParser()
            queries = translation_chain.invoke({})

            # Validate — must be a list of 3 non-empty strings
            if not isinstance(queries, list) or len(queries) < 1:
                raise ValueError("Invalid query format from LLM")

            queries = [q.strip() for q in queries if isinstance(q, str) and q.strip()]

            # ── Sub-query decomposition for complex queries ───────────
            # If any query is long/complex, add atomic sub-queries
            decomposed = []
            for q in queries:
                decomposed.append(q)
                if len(q.split()) > 5:
                    # Break into smaller atomic queries
                    words = q.split()
                    decomposed.append(" ".join(words[:3]))
                    decomposed.append(" ".join(words[3:]))

            # Always add a direct JD skills query as safety fallback
            decomposed.append(" ".join(jd_skills[:4]))

            state["translated_queries"] = decomposed
            click.echo(f"✓ Query translation: {len(decomposed)} search queries generated")

        except Exception as e:
            click.echo(f"⚠️ Query translation failed, using fallback: {e}")
            # Fallback to simple queries
            state["translated_queries"] = [
                " ".join(covered_topics[-2:]) if covered_topics else "general interview",
                " ".join(jd_skills[:3]),
                state["jd_requirements"]["summary"][:50]
            ]

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

        # ── Use translated queries for multi-search retrieval ────────
        # Falls back to simple search if translated_queries not available
        translated_queries = state.get("translated_queries", [])
        if translated_queries:
            relevant_topics = self.qdrant.multi_search_relevant_topics(
                queries=translated_queries,
                session_id=state["session_id"],
                limit_per_query=5,
                final_limit=3
            )
            click.echo(f"✓ Retrieved {len(relevant_topics)} topics via multi-query RRF")
        else:
            # Fallback to single search
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

    def enhance_answer_node(self, state: InterviewState) -> InterviewState:
        """
        Node: Semantic Answer Normalization (Answer Enhancement Layer)

        Sits between clean_response_node and evaluate_answer_node.

        Simple explanation:
        - Takes the cleaned answer + the question that was asked
        - Fixes STT terminology errors using the question as context
          e.g. "avent loop" → "event loop"
        - Maps informal descriptions to proper technical terms
          e.g. "that async thingy" → "event loop / async execution"
        - Makes implied correct knowledge explicit
          e.g. user describes how closures work → adds the term "closure"
        - NEVER adds knowledge the user didn't have
          if they missed something, it stays missing

        Result: evaluator judges understanding, not vocabulary or pronunciation.
        Original answer is always preserved in current_answer for display.
        """
        original = state.get("current_answer_cleaned") or state["current_answer"]

        # Skip for don't-know responses — nothing to enhance
        if self._is_dont_know_response(original):
            state["current_answer_enhanced"] = original
            return state

        # Skip very short answers — not enough content to enhance
        if len(original.split()) < 8:
            state["current_answer_enhanced"] = original
            return state

        question = state["current_question"]
        role     = state.get("interviewer_persona", "Technical Interviewer")

        enhance_prompt = ChatPromptTemplate.from_messages([
            ("system", f"""You are a semantic answer normalizer for a {role} technical interview.

        Your job is to produce an enhanced version of the candidate's spoken answer that:

        1. CORRECT STT ERRORS using the question as context
        - Use the question to infer what technical terms the candidate likely said
        - Example: question asks about "event loop" → "avent loop" → "event loop"
        - Example: "use state hook" → "useState hook"

        2. MAP INFORMAL TERMS to standard technical vocabulary
        - "that async thingy where it doesn't get stuck" → "non-blocking async execution / event loop"
        - "the thing that remembers variables" → "closure / lexical scoping"
        - "when you split your app into pieces" → "component-based architecture / modularization"

        3. MAKE IMPLIED KNOWLEDGE EXPLICIT
        - If the candidate correctly describes a concept without naming it, add the name
        - If they explain HOW something works correctly, make sure the WHAT is stated

        4. STRICT RULES — do NOT violate these  :
        - Do NOT add concepts the candidate did not mention or imply
        - Do NOT fix incorrect technical statements — keep their mistakes
        - Do NOT increase the apparent depth of their answer beyond what they said
        - Do NOT change the structure or flow significantly
        - If the answer is already clear and technical, return it as-is

        Return ONLY the enhanced answer text. No explanation, no preamble."""),
                ("user", f"Question asked: {question}\n\nCandidate's answer: {original}\n\nEnhanced answer:")
            ])

        try:
            enhance_chain = enhance_prompt | self.llm | StrOutputParser()
            enhanced = enhance_chain.invoke({}).strip()

            # Safety checks — fall back to original if enhancement looks wrong
            if not enhanced:
                enhanced = original
            elif len(enhanced) > len(original) * 2.5:
                # Enhanced is more than 2.5x longer — likely hallucinating content
                enhanced = original
            elif len(enhanced) < len(original) * 0.3:
                # Enhanced is too short — something went wrong
                enhanced = original

            state["current_answer_enhanced"] = enhanced
            click.echo("✓ Answer semantically normalized")

        except Exception as e:
            click.echo(f"⚠️ Enhancement skipped: {e}")
            state["current_answer_enhanced"] = original

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

    def evaluate_answer_node(self, state: InterviewState) -> InterviewState:
        """Node: Evaluate answer — uses enhanced answer for scoring, original for display"""
        click.echo("\n⏳ Evaluating your answer...")

        if self._is_dont_know_response(state["current_answer"]):
            click.echo("\n📝 No worries — noted that you weren't familiar with this topic.")
            qa_record = {
                "question_id": state["current_question_num"],
                "question": state["current_question"],
                "answer": state["current_answer"],   # always show original
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

        # ── Use enhanced answer for evaluation (better semantic matching) ──
        # Falls back: enhanced → cleaned → raw original
        eval_answer = (
            state.get("current_answer_enhanced")
            or state.get("current_answer_cleaned")
            or state["current_answer"]
        )

        # Off-topic check using enhanced answer
        off_topic_prompt = ChatPromptTemplate.from_messages([
            ("system", """Determine if the answer addresses the question.
Return ONLY a JSON with: {{"is_off_topic": true/false, "reason": "brief explanation"}}"""),
            ("user", "Question: {question}\n\nAnswer: {answer}")
        ])
        off_topic_chain = off_topic_prompt | self.llm | JsonOutputParser()
        off_topic_result = off_topic_chain.invoke({
            "question": state["current_question"],
            "answer": eval_answer    # ← enhanced
        })

        if off_topic_result.get("is_off_topic"):
            click.echo(f"\n⚠️  Off-topic detected: {off_topic_result['reason']} (continuing anyway)")

        # Evaluate using enhanced answer
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
            "answer": eval_answer    # ← enhanced
        })

        qa_record = {
            "question_id": state["current_question_num"],
            "question": state["current_question"],
            "answer": state["current_answer"],   # ← always original for display
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
    """Initialize Pinecone index and KuzuDB schema"""
    click.echo("🔧 Setting up databases...\n")
    try:
        PineconeManager()
        click.echo("✓ Pinecone index ready")
    except Exception as e:
        click.echo(f"❌ Pinecone error: {e}")
        return
    try:
        KuzuManager()
        click.echo("✓ KuzuDB schema initialized")
    except Exception as e:
        click.echo(f"❌ KuzuDB error: {e}")
        return
    click.echo("\n✅ All databases initialized successfully!")


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "setup":
        setup()
    else:
        main()