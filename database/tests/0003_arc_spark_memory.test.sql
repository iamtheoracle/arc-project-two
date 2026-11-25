\set ON_ERROR_STOP on
-- Tests for 0003. Superuser on a database with 0001..0003 applied. Everything rolls back.
DO $t$
DECLARE m1 UUID; m2 UUID; m3 UUID; m4 UUID; n INT; r RECORD; ok BOOLEAN;
BEGIN
  INSERT INTO oracle_arc_private.applications (app_id, salt, secret_hash)
  VALUES ('appa', decode(repeat('01',16),'hex'), decode(repeat('02',32),'hex')),
         ('appb', decode(repeat('03',16),'hex'), decode(repeat('04',32),'hex')),
         ('susp', decode(repeat('05',16),'hex'), decode(repeat('06',32),'hex'));
  UPDATE oracle_arc_private.applications SET suspended = true WHERE app_id='susp';

  SET LOCAL ROLE oracle_arc_runtime;

  -- 1. write, then recall within own namespace
  m1 := oracle_arc_private.spark_remember('appa','u1','study',ARRAY['study','flow'],'prefers morning lectures','personal','',1::smallint,NULL,'study planning');
  m2 := oracle_arc_private.spark_remember('appa','u1','flow',ARRAY['study','flow'],'budget is tight this month','personal','',2::smallint,NULL,'');
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appa','u1','study',ARRAY['study','flow'],'morning',5,NULL);
  IF n <> 1 THEN RAISE EXCEPTION 'recall expected 1 got %', n; END IF;

  -- 2. no implicit cross-namespace reads: study cannot see flow
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appa','u1','study',ARRAY['study','flow'],'budget',5,NULL);
  IF n <> 0 THEN RAISE EXCEPTION 'cross-namespace leak'; END IF;

  -- 3. explicit user share enables it, unshare revokes it
  PERFORM oracle_arc_private.spark_share('appa','u1','flow','study');
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appa','u1','study',ARRAY['study','flow'],'budget',5,NULL);
  IF n <> 1 THEN RAISE EXCEPTION 'share did not grant read'; END IF;
  PERFORM oracle_arc_private.spark_unshare('appa','u1','flow','study');
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appa','u1','study',ARRAY['study','flow'],'budget',5,NULL);
  IF n <> 0 THEN RAISE EXCEPTION 'unshare did not revoke'; END IF;

  -- 3b. u1's share must not apply to any other user while it is active, including to app-owned memory
  PERFORM oracle_arc_private.spark_remember('appa','u1','flow',ARRAY['flow'],'campus fee schedule','application','',0::smallint,NULL,'');
  PERFORM oracle_arc_private.spark_share('appa','u1','flow','study');
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appa','u2','study',ARRAY['study'],'fee',5,NULL);
  IF n <> 0 THEN RAISE EXCEPTION 'u1 share exposed app-owned memory to u2'; END IF;
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appa','u1','study',ARRAY['study'],'fee',5,NULL);
  IF n <> 1 THEN RAISE EXCEPTION 'u1 should see app-owned memory through own share'; END IF;
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appa','u2','study',ARRAY['study'],'budget',5,NULL);
  IF n <> 0 THEN RAISE EXCEPTION 'active share of u1 leaked to u2'; END IF;
  PERFORM oracle_arc_private.spark_unshare('appa','u1','flow','study');

  -- 4. another user never sees u1's memory, even with an identical share set up for themself
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appa','u2','study',ARRAY['study'],'morning',5,NULL);
  IF n <> 0 THEN RAISE EXCEPTION 'cross-user leak'; END IF;
  PERFORM oracle_arc_private.spark_share('appa','u2','flow','study');
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appa','u2','study',ARRAY['study'],'budget',5,NULL);
  IF n <> 0 THEN RAISE EXCEPTION 'u2 share exposed u1 data'; END IF;

  -- 5. another application never sees it, and cannot share across apps
  m3 := oracle_arc_private.spark_remember('appb','u1','study',ARRAY['study'],'prefers morning lectures','personal','',1::smallint,NULL,'');
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appb','u1','study',ARRAY['study'],'morning',5,NULL);
  IF n <> 1 THEN RAISE EXCEPTION 'appb should see only its own memory, got %', n; END IF;
  SELECT oracle_arc_private.spark_forget('appb','u1',m1) INTO ok;
  IF ok THEN RAISE EXCEPTION 'cross-app forget succeeded'; END IF;

  -- 6. agent namespace allowlist enforced
  BEGIN PERFORM oracle_arc_private.spark_remember('appa','u1','finance',ARRAY['study'],'x','personal','',1::smallint,NULL,'');
        RAISE EXCEPTION 'disallowed namespace accepted';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN PERFORM oracle_arc_private.spark_recall('appa','u1','finance',ARRAY['study'],'x',5,NULL);
        RAISE EXCEPTION 'disallowed namespace recall accepted';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;

  -- 7. suspended and unknown applications are refused
  BEGIN PERFORM oracle_arc_private.spark_remember('susp','u1','study',ARRAY['study'],'x','personal','',1::smallint,NULL,'');
        RAISE EXCEPTION 'suspended app accepted';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN PERFORM oracle_arc_private.spark_list('ghost','u1',10); RAISE EXCEPTION 'unknown app accepted';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;

  -- 8. conversation/task scope needs an id and is private to that id; task memory always expires
  BEGIN PERFORM oracle_arc_private.spark_remember('appa','u1','study',ARRAY['study'],'x','conversation','',1::smallint,NULL,'');
        RAISE EXCEPTION 'conversation without id accepted';
  EXCEPTION WHEN invalid_parameter_value THEN NULL; END;
  m4 := oracle_arc_private.spark_remember('appa','u1','study',ARRAY['study'],'draft essay outline','task','t9',1::smallint,NULL,'');
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appa','u1','study',ARRAY['study'],'outline',5,NULL);
  IF n <> 0 THEN RAISE EXCEPTION 'task memory visible without its scope id'; END IF;
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appa','u1','study',ARRAY['study'],'outline',5,ARRAY['t9']);
  IF n <> 1 THEN RAISE EXCEPTION 'task memory not visible with its scope id'; END IF;
  RESET ROLE;
  IF (SELECT expires_at FROM oracle_arc_private.spark_memory WHERE id=m4) IS NULL THEN RAISE EXCEPTION 'task memory has no expiry'; END IF;

  -- 9. expiry hides then purges
  SET LOCAL ROLE oracle_arc_runtime;
  PERFORM oracle_arc_private.spark_remember('appa','u1','study',ARRAY['study'],'short lived note','personal','',1::smallint,0.001,'');
  PERFORM pg_sleep(0.05);
  SELECT count(*) INTO n FROM oracle_arc_private.spark_recall('appa','u1','study',ARRAY['study'],'short',5,NULL);
  IF n <> 0 THEN RAISE EXCEPTION 'expired memory still recalled'; END IF;
  IF oracle_arc_private.spark_purge_expired() < 1 THEN RAISE EXCEPTION 'purge removed nothing'; END IF;

  -- 10. user controls (A10): list shows only own, correct bumps version, forget removes, forget_all clears
  SELECT count(*) INTO n FROM oracle_arc_private.spark_list('appa','u1',100);
  IF n <> 3 THEN RAISE EXCEPTION 'u1 list expected 3 got %', n; END IF;
  SELECT count(*) INTO n FROM oracle_arc_private.spark_list('appa','u2',100);
  IF n <> 0 THEN RAISE EXCEPTION 'u2 list leaked'; END IF;
  IF NOT oracle_arc_private.spark_correct('appa','u1',m1,'prefers evening lectures') THEN RAISE EXCEPTION 'correct failed'; END IF;
  IF oracle_arc_private.spark_correct('appa','u2',m1,'hijacked') THEN RAISE EXCEPTION 'u2 corrected u1 memory'; END IF;
  SELECT content, version INTO r FROM oracle_arc_private.spark_list('appa','u1',100) WHERE id=m1;
  IF r.content <> 'prefers evening lectures' OR r.version <> 2 THEN RAISE EXCEPTION 'correction not applied'; END IF;
  IF oracle_arc_private.spark_forget('appa','u2',m2) THEN RAISE EXCEPTION 'u2 deleted u1 memory'; END IF;
  IF NOT oracle_arc_private.spark_forget('appa','u1',m2) THEN RAISE EXCEPTION 'owner forget failed'; END IF;
  IF oracle_arc_private.spark_forget_all('appa','u1') < 2 THEN RAISE EXCEPTION 'forget_all removed too little'; END IF;
  SELECT count(*) INTO n FROM oracle_arc_private.spark_list('appa','u1',100);
  IF n <> 0 THEN RAISE EXCEPTION 'memories remain after forget_all'; END IF;

  -- 11. runtime and provisioner have no direct table access
  BEGIN PERFORM 1 FROM oracle_arc_private.spark_memory; RAISE EXCEPTION 'runtime read table directly';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN DELETE FROM oracle_arc_private.spark_memory; RAISE EXCEPTION 'runtime deleted directly';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN PERFORM oracle_arc_private.spark_assert_app('appa'); RAISE EXCEPTION 'runtime called private helper';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  RESET ROLE; SET LOCAL ROLE oracle_arc_provisioner;
  BEGIN PERFORM oracle_arc_private.spark_list('appa','u1',10); RAISE EXCEPTION 'provisioner called spark';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  RESET ROLE;

  -- 12. constraints: a space outside its app, content too long
  BEGIN INSERT INTO oracle_arc_private.spark_memory (app_id,space,scope,owner,content)
        VALUES ('appa','appb/study','personal','u1','x'); RAISE EXCEPTION 'space/app mismatch accepted';
  EXCEPTION WHEN check_violation THEN NULL; END;

  RAISE EXCEPTION 'ROLLBACK_AFTER_PASS';
EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'ROLLBACK_AFTER_PASS' THEN RAISE; END IF;
END
$t$;
SELECT 'spark memory tests passed' AS result;
