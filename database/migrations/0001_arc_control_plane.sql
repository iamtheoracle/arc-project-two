-- Oracle Arc A8: persistent application, agent, tool catalogue and grant configuration.
-- Apply only with an authorised migration principal. Runtime roles are NOLOGIN group roles.
BEGIN;

DO $roles$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='oracle_arc_owner') THEN
    CREATE ROLE oracle_arc_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='oracle_arc_runtime') THEN
    CREATE ROLE oracle_arc_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='oracle_arc_provisioner') THEN
    CREATE ROLE oracle_arc_provisioner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;
  END IF;
END
$roles$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA IF NOT EXISTS oracle_arc_private AUTHORIZATION oracle_arc_owner;
ALTER SCHEMA oracle_arc_private OWNER TO oracle_arc_owner;
REVOKE ALL ON SCHEMA oracle_arc_private FROM PUBLIC;
GRANT USAGE ON SCHEMA oracle_arc_private TO oracle_arc_runtime,oracle_arc_provisioner;

CREATE TABLE oracle_arc_private.applications (
  app_id TEXT PRIMARY KEY CHECK (app_id ~ '^[a-z][a-z0-9_.-]{1,63}$'),
  salt BYTEA NOT NULL CHECK (octet_length(salt)=16),
  secret_hash BYTEA NOT NULL CHECK (octet_length(secret_hash)=32),
  scopes TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  suspended BOOLEAN NOT NULL DEFAULT FALSE,
  token_epoch BIGINT NOT NULL DEFAULT 0 CHECK (token_epoch>=0),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (array_position(scopes,NULL) IS NULL),
  CHECK (cardinality(scopes)<=64)
);

CREATE TABLE oracle_arc_private.agents (
  name TEXT PRIMARY KEY CHECK (name ~ '^[a-z][a-z0-9:_-]{1,95}$'),
  version TEXT NOT NULL CHECK (version ~ '^[0-9]+[.][0-9]+[.][0-9]+$'),
  role TEXT NOT NULL CHECK (length(trim(role)) BETWEEN 1 AND 240),
  system_prompt TEXT NOT NULL CHECK (length(system_prompt) BETWEEN 1 AND 24000),
  max_risk SMALLINT NOT NULL DEFAULT 0 CHECK (max_risk BETWEEN 0 AND 3),
  memory_namespaces TEXT[] NOT NULL DEFAULT ARRAY[]::TEXT[],
  state TEXT NOT NULL DEFAULT 'active' CHECK (state IN ('active','suspended','retired')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  CHECK (array_position(memory_namespaces,NULL) IS NULL),
  CHECK (cardinality(memory_namespaces)<=32)
);

CREATE TABLE oracle_arc_private.tools (
  name TEXT PRIMARY KEY CHECK (name ~ '^[a-z][a-z0-9_.-]{1,95}$'),
  description TEXT NOT NULL CHECK (length(trim(description)) BETWEEN 1 AND 1000),
  risk SMALLINT NOT NULL CHECK (risk BETWEEN 0 AND 3),
  parameters JSONB NOT NULL CHECK (jsonb_typeof(parameters)='object'),
  data_class SMALLINT NOT NULL DEFAULT 1 CHECK (data_class BETWEEN 0 AND 3),
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE oracle_arc_private.tool_grants (
  agent_name TEXT NOT NULL REFERENCES oracle_arc_private.agents(name) ON DELETE RESTRICT,
  tool_name TEXT NOT NULL REFERENCES oracle_arc_private.tools(name) ON DELETE RESTRICT,
  granted_by TEXT NOT NULL CHECK (length(trim(granted_by)) BETWEEN 1 AND 128),
  granted_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
  PRIMARY KEY(agent_name,tool_name)
);

ALTER TABLE oracle_arc_private.applications OWNER TO oracle_arc_owner;
ALTER TABLE oracle_arc_private.agents OWNER TO oracle_arc_owner;
ALTER TABLE oracle_arc_private.tools OWNER TO oracle_arc_owner;
ALTER TABLE oracle_arc_private.tool_grants OWNER TO oracle_arc_owner;

ALTER TABLE oracle_arc_private.applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE oracle_arc_private.applications FORCE ROW LEVEL SECURITY;
ALTER TABLE oracle_arc_private.agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE oracle_arc_private.agents FORCE ROW LEVEL SECURITY;
ALTER TABLE oracle_arc_private.tools ENABLE ROW LEVEL SECURITY;
ALTER TABLE oracle_arc_private.tools FORCE ROW LEVEL SECURITY;
ALTER TABLE oracle_arc_private.tool_grants ENABLE ROW LEVEL SECURITY;
ALTER TABLE oracle_arc_private.tool_grants FORCE ROW LEVEL SECURITY;

CREATE POLICY applications_owner_all ON oracle_arc_private.applications
  FOR ALL TO oracle_arc_owner USING (current_user='oracle_arc_owner') WITH CHECK (current_user='oracle_arc_owner');
CREATE POLICY applications_provisioner_all ON oracle_arc_private.applications
  FOR ALL TO oracle_arc_provisioner USING (pg_has_role(current_user,'oracle_arc_provisioner','member')) WITH CHECK (pg_has_role(current_user,'oracle_arc_provisioner','member'));

CREATE POLICY agents_owner_all ON oracle_arc_private.agents
  FOR ALL TO oracle_arc_owner USING (current_user='oracle_arc_owner') WITH CHECK (current_user='oracle_arc_owner');
CREATE POLICY agents_provisioner_all ON oracle_arc_private.agents
  FOR ALL TO oracle_arc_provisioner USING (pg_has_role(current_user,'oracle_arc_provisioner','member')) WITH CHECK (pg_has_role(current_user,'oracle_arc_provisioner','member'));
CREATE POLICY agents_runtime_read ON oracle_arc_private.agents
  FOR SELECT TO oracle_arc_runtime USING (true);

CREATE POLICY tools_owner_all ON oracle_arc_private.tools
  FOR ALL TO oracle_arc_owner USING (current_user='oracle_arc_owner') WITH CHECK (current_user='oracle_arc_owner');
CREATE POLICY tools_provisioner_all ON oracle_arc_private.tools
  FOR ALL TO oracle_arc_provisioner USING (pg_has_role(current_user,'oracle_arc_provisioner','member')) WITH CHECK (pg_has_role(current_user,'oracle_arc_provisioner','member'));
CREATE POLICY tools_runtime_read ON oracle_arc_private.tools
  FOR SELECT TO oracle_arc_runtime USING (true);

CREATE POLICY grants_owner_all ON oracle_arc_private.tool_grants
  FOR ALL TO oracle_arc_owner USING (current_user='oracle_arc_owner') WITH CHECK (current_user='oracle_arc_owner');
CREATE POLICY grants_provisioner_all ON oracle_arc_private.tool_grants
  FOR ALL TO oracle_arc_provisioner USING (pg_has_role(current_user,'oracle_arc_provisioner','member')) WITH CHECK (pg_has_role(current_user,'oracle_arc_provisioner','member'));
CREATE POLICY grants_runtime_read ON oracle_arc_private.tool_grants
  FOR SELECT TO oracle_arc_runtime USING (true);

REVOKE ALL ON ALL TABLES IN SCHEMA oracle_arc_private FROM PUBLIC,oracle_arc_runtime,oracle_arc_provisioner;
GRANT SELECT ON oracle_arc_private.agents,oracle_arc_private.tools,oracle_arc_private.tool_grants TO oracle_arc_runtime;
GRANT SELECT,INSERT,UPDATE,DELETE ON oracle_arc_private.applications,
  oracle_arc_private.agents,oracle_arc_private.tools,oracle_arc_private.tool_grants TO oracle_arc_provisioner;
GRANT SELECT ON oracle_arc_private.applications TO oracle_arc_owner;
GRANT SELECT,INSERT,UPDATE,DELETE ON oracle_arc_private.agents,
  oracle_arc_private.tools,oracle_arc_private.tool_grants TO oracle_arc_owner;

CREATE FUNCTION oracle_arc_private.get_application(p_app_id TEXT)
RETURNS TABLE(app_id TEXT,salt BYTEA,secret_hash BYTEA,scopes TEXT[],suspended BOOLEAN,token_epoch BIGINT)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path=pg_catalog,oracle_arc_private
AS $function$
  SELECT a.app_id,a.salt,a.secret_hash,a.scopes,a.suspended,a.token_epoch
  FROM oracle_arc_private.applications AS a
  WHERE a.app_id=p_app_id
$function$;
ALTER FUNCTION oracle_arc_private.get_application(TEXT) OWNER TO oracle_arc_owner;
REVOKE ALL ON FUNCTION oracle_arc_private.get_application(TEXT) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION oracle_arc_private.get_application(TEXT) TO oracle_arc_runtime;

REVOKE CREATE ON SCHEMA public FROM oracle_arc_owner,oracle_arc_runtime,oracle_arc_provisioner;
REVOKE ALL ON SCHEMA oracle_arc_private FROM PUBLIC;
GRANT USAGE ON SCHEMA oracle_arc_private TO oracle_arc_runtime,oracle_arc_provisioner;
COMMIT;
