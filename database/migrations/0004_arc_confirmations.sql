-- Oracle Arc A8 step 4: persistent, single-use confirmation challenges. Requires 0001.
-- Consumption is one atomic UPDATE, so concurrent or multi-process replays can succeed at most once.
-- Challenge ids are stored only as SHA-256 digests. Step-up authentication stays with the host and
-- is passed in as a boolean; the database never sees credentials.
-- Rollback: 0004_arc_confirmations.rollback.sql
BEGIN;

CREATE TABLE oracle_arc_private.confirmations (
  id_hash BYTEA PRIMARY KEY CHECK (octet_length(id_hash)=32),
  app_id TEXT NOT NULL REFERENCES oracle_arc_private.applications(app_id) ON DELETE CASCADE,
  user_id TEXT NOT NULL CHECK (length(user_id) BETWEEN 1 AND 256),
  agent TEXT NOT NULL CHECK (length(agent) BETWEEN 1 AND 96),
  tool TEXT NOT NULL CHECK (length(tool) BETWEEN 1 AND 96),
  args JSONB NOT NULL CHECK (jsonb_typeof(args)='object'),
  summary TEXT NOT NULL CHECK (length(summary) BETWEEN 1 AND 1000),
  risk SMALLINT NOT NULL CHECK (risk BETWEEN 0 AND 3),
  action_hash TEXT NOT NULL CHECK (action_hash ~ '^[0-9a-f]{64}$'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  expires_at TIMESTAMPTZ NOT NULL,
  used_at TIMESTAMPTZ,
  CHECK (expires_at > created_at),
  CHECK (expires_at <= created_at + interval '1 hour')
);
CREATE INDEX confirmations_expiry_idx ON oracle_arc_private.confirmations (expires_at);

ALTER TABLE oracle_arc_private.confirmations OWNER TO oracle_arc_owner;
ALTER TABLE oracle_arc_private.confirmations ENABLE ROW LEVEL SECURITY;
ALTER TABLE oracle_arc_private.confirmations FORCE ROW LEVEL SECURITY;
CREATE POLICY confirmations_owner ON oracle_arc_private.confirmations FOR ALL TO oracle_arc_owner USING (true) WITH CHECK (true);
REVOKE ALL ON oracle_arc_private.confirmations FROM PUBLIC, oracle_arc_runtime, oracle_arc_provisioner;

CREATE FUNCTION oracle_arc_private.confirmation_create(p_app TEXT, p_user TEXT, p_id TEXT, p_agent TEXT, p_tool TEXT,
  p_args JSONB, p_summary TEXT, p_risk SMALLINT, p_action_hash TEXT, p_ttl_s DOUBLE PRECISION) RETURNS TIMESTAMPTZ
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
DECLARE v_exp TIMESTAMPTZ;
BEGIN
  PERFORM oracle_arc_private.spark_assert_app(p_app);
  IF p_id IS NULL OR length(p_id) < 16 THEN RAISE EXCEPTION 'challenge id too short' USING ERRCODE='22023'; END IF;
  IF p_ttl_s IS NULL OR p_ttl_s <= 0 OR p_ttl_s > 3600 THEN RAISE EXCEPTION 'ttl must be 1..3600 seconds' USING ERRCODE='22023'; END IF;
  v_exp := clock_timestamp() + make_interval(secs => p_ttl_s);
  INSERT INTO oracle_arc_private.confirmations (id_hash, app_id, user_id, agent, tool, args, summary, risk, action_hash, expires_at)
  VALUES (sha256(convert_to(p_id,'UTF8')), p_app, p_user, p_agent, p_tool, p_args, p_summary, p_risk, p_action_hash, v_exp);
  RETURN v_exp;
END $f$;

-- Returns the action on success. Raises a distinct, non-leaking error otherwise. SQLSTATEs: 'AC001' unknown,
-- 'AC002' wrong user/app, 'AC003' already used, 'AC004' expired, 'AC005' hash mismatch, 'AC006' step-up failed.
CREATE FUNCTION oracle_arc_private.confirmation_consume(p_app TEXT, p_user TEXT, p_id TEXT, p_echoed_hash TEXT,
  p_step_up_ok BOOLEAN) RETURNS TABLE (agent TEXT, tool TEXT, args JSONB, summary TEXT, risk SMALLINT, action_hash TEXT)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
DECLARE c oracle_arc_private.confirmations%ROWTYPE; v_hash BYTEA := sha256(convert_to(COALESCE(p_id,''),'UTF8'));
BEGIN
  PERFORM oracle_arc_private.spark_assert_app(p_app);
  SELECT * INTO c FROM oracle_arc_private.confirmations WHERE id_hash = v_hash FOR UPDATE;
  IF NOT FOUND THEN RAISE EXCEPTION 'unknown confirmation' USING ERRCODE='AC001'; END IF;
  IF c.app_id <> p_app OR c.user_id <> p_user THEN
    RAISE EXCEPTION 'confirmation belongs to a different user or application' USING ERRCODE='AC002'; END IF;
  IF c.used_at IS NOT NULL THEN RAISE EXCEPTION 'confirmation already used' USING ERRCODE='AC003'; END IF;
  IF c.expires_at < clock_timestamp() THEN RAISE EXCEPTION 'confirmation expired' USING ERRCODE='AC004'; END IF;
  IF p_echoed_hash IS DISTINCT FROM c.action_hash THEN
    RAISE EXCEPTION 'confirmation does not match the action presented' USING ERRCODE='AC005'; END IF;
  IF c.risk >= 2 AND NOT COALESCE(p_step_up_ok, false) THEN
    RAISE EXCEPTION 'step-up authentication required' USING ERRCODE='AC006'; END IF;
  UPDATE oracle_arc_private.confirmations SET used_at = clock_timestamp() WHERE id_hash = v_hash AND used_at IS NULL;
  RETURN QUERY SELECT c.agent, c.tool, c.args, c.summary, c.risk, c.action_hash;
END $f$;

CREATE FUNCTION oracle_arc_private.confirmation_purge() RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
DECLARE n INTEGER;
BEGIN
  DELETE FROM oracle_arc_private.confirmations WHERE expires_at < clock_timestamp() - interval '1 day';
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $f$;

DO $g$
DECLARE f TEXT;
BEGIN
  FOREACH f IN ARRAY ARRAY[
    'confirmation_create(text,text,text,text,text,jsonb,text,smallint,text,double precision)',
    'confirmation_consume(text,text,text,text,boolean)','confirmation_purge()']
  LOOP
    EXECUTE format('ALTER FUNCTION oracle_arc_private.%s OWNER TO oracle_arc_owner', f);
    EXECUTE format('REVOKE ALL ON FUNCTION oracle_arc_private.%s FROM PUBLIC', f);
    EXECUTE format('GRANT EXECUTE ON FUNCTION oracle_arc_private.%s TO oracle_arc_runtime', f);
  END LOOP;
END $g$;

COMMIT;
