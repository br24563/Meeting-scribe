#!/bin/bash
cd "$(dirname "$0")"

echo "============================================"
echo "  EchoPad - Starting up..."
echo "============================================"
echo

if ! command -v docker &> /dev/null; then
    echo "Docker Desktop was not found on this computer."
    echo "Please install it from https://www.docker.com/products/docker-desktop/"
    echo "then double-click this file again."
    echo
    read -p "Press Enter to close..."
    exit 1
fi

docker compose up -d --build
if [ $? -ne 0 ]; then
    echo
    echo "Something went wrong starting EchoPad."
    echo "Make sure Docker Desktop is open and running, then try again."
    echo
    read -p "Press Enter to close..."
    exit 1
fi

echo
echo "Waiting for EchoPad to finish setting up..."
echo "(First run downloads the AI model - this can take a few minutes."
echo " Later runs will be much faster.)"
echo

until curl -s -o /dev/null -w "%{http_code}" http://localhost:8501 2>/dev/null | grep -q "200"; do
    sleep 3
done

echo "EchoPad is ready! Opening in your browser..."
open http://localhost:8501 2>/dev/null || xdg-open http://localhost:8501 2>/dev/null

echo
echo "You can close this window, or leave it open to watch EchoPad's logs."
echo "To stop EchoPad later, run \"docker compose down\" from this folder."
read -p "Press Enter to close this window..."
