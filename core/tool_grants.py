"""Owner-managed application tool grants with append-only lifecycle audit."""
from __future__ import annotations
import re, sqlite3, time, uuid
from contextlib import contextmanager
_TOOL_ID=re.compile(r"^[a-z][a-z0-9._-]{1,63}$")
class ToolGrantStore:
 def __init__(self,database_path:str):
  self.database_path=database_path
  with self._session() as db:
   db.executescript("""
   CREATE TABLE IF NOT EXISTS arc_application_tool_grants(
    grant_id TEXT PRIMARY KEY,tenant_id TEXT NOT NULL,application_id TEXT NOT NULL,
    tool_id TEXT NOT NULL,granted_by TEXT NOT NULL,created_at INTEGER NOT NULL,
    revoked_at INTEGER,revoked_by TEXT);
   CREATE INDEX IF NOT EXISTS arc_tool_grants_scope ON arc_application_tool_grants(tenant_id,application_id,revoked_at);
   CREATE TABLE IF NOT EXISTS arc_tool_grant_audit(
    audit_id TEXT PRIMARY KEY,grant_id TEXT NOT NULL,tenant_id TEXT NOT NULL,
    application_id TEXT NOT NULL,tool_id TEXT NOT NULL,action TEXT NOT NULL,
    actor TEXT NOT NULL,occurred_at INTEGER NOT NULL);
   """)
 @contextmanager
 def _session(self):
  db=sqlite3.connect(self.database_path,timeout=15);db.row_factory=sqlite3.Row
  db.execute("PRAGMA foreign_keys=ON");db.execute("PRAGMA busy_timeout=15000")
  try:yield db;db.commit()
  except Exception:db.rollback();raise
  finally:db.close()
 def grant(self,tenant_id,application_id,tool_id,actor):
  if not all(isinstance(v,str) and v.strip() for v in (tenant_id,application_id,actor)):raise ValueError("Tenant, application and owner actor are required")
  if not isinstance(tool_id,str) or not _TOOL_ID.fullmatch(tool_id):raise ValueError("Tool ID must be a normalized identifier")
  now=int(time.time());gid="tgr_"+uuid.uuid4().hex
  with self._session() as db:
   db.execute("BEGIN IMMEDIATE")
   if not db.execute("SELECT 1 FROM arc_applications WHERE tenant_id=? AND application_id=? AND status='active'",(tenant_id,application_id)).fetchone():raise LookupError("Active application not found in the specified tenant")
   if db.execute("SELECT 1 FROM arc_application_tool_grants WHERE tenant_id=? AND application_id=? AND tool_id=? AND revoked_at IS NULL",(tenant_id,application_id,tool_id)).fetchone():raise ValueError("An active grant already exists; revoke it before re-granting")
   db.execute("INSERT INTO arc_application_tool_grants VALUES(?,?,?,?,?,?,NULL,NULL)",(gid,tenant_id,application_id,tool_id,actor,now))
   db.execute("INSERT INTO arc_tool_grant_audit VALUES(?,?,?,?,?,?,?,?)",("tga_"+uuid.uuid4().hex,gid,tenant_id,application_id,tool_id,"granted",actor,now))
   return self._record(db.execute("SELECT * FROM arc_application_tool_grants WHERE grant_id=?",(gid,)).fetchone())
 def revoke(self,grant_id,actor):
  now=int(time.time())
  with self._session() as db:
   db.execute("BEGIN IMMEDIATE")
   row=db.execute("SELECT * FROM arc_application_tool_grants WHERE grant_id=? AND revoked_at IS NULL",(grant_id,)).fetchone()
   if not row:return False
   changed=db.execute("UPDATE arc_application_tool_grants SET revoked_at=?,revoked_by=? WHERE grant_id=? AND revoked_at IS NULL",(now,actor,grant_id)).rowcount
   if changed:db.execute("INSERT INTO arc_tool_grant_audit VALUES(?,?,?,?,?,?,?,?)",("tga_"+uuid.uuid4().hex,grant_id,row["tenant_id"],row["application_id"],row["tool_id"],"revoked",actor,now))
   return changed==1
 def list(self,tenant_id=None,application_id=None):
  with self._session() as db:
   if tenant_id and application_id:rows=db.execute("SELECT * FROM arc_application_tool_grants WHERE tenant_id=? AND application_id=? ORDER BY created_at DESC",(tenant_id,application_id)).fetchall()
   else:rows=db.execute("SELECT * FROM arc_application_tool_grants ORDER BY created_at DESC LIMIT 500").fetchall()
   return [self._record(r) for r in rows]
 @contextmanager
 def execution_guard(self,tenant_id,application_id,tool_id):
  """Linearize tool execution against owner revocation.

  A short SQLite write reservation is held for the bounded tool invocation. A concurrent
  revoke either commits before this guard (and blocks the call) or waits until the current
  in-flight call finishes; after revoke returns, no later call can pass this guard.
  """
  with self._session() as db:
   db.execute("BEGIN IMMEDIATE")
   active=db.execute("""SELECT 1 FROM arc_application_tool_grants
    WHERE tenant_id=? AND application_id=? AND tool_id=? AND revoked_at IS NULL""",
    (tenant_id,application_id,tool_id)).fetchone()
   if not active:raise PermissionError("Owner tool grant is no longer active")
   yield
 def active_tool_ids(self,tenant_id,application_id):
  with self._session() as db:
   return {r["tool_id"] for r in db.execute("SELECT tool_id FROM arc_application_tool_grants WHERE tenant_id=? AND application_id=? AND revoked_at IS NULL",(tenant_id,application_id)).fetchall()}
 @staticmethod
 def _record(row):return {**dict(row),"status":"revoked" if row["revoked_at"] is not None else "active"}
