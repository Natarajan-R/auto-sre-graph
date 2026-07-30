#!/bin/bash
# scripts/run_tests.sh
# Test runner for Auto-SRE-Graph

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Auto-SRE-Graph Test Runner${NC}"
echo -e "${GREEN}========================================${NC}"

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Default values
TEST_PATH="${PROJECT_ROOT}/tests"
COVERAGE_THRESHOLD=${COVERAGE_THRESHOLD:-80}
PYTEST_ARGS=""
COVERAGE_ENABLED=true
PARALLEL_ENABLED=false
MARKERS=""

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --unit)
            TEST_PATH="${PROJECT_ROOT}/tests/unit"
            shift
            ;;
        --integration)
            TEST_PATH="${PROJECT_ROOT}/tests/integration"
            shift
            ;;
        --coverage)
            COVERAGE_ENABLED=true
            shift
            ;;
        --no-coverage)
            COVERAGE_ENABLED=false
            shift
            ;;
        --parallel)
            PARALLEL_ENABLED=true
            shift
            ;;
        --markers)
            MARKERS="$2"
            shift 2
            ;;
        --threshold)
            COVERAGE_THRESHOLD="$2"
            shift 2
            ;;
        --verbose)
            PYTEST_ARGS="$PYTEST_ARGS -v"
            shift
            ;;
        --help|-h)
            echo -e "${BLUE}Usage:${NC}"
            echo "  ./run_tests.sh [options]"
            echo ""
            echo -e "${BLUE}Options:${NC}"
            echo "  --unit           Run only unit tests"
            echo "  --integration    Run only integration tests"
            echo "  --coverage       Enable coverage report (default)"
            echo "  --no-coverage    Disable coverage report"
            echo "  --parallel       Run tests in parallel"
            echo "  --markers M      Run tests with specific markers (comma-separated)"
            echo "  --threshold N    Coverage threshold (default: 80)"
            echo "  --verbose        Verbose output"
            echo "  --help, -h       Show this help message"
            exit 0
            ;;
        *)
            PYTEST_ARGS="$PYTEST_ARGS $1"
            shift
            ;;
    esac
done

echo -e "${YELLOW}Configuration:${NC}"
echo "  Test path: $TEST_PATH"
echo "  Coverage enabled: $COVERAGE_ENABLED"
echo "  Parallel enabled: $PARALLEL_ENABLED"
echo "  Coverage threshold: $COVERAGE_THRESHOLD%"
echo "  Markers: ${MARKERS:-all}"
echo ""

# Activate virtual environment if it exists
if [ -d "${PROJECT_ROOT}/venv" ]; then
    echo -e "${YELLOW}Activating virtual environment...${NC}"
    source "${PROJECT_ROOT}/venv/bin/activate"
elif [ -d "${PROJECT_ROOT}/.venv" ]; then
    echo -e "${YELLOW}Activating virtual environment...${NC}"
    source "${PROJECT_ROOT}/.venv/bin/activate"
fi

# Check if pytest is installed
if ! command -v pytest &> /dev/null; then
    echo -e "${RED}Error: pytest not found. Please install test dependencies:${NC}"
    echo "  pip install -r requirements/dev.txt"
    exit 1
fi

# Build pytest command
PYTEST_CMD="pytest $TEST_PATH $PYTEST_ARGS"

# Add coverage if enabled
if [ "$COVERAGE_ENABLED" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --cov=src --cov-report=term --cov-report=html:htmlcov"
    PYTEST_CMD="$PYTEST_CMD --cov-report=xml:coverage.xml"
    PYTEST_CMD="$PYTEST_CMD --cov-fail-under=$COVERAGE_THRESHOLD"
fi

# Add markers if specified
if [ -n "$MARKERS" ]; then
    PYTEST_CMD="$PYTEST_CMD -m $MARKERS"
fi

# Add parallel if enabled
if [ "$PARALLEL_ENABLED" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -n auto"
fi

# Add additional options
PYTEST_CMD="$PYTEST_CMD --strict-markers"

echo -e "${YELLOW}Running tests...${NC}"
echo -e "${BLUE}Command: $PYTEST_CMD${NC}"
echo ""

# Run tests
set +e
eval $PYTEST_CMD
TEST_EXIT_CODE=$?
set -e

# Check test results
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo ""
    echo -e "${GREEN}========================================${NC}"
    echo -e "${GREEN}✓ All tests passed!${NC}"
    echo -e "${GREEN}========================================${NC}"
else
    echo ""
    echo -e "${RED}========================================${NC}"
    echo -e "${RED}✗ Tests failed with exit code: $TEST_EXIT_CODE${NC}"
    echo -e "${RED}========================================${NC}"
    exit $TEST_EXIT_CODE
fi

# Generate coverage report if enabled
if [ "$COVERAGE_ENABLED" = true ] && [ -f "${PROJECT_ROOT}/coverage.xml" ]; then
    echo ""
    echo -e "${YELLOW}Coverage report generated:${NC}"
    echo "  HTML: ${PROJECT_ROOT}/htmlcov/index.html"
    echo "  XML: ${PROJECT_ROOT}/coverage.xml"
    
    # Check coverage threshold
    COVERAGE=$(grep -o 'line-rate="[0-9.]*"' "${PROJECT_ROOT}/coverage.xml" | head -1 | sed 's/line-rate="//' | sed 's/"//')
    if [ -n "$COVERAGE" ]; then
        COVERAGE_PCT=$(echo "$COVERAGE * 100" | bc | cut -d. -f1)
        echo -e "  Coverage: ${COVERAGE_PCT}%"
        
        if [ "$COVERAGE_PCT" -lt "$COVERAGE_THRESHOLD" ]; then
            echo -e "${RED}  Warning: Coverage below threshold ($COVERAGE_THRESHOLD%)${NC}"
        else
            echo -e "${GREEN}  ✓ Coverage meets threshold ($COVERAGE_THRESHOLD%)${NC}"
        fi
    fi
fi

# Run linting if requested
if [ "$RUN_LINT" = true ]; then
    echo ""
    echo -e "${YELLOW}Running linters...${NC}"
    
    # Run ruff
    if command -v ruff &> /dev/null; then
        echo -e "${BLUE}Running ruff...${NC}"
        ruff check "${PROJECT_ROOT}/src" "${PROJECT_ROOT}/tests"
    else
        echo -e "${YELLOW}ruff not installed, skipping...${NC}"
    fi
    
    # Run black
    if command -v black &> /dev/null; then
        echo -e "${BLUE}Running black...${NC}"
        black --check "${PROJECT_ROOT}/src" "${PROJECT_ROOT}/tests" 2>/dev/null || true
    else
        echo -e "${YELLOW}black not installed, skipping...${NC}"
    fi
    
    # Run mypy
    if command -v mypy &> /dev/null; then
        echo -e "${BLUE}Running mypy...${NC}"
        mypy "${PROJECT_ROOT}/src" --ignore-missing-imports 2>/dev/null || true
    else
        echo -e "${YELLOW}mypy not installed, skipping...${NC}"
    fi
fi

echo ""
echo -e "${GREEN}Test run completed successfully!${NC}"
echo ""

# Show useful commands
echo -e "${YELLOW}Useful commands:${NC}"
echo "  Open coverage report: open htmlcov/index.html"
echo "  Run specific test: pytest tests/unit/test_schemas.py"
echo "  Run with specific marker: pytest -m unit"
echo "  Run with more verbosity: pytest -v"
echo ""