#!/usr/bin/env bash
# Concurrency test: N parallel sessions race to consume ONE challenge; exactly one may succeed.
# Usage: PSQL="psql -h HOST -p PORT -U USER -d DB" ./0004_arc_confirmations_concurrency.sh  (needs 0001+0004 applied, superuser)
set -u
PSQL=${PSQL:?set PSQL}; N=${N:-12}; H=$(printf 'a%.0s' $(seq 1 64))
$PSQL -q -v ON_ERROR_STOP=1 <<SQL
INSERT INTO oracle_arc_private.applications (app_id, salt, secret_hash)
VALUES ('conc', decode(repeat('01',16),'hex'), decode(repeat('02',32),'hex')) ON CONFLICT DO NOTHING;
SQL
$PSQL -q -c "SET ROLE oracle_arc_runtime; SELECT oracle_arc_private.confirmation_create('conc','u1','race-challenge-0001','a','t','{}','s',2::smallint,'$H',300)" >/dev/null || { echo "setup failed"; exit 1; }
OUT=$(mktemp -d)
for i in $(seq 1 "$N"); do
  ( $PSQL -q -A -t -c "SET ROLE oracle_arc_runtime; SELECT 'OK' FROM oracle_arc_private.confirmation_consume('conc','u1','race-challenge-0001','$H',true)" >"$OUT/$i.out" 2>"$OUT/$i.err" ) &
done
wait
ok=$(grep -l '^OK' "$OUT"/*.out 2>/dev/null | wc -l)
used=$(grep -l 'already used' "$OUT"/*.err 2>/dev/null | wc -l)
$PSQL -q -c "DELETE FROM oracle_arc_private.applications WHERE app_id='conc'" >/dev/null
rm -rf "$OUT"
echo "sessions=$N succeeded=$ok already_used=$used"
[ "$ok" -eq 1 ] && [ "$used" -eq $((N-1)) ] && echo "confirmation concurrency test passed" || { echo "FAILED"; exit 1; }
