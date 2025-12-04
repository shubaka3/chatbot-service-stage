# ai_evaluation.py
import time
import requests
import psycopg2
import json
import re
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel

# --- CẤU HÌNH ---
DB_CONFIG = {
    "dbname": "ai-evaluation",
    "user": "postgres",
    "password": "shubaka3",
    "host": "localhost",
    "port": "5432"
}

MAIN_API_URL = "https://vmentor-service.emg.edu.vn/api/chat/completions"

SCORING_API_URL = "https://llm.emg.edu.vn:3000/api/chat/completions"
SCORING_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6ImEzMzMzODY2LTBmZDgtNGFjZS1iMzg5LTZiMGEyZGExOGFjOSJ9.Pm2b2VTiKFxKlt21v1UAEt7A8MonlHOyGBBC1Ty46zQ"
SCORING_MODEL = "gemma3:27b"

PRICE_PER_1K_INPUT = 0.000125
PRICE_PER_1K_OUTPUT = 0.000375

# --- DATA MODELS (Pydantic) ---
class ConfigInput(BaseModel):
    raw_lines: List[str]
    name_prefix: Optional[str] = "Config"

class QuestionInput(BaseModel):
    questions: List[str]

class RunTestRequest(BaseModel):
    config_ids: List[int]
    question_ids: List[int]

class HistoryFilter(BaseModel):
    config_id: Optional[int] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    sort_by: Optional[str] = "time_desc"

# --- HELPER FUNCTIONS ---

def get_db_connection():
    return psycopg2.connect(**DB_CONFIG)

def calculate_tokens(text: str) -> int:
    return len(text) // 4 if text else 0

def get_ai_score(question: str, answer: str) -> int:
    prompt = f"""
    Hãy đóng vai một giám khảo khó tính. Hãy chấm điểm câu trả lời dưới đây dựa trên câu hỏi được đưa ra theo thang điểm từ 1 đến 10.
    
    Câu hỏi: {question}
    Câu trả lời: {answer}
    
    YÊU CẦU TUYỆT ĐỐI: Chỉ trả về duy nhất một con số từ 1 đến 10. Không giải thích, không thêm chữ.
    """
    
    headers = {
        "Authorization": f"Bearer {SCORING_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": SCORING_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }

    try:
        response = requests.post(SCORING_API_URL, headers=headers, json=payload, timeout=30, verify=False)
        if response.status_code == 200:
            res_json = response.json()
            content = res_json.get("choices", [{}])[0].get("message", {}).get("content", "0")
            match = re.search(r'\b(10|[1-9])\b', str(content))
            if match:
                return int(match.group(1))
    except Exception as e:
        print(f"Scoring Error: {e}")
    return 0

# --- CORE LOGIC FUNCTIONS ---

def db_get_configs():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, config_name, ai_id, collection_id, user_id FROM test_configs ORDER BY id DESC")
        rows = cur.fetchall()
        configs = []
        for r in rows:
            display_name = r[1] if r[1] else f"Config #{r[0]}"
            configs.append({
                "id": r[0],
                "name": display_name,
                "ai_id": r[2],
                "full_str": f"{r[2]}&{r[3]}&{r[4]}"
            })
        return configs
    finally:
        if conn: conn.close()

def db_add_configs(data: ConfigInput):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        added = 0
        for idx, line in enumerate(data.raw_lines):
            parts = line.strip().split('&')
            if len(parts) >= 3:
                ai_id, col_id, user_id = parts[0].strip(), parts[1].strip(), parts[2].strip()
                conf_name = f"{data.name_prefix} {idx+1}" if data.name_prefix else f"Config {ai_id[:5]}"
                
                cur.execute("""
                    INSERT INTO test_configs (config_name, ai_id, collection_id, user_id)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (ai_id, collection_id, user_id) 
                    DO UPDATE SET config_name = EXCLUDED.config_name
                """, (conf_name, ai_id, col_id, user_id))
                added += 1
        conn.commit()
        return added
    finally:
        if conn: conn.close()

def db_get_questions():
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, content FROM test_questions ORDER BY id DESC")
        rows = cur.fetchall()
        return [{"id": r[0], "content": r[1]} for r in rows]
    finally:
        if conn: conn.close()

def db_add_questions(data: QuestionInput):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        for q in data.questions:
            if q.strip():
                cur.execute("INSERT INTO test_questions (content) VALUES (%s) ON CONFLICT (content) DO NOTHING", (q.strip(),))
        conn.commit()
    finally:
        if conn: conn.close()

def process_run_test(data: RunTestRequest):
    conn = get_db_connection()
    results = []
    try:
        cur = conn.cursor()
        cur.execute("SELECT id, config_name, ai_id, collection_id, user_id FROM test_configs WHERE id = ANY(%s)", (data.config_ids,))
        configs = cur.fetchall()
        cur.execute("SELECT id, content FROM test_questions WHERE id = ANY(%s)", (data.question_ids,))
        questions = cur.fetchall()

        for conf in configs:
            conf_id, conf_name, ai_id, col_id, user_id = conf
            display_name = conf_name if conf_name else f"ID {conf_id}"
            
            for ques in questions:
                q_text = ques[1]
                session_id = f"sess_{int(time.time())}"
                payload = {
                    "ai_id": ai_id, "collection_id": col_id, "user_id": user_id,
                    "messages": [{"content": q_text, "role": "user"}],
                    "stream": False, "sessionId": session_id
                }

                start = time.time()
                try:
                    res = requests.post(MAIN_API_URL, json=payload, timeout=60)
                    res_json = res.json()
                except Exception as e:
                    res_json = {"answer": f"Error: {str(e)}", "sources": []}
                end = time.time()
                
                # Process Data
                ans_text = res_json.get("answer", "")
                sources = res_json.get("sources", [])
                rag_list = [s.get("page_content", "") for s in sources]
                full_rag = " ".join(rag_list)
                
                while len(rag_list) < 10: rag_list.append(None)
                
                # --- AUTO SCORING ---
                ai_score = get_ai_score(q_text, ans_text)

                # Metrics
                q_tok = calculate_tokens(q_text)
                rag_tok = calculate_tokens(full_rag)
                ans_tok = calculate_tokens(ans_text)
                cost = ((q_tok + rag_tok)/1000 * PRICE_PER_1K_INPUT) + (ans_tok/1000 * PRICE_PER_1K_OUTPUT)
                time_ms = round((end - start) * 1000, 2)

                # Save DB
                insert_sql = """
                    INSERT INTO ai_test_results (
                        config_id, session_id, question, answer, score,
                        rag_content_1, rag_content_2, rag_content_3, rag_content_4, rag_content_5,
                        rag_content_6, rag_content_7, rag_content_8, rag_content_9, rag_content_10,
                        rag_length, rag_tokens, input_length, input_tokens,
                        response_length, response_tokens, response_time_ms, total_cost, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                """
                cur.execute(insert_sql, (
                    conf_id, session_id, q_text, ans_text, ai_score,
                    rag_list[0], rag_list[1], rag_list[2], rag_list[3], rag_list[4],
                    rag_list[5], rag_list[6], rag_list[7], rag_list[8], rag_list[9],
                    len(full_rag), rag_tok, len(q_text), q_tok + rag_tok,
                    len(ans_text), ans_tok, time_ms, cost
                ))
                conn.commit()

                results.append({
                    "config_name": display_name,
                    "question": q_text,
                    "answer": ans_text,
                    "score": ai_score,
                    "time_ms": time_ms,
                    "cost": cost,
                    "metrics": {
                        "input_tok": q_tok + rag_tok,
                        "rag_tok": rag_tok,
                        "ans_tok": ans_tok,
                        "rag_len": len(full_rag)
                    },
                    "rag_sources": rag_list
                })
        return results
    finally:
        if conn: conn.close()

def process_history(filter: HistoryFilter):
    conn = get_db_connection()
    try:
        cur = conn.cursor()
        query = """
            SELECT r.id, c.config_name, r.question, r.answer, r.score, r.response_time_ms, 
                   r.total_cost, r.input_tokens, r.rag_tokens, r.response_tokens, r.created_at,
                   r.rag_content_1, r.rag_content_2, r.rag_content_3, r.rag_content_4, r.rag_content_5,
                   r.rag_content_6, r.rag_content_7, r.rag_content_8, r.rag_content_9, r.rag_content_10,
                   r.rag_length
            FROM ai_test_results r
            JOIN test_configs c ON r.config_id = c.id
            WHERE 1=1
        """
        params = []

        if filter.config_id:
            query += " AND r.config_id = %s"
            params.append(filter.config_id)
        if filter.start_date:
            query += " AND r.created_at >= %s"
            params.append(f"{filter.start_date} 00:00:00")
        if filter.end_date:
            query += " AND r.created_at <= %s"
            params.append(f"{filter.end_date} 23:59:59")
            
        if filter.sort_by == "score_desc": query += " ORDER BY r.score DESC, r.id DESC"
        elif filter.sort_by == "score_asc": query += " ORDER BY r.score ASC, r.id DESC"
        elif filter.sort_by == "cost_desc": query += " ORDER BY r.total_cost DESC, r.id DESC"
        else: query += " ORDER BY r.created_at DESC"

        query += " LIMIT 200"

        cur.execute(query, tuple(params))
        rows = cur.fetchall()
        
        results = []
        for r in rows:
            rag_list = [r[11], r[12], r[13], r[14], r[15], r[16], r[17], r[18], r[19], r[20]]
            results.append({
                "id": r[0],
                "config_name": r[1],
                "question": r[2],
                "answer": r[3],
                "score": r[4],
                "time_ms": r[5],
                "cost": r[6],
                "created_at": r[10].strftime("%Y-%m-%d %H:%M:%S") if r[10] else "",
                "metrics": {
                    "input_tok": r[7], "rag_tok": r[8], "ans_tok": r[9], "rag_len": r[21]
                },
                "rag_sources": rag_list
            })
        return results
    finally:
        if conn: conn.close()