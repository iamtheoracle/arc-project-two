\set ON_ERROR_STOP on
BEGIN;

-- Provisioner can create durable host configuration through its dedicated role.
SET LOCAL ROLE oracle_arc_provisioner;
INSERT INTO oracle_arc_private.applications(app_id,salt,secret_hash,scopes)
VALUES ('test-app',decode(repeat('11',16),'hex'),decode(repeat('22',32),'hex'),ARRAY['chat']);
INSERT INTO oracle_arc_private.agents(name,version,role,system_prompt,max_risk,memory_namespaces)
VALUES ('unibud:bud','1.0.0','UNIBUD companion','Read-only registered host agent.',0,ARRAY[]::TEXT[]);
INSERT INTO oracle_arc_private.tools(name,description,risk,parameters,data_class)
VALUES ('read_profile','Read an approved profile',0,'{"type":"object","properties":{}}'::JSONB,2);
INSERT INTO oracle_arc_private.tool_grants(agent_name,tool_name,granted_by)
VALUES ('unibud:bud','read_profile','founder-approved-host-config');
RESET ROLE;

-- Runtime can read agent/tool/grant configuration but cannot read app credential rows.
SET LOCAL ROLE oracle_arc_runtime;
DO $runtime$
DECLARE n INTEGER; app_visible BOOLEAN;
BEGIN
  SELECT count(*) INTO n FROM oracle_arc_private.agents;
  IF n<>1 THEN RAISE EXCEPTION 'runtime agent catalogue read failed'; END IF;
  SELECT count(*) INTO n FROM oracle_arc_private.tools;
  IF n<>1 THEN RAISE EXCEPTION 'runtime tool catalogue read failed'; END IF;
  SELECT count(*) INTO n FROM oracle_arc_private.tool_grants;
  IF n<>1 THEN RAISE EXCEPTION 'runtime grant catalogue read failed'; END IF;

  IF has_table_privilege(current_user,'oracle_arc_private.applications','SELECT') THEN
    RAISE EXCEPTION 'runtime role has direct application credential table access';
  END IF;
  BEGIN
    EXECUTE 'SELECT app_id FROM oracle_arc_private.applications';
    RAISE EXCEPTION 'runtime role directly read application credential rows';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;

  SELECT EXISTS(
    SELECT 1 FROM oracle_arc_private.get_application('test-app') AS app
    WHERE app.app_id='test-app'
      AND octet_length(app.salt)=16
      AND octet_length(app.secret_hash)=32
      AND app.scopes=ARRAY['chat']::TEXT[]
      AND app.suspended=false
      AND app.token_epoch=0
  ) INTO app_visible;
  IF NOT app_visible THEN RAISE EXCEPTION 'narrow application lookup function failed'; END IF;

  IF EXISTS(SELECT 1 FROM oracle_arc_private.get_application('missing-app')) THEN
    RAISE EXCEPTION 'application lookup returned a non-existent app';
  END IF;

  BEGIN
    EXECUTE 'INSERT INTO oracle_arc_private.agents(name,version,role,system_prompt) VALUES (''forged'',''1.0.0'',''x'',''x'')';
    RAISE EXCEPTION 'runtime role inserted agent configuration';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;

  BEGIN
    EXECUTE 'DELETE FROM oracle_arc_private.tool_grants';
    RAISE EXCEPTION 'runtime role modified tool grants';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;

  BEGIN
    EXECUTE 'SET ROLE oracle_arc_provisioner';
    RAISE EXCEPTION 'runtime role assumed provisioner';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END
$runtime$;
RESET ROLE;

-- Provisioner cannot access unlisted schemas or elevate into the owner role.
SET LOCAL ROLE oracle_arc_provisioner;
DO $provisioner$
BEGIN
  IF has_schema_privilege(current_user,'public','CREATE') THEN
    RAISE EXCEPTION 'provisioner can create objects in public schema';
  END IF;
  BEGIN
    EXECUTE 'SET ROLE oracle_arc_owner';
    RAISE EXCEPTION 'provisioner assumed owner role';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
END
$provisioner$;
RESET ROLE;

ROLLBACK;
