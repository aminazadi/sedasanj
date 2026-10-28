#!/bin/sh
set -eu

aof_dir=/data/appendonlydir
manifest="$aof_dir/appendonly.aof.manifest"

if [ ! -f "$manifest" ]; then
    exit 0
fi

if redis-check-aof "$manifest"; then
    exit 0
fi

backup_root=/data/aof-repair-backups
backup_dir="$backup_root/$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
cp -a "$aof_dir/." "$backup_dir/"

printf 'y\n' | redis-check-aof --fix "$manifest"
redis-check-aof "$manifest"
