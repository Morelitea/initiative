#!/bin/bash
# Run tests only for files that have changed relative to main (or staged files).
#
# Usage:
#   ./scripts/test-changed.sh            # changed vs main
#   ./scripts/test-changed.sh --staged   # staged files only

set -e

cd "$(dirname "$0")/.."

MODE="diff"
if [[ "$1" == "--staged" ]]; then
    MODE="staged"
fi

# Get list of changed Python files
if [[ "$MODE" == "staged" ]]; then
    CHANGED=$(git diff --cached --name-only --diff-filter=ACMR -- '*.py' | grep '^backend/' | sed 's|^backend/||' || true)
else
    CHANGED=$(git diff --name-only main...HEAD -- '*.py' 2>/dev/null | grep '^backend/' | sed 's|^backend/||' || true)
    # Also include uncommitted changes
    UNCOMMITTED=$(git diff --name-only -- '*.py' | grep '^backend/' | sed 's|^backend/||' || true)
    UNTRACKED=$(git ls-files --others --exclude-standard -- '*.py' | grep '^backend/' | sed 's|^backend/||' || true)
    CHANGED=$(printf "%s\n%s\n%s" "$CHANGED" "$UNCOMMITTED" "$UNTRACKED" | sort -u)
fi

if [[ -z "$CHANGED" ]]; then
    echo "No changed Python files detected."
    exit 0
fi

# If shared infrastructure changed, run all tests
if echo "$CHANGED" | grep -qE '(app/testing/|app/models/|app/core/|app/db/|conftest\.py)'; then
    echo "Shared infrastructure changed — running all tests."
    python -m pytest app/
    exit $?
fi

# Collect matching test files
TEST_FILES=""

while IFS= read -r file; do
    [[ -z "$file" ]] && continue

    # If the file is already a test file, include it directly
    if [[ "$file" == *_test.py ]]; then
        if [[ -f "$file" ]]; then
            TEST_FILES="$TEST_FILES $file"
        fi
        continue
    fi

    # Look for a sibling _test.py file
    dir=$(dirname "$file")
    base=$(basename "$file" .py)
    test_file="${dir}/${base}_test.py"

    if [[ -f "$test_file" ]]; then
        TEST_FILES="$TEST_FILES $test_file"
    fi
done <<< "$CHANGED"

# Deduplicate
TEST_FILES=$(echo "$TEST_FILES" | tr ' ' '\n' | sort -u | tr '\n' ' ')

if [[ -z "${TEST_FILES// /}" ]]; then
    echo "No matching test files found for changed files."
    echo "Changed files:"
    echo "$CHANGED" | sed 's/^/  /'
    exit 0
fi

echo "Running tests for changed files:"
echo "$TEST_FILES" | tr ' ' '\n' | sed '/^$/d' | sed 's/^/  /'
echo ""

python -m pytest $TEST_FILES "$@"
