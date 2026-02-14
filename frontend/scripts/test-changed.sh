#!/bin/bash
# Run tests only for frontend files that have changed relative to main (or staged files).
#
# Usage:
#   ./scripts/test-changed.sh            # changed vs main
#   ./scripts/test-changed.sh --staged   # staged files only

set -e

cd "$(dirname "$0")/.."

MODE="diff"
if [[ "$1" == "--staged" ]]; then
    MODE="staged"
    shift
fi

# Get list of changed TS/TSX files
if [[ "$MODE" == "staged" ]]; then
    CHANGED=$(git diff --cached --name-only --diff-filter=ACMR -- '*.ts' '*.tsx' | grep '^frontend/src/' | sed 's|^frontend/||' || true)
else
    CHANGED=$(git diff --name-only main...HEAD -- '*.ts' '*.tsx' 2>/dev/null | grep '^frontend/src/' | sed 's|^frontend/||' || true)
    # Also include uncommitted changes
    UNCOMMITTED=$(git diff --name-only -- '*.ts' '*.tsx' | grep '^frontend/src/' | sed 's|^frontend/||' || true)
    UNTRACKED=$(git ls-files --others --exclude-standard -- '*.ts' '*.tsx' | grep '^frontend/src/' | sed 's|^frontend/||' || true)
    CHANGED=$(printf "%s\n%s\n%s" "$CHANGED" "$UNCOMMITTED" "$UNTRACKED" | sort -u)
fi

if [[ -z "$CHANGED" ]]; then
    echo "No changed TypeScript files detected."
    exit 0
fi

# If shared test infrastructure changed, run all tests
if echo "$CHANGED" | grep -qE '(src/__tests__/setup\.ts|src/__tests__/helpers/|src/__tests__/factories/)'; then
    echo "Shared test infrastructure changed — running all tests."
    pnpm test:run "$@"
    exit $?
fi

# If shared lib/hooks/api/types changed, run all tests
if echo "$CHANGED" | grep -qE '(src/lib/|src/types/|src/api/)'; then
    echo "Shared library code changed — running all tests."
    pnpm test:run "$@"
    exit $?
fi

# Collect matching test files
TEST_FILES=""

while IFS= read -r file; do
    [[ -z "$file" ]] && continue

    # If the file is already a test file, include it directly
    if [[ "$file" == *.test.ts || "$file" == *.test.tsx ]]; then
        if [[ -f "$file" ]]; then
            TEST_FILES="$TEST_FILES $file"
        fi
        continue
    fi

    # Look for sibling .test.ts or .test.tsx files
    dir=$(dirname "$file")
    base=$(basename "$file")
    # Strip .ts or .tsx extension
    base_no_ext="${base%.tsx}"
    base_no_ext="${base_no_ext%.ts}"

    for ext in test.ts test.tsx; do
        test_file="${dir}/${base_no_ext}.${ext}"
        if [[ -f "$test_file" ]]; then
            TEST_FILES="$TEST_FILES $test_file"
            break
        fi
    done
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

pnpm vitest run $TEST_FILES "$@"
