# Beyonder launcher for Windows.
# Usage:
#   .\run.ps1 up        # docker compose up postgres + qdrant
#   .\run.ps1 migrate   # run alembic
#   .\run.ps1 backend   # start FastAPI (uvicorn) on host (Python venv)
#   .\run.ps1 frontend  # start Next.js in Docker (host never touches npm)
#   .\run.ps1 smoke     # end-to-end Gemini sanity check
#   .\run.ps1 test      # run pytest
#   .\run.ps1 eval      # run full eval and refresh dashboard JSON
#   .\run.ps1 down      # stop infra

param(
    [Parameter(Position=0)]
    [ValidateSet("up", "migrate", "backend", "api", "frontend", "frontend-build", "smoke", "test", "eval", "down", "doctor")]
    [string]$Cmd = "doctor"
)

$ErrorActionPreference = "Stop"
$REPO = Split-Path -Parent $MyInvocation.MyCommand.Path

function Activate-Venv {
    $venv = Join-Path $REPO "backend\.venv"
    if (-not (Test-Path $venv)) {
        Write-Host "Creating Python venv..." -ForegroundColor Yellow
        & python -m venv $venv
    }
    $activate = Join-Path $venv "Scripts\Activate.ps1"
    & $activate
    Write-Host "Installing Python deps..." -ForegroundColor Yellow
    & python -m pip install --upgrade pip --disable-pip-version-check 2>&1 | Out-Null
    & python -m pip install --disable-pip-version-check -r (Join-Path $REPO "backend\requirements.txt") -r (Join-Path $REPO "backend\requirements-dev.txt")
}

function Ensure-Env {
    $envPath = Join-Path $REPO ".env"
    if (-not (Test-Path $envPath)) {
        Write-Host ".env missing — copying from .env.example" -ForegroundColor Yellow
        Copy-Item (Join-Path $REPO ".env.example") $envPath
        Write-Host "Edit .env to set GEMINI_API_KEY before running smoke/eval." -ForegroundColor Yellow
    }
}

switch ($Cmd) {
    "up" {
        Ensure-Env
        & docker compose -f (Join-Path $REPO "docker-compose.yml") up -d postgres qdrant
    }
    "migrate" {
        Activate-Venv
        Set-Location (Join-Path $REPO "backend")
        & alembic upgrade head
    }
    "backend" {
        Ensure-Env
        Activate-Venv
        Set-Location (Join-Path $REPO "backend")
        Write-Host "Backend on http://localhost:8000" -ForegroundColor Green
        & uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
    }
    "api" {
        Ensure-Env
        & docker compose -f (Join-Path $REPO "docker-compose.yml") up -d postgres qdrant
        & docker compose -f (Join-Path $REPO "docker-compose.yml") --profile api up --build api
    }
    "frontend" {
        Ensure-Env
        & docker compose -f (Join-Path $REPO "docker-compose.yml") --profile frontend up frontend-dev
    }
    "frontend-build" {
        Ensure-Env
        & docker compose -f (Join-Path $REPO "docker-compose.yml") --profile build run --rm frontend-build
        Write-Host "Static export written to frontend/out/" -ForegroundColor Green
    }
    "smoke" {
        Ensure-Env
        Activate-Venv
        Set-Location (Join-Path $REPO "backend")
        & python -m scripts.smoke
    }
    "test" {
        Activate-Venv
        Set-Location (Join-Path $REPO "backend")
        & pytest -q
    }
    "eval" {
        Ensure-Env
        Activate-Venv
        Set-Location (Join-Path $REPO "backend")
        & python -m eval.run all
    }
    "down" {
        & docker compose -f (Join-Path $REPO "docker-compose.yml") down
    }
    "doctor" {
        Write-Host "Beyonder doctor" -ForegroundColor Cyan
        Write-Host "----------------"
        Write-Host "Repo: $REPO"
        $py = Get-Command python -ErrorAction SilentlyContinue
        if ($py) { Write-Host ("python: " + (& python --version 2>&1)) -ForegroundColor Green }
        else { Write-Host "python: MISSING (install 3.11+)" -ForegroundColor Red }

        $docker = Get-Command docker -ErrorAction SilentlyContinue
        if ($docker) { Write-Host ("docker: " + (& docker --version)) -ForegroundColor Green }
        else { Write-Host "docker: MISSING" -ForegroundColor Red }

        $node = Get-Command node -ErrorAction SilentlyContinue
        if ($node) {
            Write-Host ("node: " + (& node --version) + " (NOT used by Beyonder — Docker only)") -ForegroundColor Yellow
        } else {
            Write-Host "node: not on host (correct — Beyonder runs npm only inside Docker)" -ForegroundColor Green
        }

        $envPath = Join-Path $REPO ".env"
        if (Test-Path $envPath) {
            $hasKey = (Get-Content $envPath | Select-String "^GEMINI_API_KEY=.+").Count -gt 0
            if ($hasKey) { Write-Host ".env: has GEMINI_API_KEY" -ForegroundColor Green }
            else { Write-Host ".env: present but GEMINI_API_KEY blank" -ForegroundColor Yellow }
        } else {
            Write-Host ".env: missing — copy .env.example to .env" -ForegroundColor Yellow
        }

        Write-Host ""
        Write-Host "Next: .\run.ps1 up   # start postgres + qdrant"
    }
}
