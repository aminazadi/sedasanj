#!/bin/sh
set -eu

psql_args="--username ${POSTGRES_USER} --dbname ${POSTGRES_DB} --no-psqlrc --tuples-only --no-align"

test "$(psql ${psql_args} --command "SELECT count(*) = 2 FROM pg_available_extensions WHERE name IN ('vector', 'age')")" = "t"
test "$(psql ${psql_args} --command "SELECT 'age' = ANY (regexp_split_to_array(current_setting('shared_preload_libraries'), '\\s*,\\s*'))")" = "t"
test "$(psql ${psql_args} --command "SELECT count(*) = 2 FROM pg_extension WHERE extname IN ('vector', 'age')")" = "t"
test "$(psql ${psql_args} --command "SELECT count(*) = 1 FROM ag_catalog.ag_graph WHERE name = 'tenant_graph'")" = "t"
test "$(psql ${psql_args} --command "SELECT count(*) = 1 FROM ag_catalog.cypher('tenant_graph', \$\$RETURN 1\$\$) AS (result ag_catalog.agtype)")" = "t"
