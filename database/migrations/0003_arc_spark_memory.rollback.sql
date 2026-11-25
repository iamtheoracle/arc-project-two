-- Rollback for 0003. Destroys all SPARK memory and share grants. Export first if they must be kept.
BEGIN;
DROP FUNCTION IF EXISTS oracle_arc_private.spark_purge_expired();
DROP FUNCTION IF EXISTS oracle_arc_private.spark_unshare(text,text,text,text);
DROP FUNCTION IF EXISTS oracle_arc_private.spark_share(text,text,text,text);
DROP FUNCTION IF EXISTS oracle_arc_private.spark_forget_all(text,text);
DROP FUNCTION IF EXISTS oracle_arc_private.spark_forget(text,text,uuid);
DROP FUNCTION IF EXISTS oracle_arc_private.spark_correct(text,text,uuid,text);
DROP FUNCTION IF EXISTS oracle_arc_private.spark_list(text,text,integer);
DROP FUNCTION IF EXISTS oracle_arc_private.spark_recall(text,text,text,text[],text,integer,text[]);
DROP FUNCTION IF EXISTS oracle_arc_private.spark_remember(text,text,text,text[],text,text,text,smallint,double precision,text);
DROP FUNCTION IF EXISTS oracle_arc_private.spark_owner(text,text,text,text);
DROP FUNCTION IF EXISTS oracle_arc_private.spark_assert_app(text);
DROP TABLE IF EXISTS oracle_arc_private.spark_share;
DROP TABLE IF EXISTS oracle_arc_private.spark_memory;
COMMIT;
