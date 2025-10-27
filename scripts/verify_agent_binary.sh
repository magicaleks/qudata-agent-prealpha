#!/usr/bin/env bash
# verify_agent_binary.sh — проверка, что PID указывает на ожидаемый бинарник агента
# Использование:
#   ./verify_agent_binary.sh <PID> <expected_binary_abs_path>
# Возврат:
#   0 — OK, процесс исполняет ровно этот бинарник
#   1 — Ошибка использования
#   2 — Процесс не найден
#   3 — Несоответствие бинарника
#   4 — Недоступно для чтения или неизвестная ошибка

set -euo pipefail

if [[ ${1:-} == "" || ${2:-} == "" ]]; then
  echo "usage: $0 <PID> <expected_binary_abs_path>" >&2
  exit 1
fi

PID="$1"
EXPECTED="$2"

if [[ ! -e "$EXPECTED" ]]; then
  echo "expected binary not found: $EXPECTED" >&2
  exit 4
fi

# Проверяем, существует ли процесс
if [[ ! -d "/proc/$PID" ]]; then
  echo "process not found: $PID" >&2
  exit 2
fi

# Фактический путь бинарника процесса
ACTUAL=""
if [[ -L "/proc/$PID/exe" ]]; then
  # shellcheck disable=SC2086
  ACTUAL=$(readlink -f "/proc/$PID/exe" || true)
fi

if [[ -z "$ACTUAL" ]]; then
  echo "cannot resolve process binary path (need root?): /proc/$PID/exe" >&2
  exit 4
fi

# Сначала сравниваем путь 1:1
if [[ "$ACTUAL" == "$EXPECTED" ]]; then
  echo "OK: process $PID runs expected binary $EXPECTED"
  exit 0
fi

# Если пути различаются, дополнительно сравним inode и device (надёжнее при hardlink/overlay)
get_stat() {
  # prints: dev major:minor + inode
  stat -Lc '%D %i' -- "$1"
}

ACT_STAT=$(get_stat "$ACTUAL" 2>/dev/null || true)
EXP_STAT=$(get_stat "$EXPECTED" 2>/dev/null || true)

if [[ -n "$ACT_STAT" && -n "$EXP_STAT" && "$ACT_STAT" == "$EXP_STAT" ]]; then
  echo "OK: process $PID runs expected binary (matched by device+inode): $EXPECTED"
  exit 0
fi

# В качестве финальной проверки — сравнение хеша содержимого файла (дороже, но надёжно)
if command -v sha256sum >/dev/null 2>&1; then
  ACT_HASH=$(sha256sum -- "$ACTUAL" | awk '{print $1}')
  EXP_HASH=$(sha256sum -- "$EXPECTED" | awk '{print $1}')
  if [[ "$ACT_HASH" == "$EXP_HASH" ]]; then
    echo "OK: process $PID runs expected binary (matched by sha256)"
    exit 0
  fi
fi

echo "MISMATCH: process $PID binary is $ACTUAL, expected $EXPECTED" >&2
exit 3


