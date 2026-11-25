-- Rollback for 0004. Pending confirmations are discarded (users must re-confirm).
BEGIN;
DROP FUNCTION IF EXISTS oracle_arc_private.confirmation_purge();
DROP FUNCTION IF EXISTS oracle_arc_private.confirmation_consume(text,text,text,text,boolean);
DROP FUNCTION IF EXISTS oracle_arc_private.confirmation_create(text,text,text,text,text,jsonb,text,smallint,text,double precision);
DROP TABLE IF EXISTS oracle_arc_private.confirmations;
COMMIT;
