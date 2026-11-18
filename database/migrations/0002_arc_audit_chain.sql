-- Oracle Arc A8 step 2: append-only, hash-chained audit log in PostgreSQL.
-- Requires 0001. The runtime role can only call append_audit() and verify_audit_chain();
-- it has no direct INSERT/UPDATE/DELETE. Triggers block UPDATE/DELETE/TRUNCATE for every role.
-- Rollback: database/migrations/0002_arc_audit_chain.rollback.sql
BEGIN;

CREATE TABLE oracle_arc_private.audit_log (
  seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  ts_us BIGINT NOT NULL CHECK (ts_us > 0),
  event TEXT NOT NULL CHECK (length(event) BETWEEN 1 AND 120),
  app_id TEXT NOT NULL DEFAULT '' CHECK (length(app_id) <= 64),
  user_id TEXT NOT NULL DEFAULT '' CHECK (length(user_id) <= 256),
  agent TEXT NOT NULL DEFAULT '' CHECK (length(agent) <= 96),
  detail JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(detail)='object'),
  prev BYTEA NOT NULL CHECK (octet_length(prev)=32),
  hash BYTEA NOT NULL UNIQUE CHECK (octet_length(hash)=32)
);
CREATE INDEX audit_log_event_idx ON oracle_arc_private.audit_log (event, seq);
CREATE INDEX audit_log_app_idx ON oracle_arc_private.audit_log (app_id, seq);
ALTER TABLE oracle_arc_private.audit_log OWNER TO oracle_arc_owner;
ALTER TABLE oracle_arc_private.audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE oracle_arc_private.audit_log FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_owner_all ON oracle_arc_private.audit_log FOR ALL TO oracle_arc_owner USING (true) WITH CHECK (true);

REVOKE ALL ON oracle_arc_private.audit_log FROM PUBLIC, oracle_arc_runtime, oracle_arc_provisioner;

CREATE FUNCTION oracle_arc_private.audit_immutable() RETURNS trigger
LANGUAGE plpgsql AS $f$
BEGIN
  RAISE EXCEPTION 'audit_log is append-only' USING ERRCODE = '42501';
END
$f$;
CREATE TRIGGER audit_no_update_delete BEFORE UPDATE OR DELETE ON oracle_arc_private.audit_log
  FOR EACH ROW EXECUTE FUNCTION oracle_arc_private.audit_immutable();
CREATE TRIGGER audit_no_truncate BEFORE TRUNCATE ON oracle_arc_private.audit_log
  FOR EACH STATEMENT EXECUTE FUNCTION oracle_arc_private.audit_immutable();

CREATE FUNCTION oracle_arc_private.audit_digest(prev BYTEA, ts_us BIGINT, event TEXT, app_id TEXT,
  user_id TEXT, agent TEXT, detail JSONB) RETURNS BYTEA
LANGUAGE sql IMMUTABLE AS $f$
  SELECT sha256(convert_to(encode(prev,'hex') ||
    jsonb_build_array(ts_us, event, app_id, user_id, agent, detail)::text, 'UTF8'))
$f$;

-- Serialises appends so the chain has exactly one head. Secrets must be redacted by the caller.
CREATE FUNCTION oracle_arc_private.append_audit(p_event TEXT, p_app_id TEXT, p_user_id TEXT,
  p_agent TEXT, p_detail JSONB) RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
DECLARE
  v_prev BYTEA; v_ts BIGINT; v_hash BYTEA; v_seq BIGINT;
  v_detail JSONB := COALESCE(p_detail, '{}'::jsonb);
BEGIN
  PERFORM pg_advisory_xact_lock(hashtextextended('oracle_arc.audit_chain', 0));
  SELECT hash INTO v_prev FROM oracle_arc_private.audit_log ORDER BY seq DESC LIMIT 1;
  v_prev := COALESCE(v_prev, decode(repeat('00', 32), 'hex'));
  v_ts := (extract(epoch FROM clock_timestamp()) * 1000000)::bigint;
  v_hash := oracle_arc_private.audit_digest(v_prev, v_ts, p_event, COALESCE(p_app_id,''),
            COALESCE(p_user_id,''), COALESCE(p_agent,''), v_detail);
  INSERT INTO oracle_arc_private.audit_log (ts_us, event, app_id, user_id, agent, detail, prev, hash)
  VALUES (v_ts, p_event, COALESCE(p_app_id,''), COALESCE(p_user_id,''), COALESCE(p_agent,''),
          v_detail, v_prev, v_hash) RETURNING seq INTO v_seq;
  RETURN v_seq;
END
$f$;

-- Returns NULL when the whole chain verifies, otherwise the first sequence number that fails.
CREATE FUNCTION oracle_arc_private.verify_audit_chain() RETURNS BIGINT
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
DECLARE
  r RECORD; v_prev BYTEA := decode(repeat('00', 32), 'hex');
BEGIN
  FOR r IN SELECT * FROM oracle_arc_private.audit_log ORDER BY seq LOOP
    IF r.prev <> v_prev OR r.hash <> oracle_arc_private.audit_digest(
         r.prev, r.ts_us, r.event, r.app_id, r.user_id, r.agent, r.detail) THEN
      RETURN r.seq;
    END IF;
    v_prev := r.hash;
  END LOOP;
  RETURN NULL;
END
$f$;

-- Current head, for external anchoring (A13).
CREATE FUNCTION oracle_arc_private.audit_head() RETURNS TABLE (seq BIGINT, hash TEXT)
LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
  SELECT seq, encode(hash,'hex') FROM oracle_arc_private.audit_log ORDER BY seq DESC LIMIT 1
$f$;

ALTER FUNCTION oracle_arc_private.append_audit(TEXT,TEXT,TEXT,TEXT,JSONB) OWNER TO oracle_arc_owner;
ALTER FUNCTION oracle_arc_private.verify_audit_chain() OWNER TO oracle_arc_owner;
ALTER FUNCTION oracle_arc_private.audit_head() OWNER TO oracle_arc_owner;
ALTER FUNCTION oracle_arc_private.audit_digest(BYTEA,BIGINT,TEXT,TEXT,TEXT,TEXT,JSONB) OWNER TO oracle_arc_owner;
ALTER FUNCTION oracle_arc_private.audit_immutable() OWNER TO oracle_arc_owner;
REVOKE ALL ON FUNCTION oracle_arc_private.append_audit(TEXT,TEXT,TEXT,TEXT,JSONB) FROM PUBLIC;
REVOKE ALL ON FUNCTION oracle_arc_private.verify_audit_chain() FROM PUBLIC;
REVOKE ALL ON FUNCTION oracle_arc_private.audit_head() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION oracle_arc_private.append_audit(TEXT,TEXT,TEXT,TEXT,JSONB) TO oracle_arc_runtime;
GRANT EXECUTE ON FUNCTION oracle_arc_private.verify_audit_chain() TO oracle_arc_runtime;
GRANT EXECUTE ON FUNCTION oracle_arc_private.audit_head() TO oracle_arc_runtime;

COMMIT;
