import kuzu
from datetime import datetime
from typing import Dict, Any, List
from config import KUZU_DATA_DIR


class KuzuManager:
    _db = None
    _conn = None

    def __init__(self):
        if KuzuManager._db is None:
            KuzuManager._db = kuzu.Database(str(KUZU_DATA_DIR))
            KuzuManager._conn = kuzu.Connection(KuzuManager._db)
            self._setup_schema()

    def _setup_schema(self):
        conn = KuzuManager._conn
        node_tables = [
            "CREATE NODE TABLE IF NOT EXISTS User (session_id STRING, created_at STRING, PRIMARY KEY(session_id))",
            "CREATE NODE TABLE IF NOT EXISTS Skill (name STRING, PRIMARY KEY(name))",
            "CREATE NODE TABLE IF NOT EXISTS Question (question_key STRING, session_id STRING, question_id INT64, text STRING, asked_at STRING, PRIMARY KEY(question_key))",
            "CREATE NODE TABLE IF NOT EXISTS Answer (answer_key STRING, text STRING, technical_score DOUBLE, clarity_score DOUBLE, confidence_score DOUBLE, overall_score DOUBLE, PRIMARY KEY(answer_key))",
            "CREATE NODE TABLE IF NOT EXISTS Weakness (weakness_key STRING, area STRING, severity STRING, PRIMARY KEY(weakness_key))",
            "CREATE NODE TABLE IF NOT EXISTS Improvement (improvement_key STRING, recommendation STRING, PRIMARY KEY(improvement_key))",
            "CREATE NODE TABLE IF NOT EXISTS Requirement (req_key STRING, session_id STRING, skill STRING, priority STRING, PRIMARY KEY(req_key))",
        ]
        rel_tables = [
            "CREATE REL TABLE IF NOT EXISTS HAS_SKILL (FROM User TO Skill, proficiency DOUBLE)",
            "CREATE REL TABLE IF NOT EXISTS ASKED (FROM User TO Question)",
            "CREATE REL TABLE IF NOT EXISTS ANSWERED_BY (FROM Question TO Answer)",
            "CREATE REL TABLE IF NOT EXISTS REVEALS (FROM Answer TO Weakness)",
            "CREATE REL TABLE IF NOT EXISTS SUGGESTS (FROM Weakness TO Improvement)",
            "CREATE REL TABLE IF NOT EXISTS TARGETS (FROM User TO Requirement)",
        ]
        for stmt in node_tables + rel_tables:
            conn.execute(stmt)

    def create_user_session(self, session_id: str, resume_data: Dict[str, Any]):
        conn = KuzuManager._conn
        conn.execute(
            "CREATE (:User {session_id: $session_id, created_at: $created_at})",
            {"session_id": session_id, "created_at": datetime.now().isoformat()}
        )
        for skill in resume_data.get("skills", []):
            try:
                conn.execute("CREATE (:Skill {name: $name})", {"name": skill})
            except Exception:
                pass
            conn.execute(
                "MATCH (u:User {session_id: $session_id}), (s:Skill {name: $skill}) "
                "CREATE (u)-[:HAS_SKILL {proficiency: 0.7}]->(s)",
                {"session_id": session_id, "skill": skill}
            )

    def create_jd_requirements(self, session_id: str, jd_requirements: Dict[str, Any]):
        conn = KuzuManager._conn
        for skill in jd_requirements.get("required_skills", []):
            try:
                conn.execute("CREATE (:Skill {name: $name})", {"name": skill})
            except Exception:
                pass
            req_key = f"{session_id}_req_{skill}"
            conn.execute(
                "CREATE (:Requirement {req_key: $req_key, session_id: $session_id, skill: $skill, priority: $priority})",
                {"req_key": req_key, "session_id": session_id, "skill": skill, "priority": "high"}
            )
            conn.execute(
                "MATCH (u:User {session_id: $session_id}), (r:Requirement {req_key: $req_key}) "
                "CREATE (u)-[:TARGETS]->(r)",
                {"session_id": session_id, "req_key": req_key}
            )

    def store_qa_evaluation(self, session_id: str, qa_data: Dict[str, Any]):
        conn = KuzuManager._conn
        question_id = int(qa_data["question_id"])
        question_key = f"{session_id}_q{question_id}"
        answer_key = f"{session_id}_a{question_id}"

        conn.execute(
            "CREATE (:Question {question_key: $question_key, session_id: $session_id, "
            "question_id: $question_id, text: $text, asked_at: $asked_at})",
            {
                "question_key": question_key,
                "session_id": session_id,
                "question_id": question_id,
                "text": qa_data["question"],
                "asked_at": datetime.now().isoformat(),
            }
        )
        conn.execute(
            "CREATE (:Answer {answer_key: $answer_key, text: $text, "
            "technical_score: $technical_score, clarity_score: $clarity_score, "
            "confidence_score: $confidence_score, overall_score: $overall_score})",
            {
                "answer_key": answer_key,
                "text": qa_data["answer"],
                "technical_score": float(qa_data["technical_score"]),
                "clarity_score": float(qa_data["clarity_score"]),
                "confidence_score": float(qa_data["confidence_score"]),
                "overall_score": float(qa_data["overall_score"]),
            }
        )
        conn.execute(
            "MATCH (u:User {session_id: $session_id}), (q:Question {question_key: $question_key}) "
            "CREATE (u)-[:ASKED]->(q)",
            {"session_id": session_id, "question_key": question_key}
        )
        conn.execute(
            "MATCH (q:Question {question_key: $question_key}), (a:Answer {answer_key: $answer_key}) "
            "CREATE (q)-[:ANSWERED_BY]->(a)",
            {"question_key": question_key, "answer_key": answer_key}
        )

        if qa_data["overall_score"] < 3.0:
            weakness_area = qa_data.get("question", "Unknown topic")[:200]
            score = qa_data["overall_score"]
            weakness_key = f"{session_id}_w{question_id}"
            improvement_key = f"{session_id}_i{question_id}"
            severity = "high" if score < 2.0 else "medium"
            if score <= 1.0:
                recommendation = f"No answer provided. Study this topic from scratch: '{weakness_area[:80]}'"
            elif score < 2.0:
                recommendation = f"Very weak answer. Deep dive into: '{weakness_area[:80]}'"
            else:
                recommendation = f"Partial understanding. Revisit and practice: '{weakness_area[:80]}'"

            conn.execute(
                "CREATE (:Weakness {weakness_key: $weakness_key, area: $area, severity: $severity})",
                {"weakness_key": weakness_key, "area": weakness_area, "severity": severity}
            )
            conn.execute(
                "CREATE (:Improvement {improvement_key: $improvement_key, recommendation: $recommendation})",
                {"improvement_key": improvement_key, "recommendation": recommendation}
            )
            conn.execute(
                "MATCH (a:Answer {answer_key: $answer_key}), (w:Weakness {weakness_key: $weakness_key}) "
                "CREATE (a)-[:REVEALS]->(w)",
                {"answer_key": answer_key, "weakness_key": weakness_key}
            )
            conn.execute(
                "MATCH (w:Weakness {weakness_key: $weakness_key}), (i:Improvement {improvement_key: $improvement_key}) "
                "CREATE (w)-[:SUGGESTS]->(i)",
                {"weakness_key": weakness_key, "improvement_key": improvement_key}
            )

    def get_performance_summary(self, session_id: str) -> Dict[str, Any]:
        conn = KuzuManager._conn
        result = conn.execute(
            "MATCH (u:User {session_id: $session_id})-[:ASKED]->(q:Question)-[:ANSWERED_BY]->(a:Answer) "
            "RETURN AVG(a.technical_score), AVG(a.clarity_score), AVG(a.confidence_score), "
            "AVG(a.overall_score), COUNT(a)",
            {"session_id": session_id}
        )
        if result.has_next():
            row = result.get_next()
            return {
                "avg_technical": round(row[0] or 0, 2),
                "avg_clarity": round(row[1] or 0, 2),
                "avg_confidence": round(row[2] or 0, 2),
                "avg_overall": round(row[3] or 0, 2),
                "total_questions": row[4],
            }
        return {}

    def get_weaknesses_and_improvements(self, session_id: str) -> List[Dict[str, str]]:
        conn = KuzuManager._conn
        result = conn.execute(
            "MATCH (u:User {session_id: $session_id})-[:ASKED]->(q:Question)"
            "-[:ANSWERED_BY]->(a:Answer)-[:REVEALS]->(w:Weakness)-[:SUGGESTS]->(i:Improvement) "
            "RETURN w.area, w.severity, i.recommendation "
            "ORDER BY w.severity DESC",
            {"session_id": session_id}
        )
        rows = []
        while result.has_next():
            row = result.get_next()
            rows.append({"weakness": row[0], "severity": row[1], "improvement": row[2]})
        return rows

    def delete_session_data(self, session_id: str):
        conn = KuzuManager._conn
        # Delete relationships deepest first (KùzuDB requires rels deleted before nodes)
        conn.execute(
            "MATCH (u:User {session_id: $session_id})-[:ASKED]->(:Question)"
            "-[:ANSWERED_BY]->(:Answer)-[:REVEALS]->(:Weakness)-[r:SUGGESTS]->() DELETE r",
            {"session_id": session_id}
        )
        conn.execute(
            "MATCH (u:User {session_id: $session_id})-[:ASKED]->(:Question)"
            "-[:ANSWERED_BY]->(:Answer)-[r:REVEALS]->() DELETE r",
            {"session_id": session_id}
        )
        conn.execute(
            "MATCH (u:User {session_id: $session_id})-[:ASKED]->(:Question)-[r:ANSWERED_BY]->() DELETE r",
            {"session_id": session_id}
        )
        conn.execute(
            "MATCH (u:User {session_id: $session_id})-[r:ASKED]->() DELETE r",
            {"session_id": session_id}
        )
        conn.execute(
            "MATCH (u:User {session_id: $session_id})-[r:TARGETS]->() DELETE r",
            {"session_id": session_id}
        )
        conn.execute(
            "MATCH (u:User {session_id: $session_id})-[r:HAS_SKILL]->() DELETE r",
            {"session_id": session_id}
        )
        # Delete nodes (deepest first, by key prefix or session_id field)
        conn.execute(
            "MATCH (i:Improvement) WHERE i.improvement_key STARTS WITH $prefix DELETE i",
            {"prefix": f"{session_id}_i"}
        )
        conn.execute(
            "MATCH (w:Weakness) WHERE w.weakness_key STARTS WITH $prefix DELETE w",
            {"prefix": f"{session_id}_w"}
        )
        conn.execute(
            "MATCH (a:Answer) WHERE a.answer_key STARTS WITH $prefix DELETE a",
            {"prefix": f"{session_id}_a"}
        )
        conn.execute(
            "MATCH (q:Question {session_id: $session_id}) DELETE q",
            {"session_id": session_id}
        )
        conn.execute(
            "MATCH (r:Requirement {session_id: $session_id}) DELETE r",
            {"session_id": session_id}
        )
        conn.execute(
            "MATCH (u:User {session_id: $session_id}) DELETE u",
            {"session_id": session_id}
        )

    def close(self):
        pass
