\set ON_ERROR_STOP on
-- Tests for 0004 (single process). Concurrency is in 0004_arc_confirmations_concurrency.sh.
DO $t$
DECLARE h TEXT := repeat('a',64); r RECORD; exp TIMESTAMPTZ; stored INT;
BEGIN
  INSERT INTO oracle_arc_private.applications (app_id, salt, secret_hash)
  VALUES ('appa', decode(repeat('01',16),'hex'), decode(repeat('02',32),'hex')),
         ('appb', decode(repeat('03',16),'hex'), decode(repeat('04',32),'hex'));
  SET LOCAL ROLE oracle_arc_runtime;

  -- 1. create then consume once, returning the bound action
  exp := oracle_arc_private.confirmation_create('appa','u1','chal-0000000000001','concierge','book_provider',
         '{"provider":"p1","amount":"20"}','Book p1 for 20',2::smallint,h,300);
  IF exp <= clock_timestamp() THEN RAISE EXCEPTION 'bad expiry'; END IF;
  SELECT * INTO r FROM oracle_arc_private.confirmation_consume('appa','u1','chal-0000000000001',h,true);
  IF r.tool <> 'book_provider' OR r.args->>'amount' <> '20' THEN RAISE EXCEPTION 'wrong action returned'; END IF;

  -- 2. replay fails
  BEGIN PERFORM oracle_arc_private.confirmation_consume('appa','u1','chal-0000000000001',h,true);
        RAISE EXCEPTION 'replay accepted';
  EXCEPTION WHEN SQLSTATE 'AC003' THEN NULL; END;

  -- 3. wrong user and wrong app are refused and do NOT burn the challenge
  PERFORM oracle_arc_private.confirmation_create('appa','u1','chal-0000000000002','a','t','{}','s',0::smallint,h,300);
  BEGIN PERFORM oracle_arc_private.confirmation_consume('appa','u2','chal-0000000000002',h,true);
        RAISE EXCEPTION 'wrong user accepted';
  EXCEPTION WHEN SQLSTATE 'AC002' THEN NULL; END;
  BEGIN PERFORM oracle_arc_private.confirmation_consume('appb','u1','chal-0000000000002',h,true);
        RAISE EXCEPTION 'wrong app accepted';
  EXCEPTION WHEN SQLSTATE 'AC002' THEN NULL; END;
  PERFORM oracle_arc_private.confirmation_consume('appa','u1','chal-0000000000002',h,true);

  -- 4. hash mismatch refused (action tampering) and does not burn
  PERFORM oracle_arc_private.confirmation_create('appa','u1','chal-0000000000003','a','t','{}','s',0::smallint,h,300);
  BEGIN PERFORM oracle_arc_private.confirmation_consume('appa','u1','chal-0000000000003',repeat('b',64),true);
        RAISE EXCEPTION 'hash mismatch accepted';
  EXCEPTION WHEN SQLSTATE 'AC005' THEN NULL; END;
  PERFORM oracle_arc_private.confirmation_consume('appa','u1','chal-0000000000003',h,true);

  -- 5. step-up required from FINANCIAL (risk>=2) upward, not for READ/WRITE; failure does not burn
  PERFORM oracle_arc_private.confirmation_create('appa','u1','chal-0000000000004','a','t','{}','s',2::smallint,h,300);
  BEGIN PERFORM oracle_arc_private.confirmation_consume('appa','u1','chal-0000000000004',h,false);
        RAISE EXCEPTION 'financial accepted without step-up';
  EXCEPTION WHEN SQLSTATE 'AC006' THEN NULL; END;
  BEGIN PERFORM oracle_arc_private.confirmation_consume('appa','u1','chal-0000000000004',h,NULL);
        RAISE EXCEPTION 'financial accepted with NULL step-up';
  EXCEPTION WHEN SQLSTATE 'AC006' THEN NULL; END;
  PERFORM oracle_arc_private.confirmation_consume('appa','u1','chal-0000000000004',h,true);
  PERFORM oracle_arc_private.confirmation_create('appa','u1','chal-0000000000005','a','t','{}','s',1::smallint,h,300);
  PERFORM oracle_arc_private.confirmation_consume('appa','u1','chal-0000000000005',h,false);

  -- 6. unknown id, expiry
  BEGIN PERFORM oracle_arc_private.confirmation_consume('appa','u1','never-issued-0000000',h,true);
        RAISE EXCEPTION 'unknown accepted';
  EXCEPTION WHEN SQLSTATE 'AC001' THEN NULL; END;
  PERFORM oracle_arc_private.confirmation_create('appa','u1','chal-0000000000006','a','t','{}','s',0::smallint,h,0.001);
  PERFORM pg_sleep(0.05);
  BEGIN PERFORM oracle_arc_private.confirmation_consume('appa','u1','chal-0000000000006',h,true);
        RAISE EXCEPTION 'expired accepted';
  EXCEPTION WHEN SQLSTATE 'AC004' THEN NULL; END;

  -- 7. input limits
  BEGIN PERFORM oracle_arc_private.confirmation_create('appa','u1','short','a','t','{}','s',0::smallint,h,300);
        RAISE EXCEPTION 'short id accepted';
  EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
  BEGIN PERFORM oracle_arc_private.confirmation_create('appa','u1','chal-0000000000007','a','t','{}','s',0::smallint,h,86400);
        RAISE EXCEPTION 'ttl > 1h accepted';
  EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
  BEGIN PERFORM oracle_arc_private.confirmation_create('ghost','u1','chal-0000000000008','a','t','{}','s',0::smallint,h,300);
        RAISE EXCEPTION 'unknown app accepted';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;

  -- 8. no direct table access; provisioner has none
  BEGIN PERFORM 1 FROM oracle_arc_private.confirmations; RAISE EXCEPTION 'runtime read table';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN UPDATE oracle_arc_private.confirmations SET used_at = NULL; RAISE EXCEPTION 'runtime reset used_at';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  RESET ROLE; SET LOCAL ROLE oracle_arc_provisioner;
  BEGIN PERFORM oracle_arc_private.confirmation_purge(); RAISE EXCEPTION 'provisioner ran purge';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  RESET ROLE;

  -- 9. the plaintext challenge id is never stored
  SELECT count(*) INTO stored FROM oracle_arc_private.confirmations WHERE encode(id_hash,'escape') LIKE '%chal-%';
  IF stored <> 0 THEN RAISE EXCEPTION 'plaintext id stored'; END IF;

  RAISE EXCEPTION 'ROLLBACK_AFTER_PASS';
EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'ROLLBACK_AFTER_PASS' THEN RAISE; END IF;
END
$t$;
SELECT 'confirmation tests passed' AS result;
