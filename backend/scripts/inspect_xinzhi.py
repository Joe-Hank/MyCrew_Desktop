"""Ad-hoc inspection of 心之回廊 project state. Safe to delete after use."""
import sqlite3, json, sys

c = sqlite3.connect('f:/ClaudeData/MyCrew_v3/data/db/mycrew.db')
c.row_factory = sqlite3.Row
PID = 'proj_031487f7e2db'

print('=== Agents used (and their is_auto_generated flag) ===')
rows = c.execute("""
  SELECT DISTINCT a.id, a.role, a.is_auto_generated, a.llm_id
  FROM tasks t JOIN agents a ON t.agent_id=a.id
  WHERE t.project_id=?
""", (PID,)).fetchall()
for r in rows:
    print(f'  id={r["id"]}  role={r["role"]}  auto_gen={r["is_auto_generated"]}  llm_id={r["llm_id"]}')

print()
print('=== Final QA task ===')
qa = c.execute("""
  SELECT id, title, status, io_out_ref, qa_score, started_at, finished_at
  FROM tasks WHERE project_id=? AND kind='final_qa'
""", (PID,)).fetchone()
if qa:
    for k in qa.keys():
        v = qa[k]
        s = str(v)
        print(f'  {k}: {s[:200]}')

print()
print('=== Last 3 tasks io_out_ref samples ===')
rows = c.execute("""
  SELECT id, title, io_out_ref
  FROM tasks WHERE project_id=? AND io_out_ref IS NOT NULL
  ORDER BY rowid DESC LIMIT 3
""", (PID,)).fetchall()
for r in rows:
    print(f'  task={r["id"]}  io_out={r["io_out_ref"]}')
