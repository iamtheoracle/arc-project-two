-- Oracle Arc A8 step 3: SPARK user-controlled memory in PostgreSQL. Requires 0001.
-- Isolation is enforced in the database: tables have forced RLS and no runtime grants; the runtime role
-- only calls SECURITY DEFINER functions, each scoped to the (app_id,user_id) the gateway authenticated.
-- Rollback: 0003_arc_spark_memory.rollback.sql
BEGIN;

CREATE TABLE oracle_arc_private.spark_memory (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  app_id TEXT NOT NULL REFERENCES oracle_arc_private.applications(app_id) ON DELETE CASCADE,
  space TEXT NOT NULL CHECK (space ~ '^[a-z][a-z0-9_.-]{1,63}/[a-z][a-z0-9_.:-]{0,63}$'),
  scope TEXT NOT NULL CHECK (scope IN ('personal','application','conversation','task')),
  owner TEXT NOT NULL CHECK (length(owner) BETWEEN 1 AND 320),
  content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 8000),
  purpose TEXT NOT NULL DEFAULT '' CHECK (length(purpose) <= 240),
  data_class SMALLINT NOT NULL DEFAULT 1 CHECK (data_class BETWEEN 0 AND 3),
  version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  expires_at TIMESTAMPTZ,
  tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED,
  CHECK (split_part(space,'/',1) = app_id),
  CHECK (scope <> 'task' OR expires_at IS NOT NULL)
);
CREATE INDEX spark_memory_lookup_idx ON oracle_arc_private.spark_memory (app_id, space, owner);
CREATE INDEX spark_memory_tsv_idx ON oracle_arc_private.spark_memory USING GIN (tsv);
CREATE INDEX spark_memory_expiry_idx ON oracle_arc_private.spark_memory (expires_at) WHERE expires_at IS NOT NULL;

CREATE TABLE oracle_arc_private.spark_share (
  app_id TEXT NOT NULL REFERENCES oracle_arc_private.applications(app_id) ON DELETE CASCADE,
  user_id TEXT NOT NULL CHECK (length(user_id) BETWEEN 1 AND 256),
  from_space TEXT NOT NULL,
  to_space TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY (app_id, user_id, from_space, to_space),
  CHECK (split_part(from_space,'/',1) = app_id AND split_part(to_space,'/',1) = app_id),
  CHECK (from_space <> to_space)
);

ALTER TABLE oracle_arc_private.spark_memory OWNER TO oracle_arc_owner;
ALTER TABLE oracle_arc_private.spark_share OWNER TO oracle_arc_owner;
ALTER TABLE oracle_arc_private.spark_memory ENABLE ROW LEVEL SECURITY;
ALTER TABLE oracle_arc_private.spark_memory FORCE ROW LEVEL SECURITY;
ALTER TABLE oracle_arc_private.spark_share ENABLE ROW LEVEL SECURITY;
ALTER TABLE oracle_arc_private.spark_share FORCE ROW LEVEL SECURITY;
CREATE POLICY spark_memory_owner ON oracle_arc_private.spark_memory FOR ALL TO oracle_arc_owner USING (true) WITH CHECK (true);
CREATE POLICY spark_share_owner ON oracle_arc_private.spark_share FOR ALL TO oracle_arc_owner USING (true) WITH CHECK (true);
REVOKE ALL ON oracle_arc_private.spark_memory, oracle_arc_private.spark_share
  FROM PUBLIC, oracle_arc_runtime, oracle_arc_provisioner;

-- Shared guard: the application must exist and not be suspended.
CREATE FUNCTION oracle_arc_private.spark_assert_app(p_app TEXT) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM oracle_arc_private.applications WHERE app_id=p_app AND NOT suspended) THEN
    RAISE EXCEPTION 'unknown or suspended application' USING ERRCODE='42501';
  END IF;
END $f$;

CREATE FUNCTION oracle_arc_private.spark_owner(p_app TEXT, p_user TEXT, p_scope TEXT, p_scope_id TEXT) RETURNS TEXT
LANGUAGE plpgsql IMMUTABLE SET search_path = pg_catalog AS $f$
BEGIN
  IF p_scope = 'personal' THEN RETURN p_user; END IF;
  IF p_scope = 'application' THEN RETURN p_app; END IF;
  IF p_scope IN ('conversation','task') AND COALESCE(p_scope_id,'') <> '' THEN RETURN p_user || ':' || p_scope_id; END IF;
  RAISE EXCEPTION 'scope requires a scope id' USING ERRCODE='22023';
END $f$;

CREATE FUNCTION oracle_arc_private.spark_remember(p_app TEXT, p_user TEXT, p_namespace TEXT, p_allowed TEXT[],
  p_content TEXT, p_scope TEXT, p_scope_id TEXT, p_data_class SMALLINT, p_ttl_s DOUBLE PRECISION, p_purpose TEXT)
RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
DECLARE v_id UUID; v_ttl DOUBLE PRECISION := p_ttl_s;
BEGIN
  PERFORM oracle_arc_private.spark_assert_app(p_app);
  IF p_user IS NULL OR p_user = '' THEN RAISE EXCEPTION 'user required' USING ERRCODE='22023'; END IF;
  IF NOT (p_namespace = ANY (COALESCE(p_allowed, ARRAY[]::TEXT[]))) THEN
    RAISE EXCEPTION 'agent may not use memory namespace' USING ERRCODE='42501';
  END IF;
  IF p_scope = 'task' AND v_ttl IS NULL THEN v_ttl := 3600; END IF;
  INSERT INTO oracle_arc_private.spark_memory (app_id, space, scope, owner, content, purpose, data_class, expires_at)
  VALUES (p_app, p_app || '/' || p_namespace, p_scope,
          oracle_arc_private.spark_owner(p_app, p_user, p_scope, p_scope_id), p_content, COALESCE(p_purpose,''),
          COALESCE(p_data_class, 1), CASE WHEN v_ttl IS NULL THEN NULL ELSE clock_timestamp() + make_interval(secs => v_ttl) END)
  RETURNING id INTO v_id;
  RETURN v_id;
END $f$;

CREATE FUNCTION oracle_arc_private.spark_recall(p_app TEXT, p_user TEXT, p_namespace TEXT, p_allowed TEXT[],
  p_query TEXT, p_k INTEGER, p_scope_ids TEXT[])
RETURNS TABLE (id UUID, space TEXT, scope TEXT, owner TEXT, content TEXT, purpose TEXT, data_class SMALLINT,
               created_at TIMESTAMPTZ, expires_at TIMESTAMPTZ, score REAL)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
DECLARE v_mine TEXT := p_app || '/' || p_namespace; v_q tsquery;
BEGIN
  PERFORM oracle_arc_private.spark_assert_app(p_app);
  IF NOT (p_namespace = ANY (COALESCE(p_allowed, ARRAY[]::TEXT[]))) THEN
    RAISE EXCEPTION 'agent may not use memory namespace' USING ERRCODE='42501';
  END IF;
  v_q := CASE WHEN COALESCE(trim(p_query),'') = '' THEN NULL ELSE plainto_tsquery('simple', p_query) END;
  RETURN QUERY
  SELECT m.id, m.space, m.scope, m.owner, m.content, m.purpose, m.data_class, m.created_at, m.expires_at,
         (CASE WHEN v_q IS NULL THEN 0 ELSE ts_rank(m.tsv, v_q) END)::REAL
  FROM oracle_arc_private.spark_memory m
  WHERE m.app_id = p_app
    AND (m.space = v_mine OR m.space IN (SELECT s.from_space FROM oracle_arc_private.spark_share s
                                         WHERE s.app_id = p_app AND s.user_id = p_user AND s.to_space = v_mine))
    AND (m.owner = p_user OR m.owner = p_app
         OR m.owner = ANY (SELECT p_user || ':' || x FROM unnest(COALESCE(p_scope_ids, ARRAY[]::TEXT[])) x))
    AND (m.expires_at IS NULL OR m.expires_at > clock_timestamp())
    AND (v_q IS NULL OR m.tsv @@ v_q)
  ORDER BY 10 DESC, m.created_at DESC
  LIMIT GREATEST(1, LEAST(COALESCE(p_k,5), 50));
END $f$;

-- User-controlled management (A10). Only the owning user's own personal/conversation/task memories.
CREATE FUNCTION oracle_arc_private.spark_list(p_app TEXT, p_user TEXT, p_limit INTEGER)
RETURNS TABLE (id UUID, space TEXT, scope TEXT, content TEXT, purpose TEXT, data_class SMALLINT,
               version INTEGER, created_at TIMESTAMPTZ, expires_at TIMESTAMPTZ)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
BEGIN
  PERFORM oracle_arc_private.spark_assert_app(p_app);
  RETURN QUERY SELECT m.id, m.space, m.scope, m.content, m.purpose, m.data_class, m.version, m.created_at, m.expires_at
  FROM oracle_arc_private.spark_memory m
  WHERE m.app_id = p_app AND (m.owner = p_user OR m.owner LIKE p_user || ':%')
    AND (m.expires_at IS NULL OR m.expires_at > clock_timestamp())
  ORDER BY m.created_at DESC LIMIT GREATEST(1, LEAST(COALESCE(p_limit,100), 500));
END $f$;

CREATE FUNCTION oracle_arc_private.spark_correct(p_app TEXT, p_user TEXT, p_id UUID, p_content TEXT)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
DECLARE n INTEGER;
BEGIN
  PERFORM oracle_arc_private.spark_assert_app(p_app);
  UPDATE oracle_arc_private.spark_memory SET content = p_content, version = version + 1, updated_at = clock_timestamp()
  WHERE id = p_id AND app_id = p_app AND (owner = p_user OR owner LIKE p_user || ':%');
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n > 0;
END $f$;

CREATE FUNCTION oracle_arc_private.spark_forget(p_app TEXT, p_user TEXT, p_id UUID)
RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
DECLARE n INTEGER;
BEGIN
  PERFORM oracle_arc_private.spark_assert_app(p_app);
  DELETE FROM oracle_arc_private.spark_memory
  WHERE id = p_id AND app_id = p_app AND (owner = p_user OR owner LIKE p_user || ':%');
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n > 0;
END $f$;

CREATE FUNCTION oracle_arc_private.spark_forget_all(p_app TEXT, p_user TEXT) RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
DECLARE n INTEGER;
BEGIN
  PERFORM oracle_arc_private.spark_assert_app(p_app);
  DELETE FROM oracle_arc_private.spark_memory WHERE app_id = p_app AND (owner = p_user OR owner LIKE p_user || ':%');
  GET DIAGNOSTICS n = ROW_COUNT;
  DELETE FROM oracle_arc_private.spark_share WHERE app_id = p_app AND user_id = p_user;
  RETURN n;
END $f$;

CREATE FUNCTION oracle_arc_private.spark_share(p_app TEXT, p_user TEXT, p_from TEXT, p_to TEXT) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
BEGIN
  PERFORM oracle_arc_private.spark_assert_app(p_app);
  INSERT INTO oracle_arc_private.spark_share (app_id, user_id, from_space, to_space)
  VALUES (p_app, p_user, p_app || '/' || p_from, p_app || '/' || p_to) ON CONFLICT DO NOTHING;
END $f$;

CREATE FUNCTION oracle_arc_private.spark_unshare(p_app TEXT, p_user TEXT, p_from TEXT, p_to TEXT) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
BEGIN
  PERFORM oracle_arc_private.spark_assert_app(p_app);
  DELETE FROM oracle_arc_private.spark_share
  WHERE app_id = p_app AND user_id = p_user AND from_space = p_app || '/' || p_from AND to_space = p_app || '/' || p_to;
END $f$;

CREATE FUNCTION oracle_arc_private.spark_purge_expired() RETURNS INTEGER
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, oracle_arc_private AS $f$
DECLARE n INTEGER;
BEGIN
  DELETE FROM oracle_arc_private.spark_memory WHERE expires_at IS NOT NULL AND expires_at <= clock_timestamp();
  GET DIAGNOSTICS n = ROW_COUNT;
  RETURN n;
END $f$;

DO $g$
DECLARE f TEXT;
BEGIN
  FOREACH f IN ARRAY ARRAY[
    'spark_assert_app(text)','spark_owner(text,text,text,text)',
    'spark_remember(text,text,text,text[],text,text,text,smallint,double precision,text)',
    'spark_recall(text,text,text,text[],text,integer,text[])','spark_list(text,text,integer)',
    'spark_correct(text,text,uuid,text)','spark_forget(text,text,uuid)','spark_forget_all(text,text)',
    'spark_share(text,text,text,text)','spark_unshare(text,text,text,text)','spark_purge_expired()']
  LOOP
    EXECUTE format('ALTER FUNCTION oracle_arc_private.%s OWNER TO oracle_arc_owner', f);
    EXECUTE format('REVOKE ALL ON FUNCTION oracle_arc_private.%s FROM PUBLIC', f);
    IF f NOT LIKE 'spark_assert_app%' AND f NOT LIKE 'spark_owner%' THEN
      EXECUTE format('GRANT EXECUTE ON FUNCTION oracle_arc_private.%s TO oracle_arc_runtime', f);
    END IF;
  END LOOP;
END $g$;

COMMIT;
