-- Rollback for 0002. Destroys the audit log. Export it first if it must be kept.
BEGIN;
DROP FUNCTION IF EXISTS oracle_arc_private.audit_head();
DROP FUNCTION IF EXISTS oracle_arc_private.verify_audit_chain();
DROP FUNCTION IF EXISTS oracle_arc_private.append_audit(TEXT,TEXT,TEXT,TEXT,JSONB);
DROP FUNCTION IF EXISTS oracle_arc_private.audit_digest(BYTEA,BIGINT,TEXT,TEXT,TEXT,TEXT,JSONB);
DROP TABLE IF EXISTS oracle_arc_private.audit_log;
DROP FUNCTION IF EXISTS oracle_arc_private.audit_immutable();
COMMIT;
