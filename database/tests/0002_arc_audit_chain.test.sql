\set ON_ERROR_STOP on
-- Tests for 0002. Run as a superuser on a database where 0001 and 0002 are applied.
-- Each negative case must fail for the stated reason; a case that passes silently aborts the run.
DO $t$
DECLARE s1 BIGINT; s2 BIGINT; s3 BIGINT; bad BIGINT; h RECORD; n INT;
BEGIN
  SET LOCAL ROLE oracle_arc_runtime;

  -- 1. runtime can append and the chain verifies
  s1 := oracle_arc_private.append_audit('app.token', 'host', 'u1', 'a1', '{"k":1}');
  s2 := oracle_arc_private.append_audit('tool.run', 'host', 'u1', 'a1', '{"tool":"calc"}');
  s3 := oracle_arc_private.append_audit('app.token', 'other', 'u2', '', NULL);
  IF NOT (s1 < s2 AND s2 < s3) THEN RAISE EXCEPTION 'sequence not increasing'; END IF;
  IF oracle_arc_private.verify_audit_chain() IS NOT NULL THEN RAISE EXCEPTION 'fresh chain failed verification'; END IF;

  -- 2. head matches the last row
  SELECT * INTO h FROM oracle_arc_private.audit_head();
  IF h.seq <> s3 OR length(h.hash) <> 64 THEN RAISE EXCEPTION 'audit_head wrong'; END IF;

  -- 3. runtime has no direct table access of any kind
  BEGIN PERFORM 1 FROM oracle_arc_private.audit_log; RAISE EXCEPTION 'runtime SELECT allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN INSERT INTO oracle_arc_private.audit_log(ts_us,event,prev,hash)
        VALUES (1,'x',decode(repeat('00',32),'hex'),decode(repeat('11',32),'hex'));
        RAISE EXCEPTION 'runtime INSERT allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN UPDATE oracle_arc_private.audit_log SET event='x'; RAISE EXCEPTION 'runtime UPDATE allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN DELETE FROM oracle_arc_private.audit_log; RAISE EXCEPTION 'runtime DELETE allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN TRUNCATE oracle_arc_private.audit_log; RAISE EXCEPTION 'runtime TRUNCATE allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;

  -- 4. provisioner has no access either
  RESET ROLE; SET LOCAL ROLE oracle_arc_provisioner;
  BEGIN PERFORM oracle_arc_private.append_audit('x','','','',NULL); RAISE EXCEPTION 'provisioner append allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  RESET ROLE;

  -- 5. even the owner cannot rewrite history (trigger)
  SET LOCAL ROLE oracle_arc_owner;
  BEGIN UPDATE oracle_arc_private.audit_log SET event='forged' WHERE seq=s1; RAISE EXCEPTION 'owner UPDATE allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN DELETE FROM oracle_arc_private.audit_log WHERE seq=s2; RAISE EXCEPTION 'owner DELETE allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  BEGIN TRUNCATE oracle_arc_private.audit_log; RAISE EXCEPTION 'owner TRUNCATE allowed';
  EXCEPTION WHEN insufficient_privilege THEN NULL; END;
  RESET ROLE;

  -- 6. a privileged attacker who disables the trigger is DETECTED, at the tampered row
  ALTER TABLE oracle_arc_private.audit_log DISABLE TRIGGER audit_no_update_delete;
  UPDATE oracle_arc_private.audit_log SET detail='{"k":999}' WHERE seq=s1;
  bad := oracle_arc_private.verify_audit_chain();
  IF bad IS DISTINCT FROM s1 THEN RAISE EXCEPTION 'tampered detail not detected at %, got %', s1, bad; END IF;
  UPDATE oracle_arc_private.audit_log SET detail='{"k":1}' WHERE seq=s1;
  IF oracle_arc_private.verify_audit_chain() IS NOT NULL THEN RAISE EXCEPTION 'restore did not re-verify'; END IF;

  -- 7. deleting a middle row breaks the link at the next row
  DELETE FROM oracle_arc_private.audit_log WHERE seq=s2;
  bad := oracle_arc_private.verify_audit_chain();
  IF bad IS DISTINCT FROM s3 THEN RAISE EXCEPTION 'deleted row not detected at %, got %', s3, bad; END IF;
  ALTER TABLE oracle_arc_private.audit_log ENABLE TRIGGER audit_no_update_delete;

  -- 8. constraints reject malformed rows even via the append function
  BEGIN PERFORM oracle_arc_private.append_audit('', '', '', '', NULL); RAISE EXCEPTION 'empty event accepted';
  EXCEPTION WHEN check_violation THEN NULL; END;
  BEGIN PERFORM oracle_arc_private.append_audit('e', '', '', '', '[1]'::jsonb); RAISE EXCEPTION 'non-object detail accepted';
  EXCEPTION WHEN check_violation THEN NULL; END;

  RAISE EXCEPTION 'ROLLBACK_AFTER_PASS';
EXCEPTION WHEN raise_exception THEN
  IF SQLERRM <> 'ROLLBACK_AFTER_PASS' THEN RAISE; END IF;
END
$t$;
SELECT 'audit chain tests passed' AS result;
