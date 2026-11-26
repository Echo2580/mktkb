@echo off
title MKTKB Local Launcher
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing project Python: .venv\Scripts\python.exe
  pause
  exit /b 1
)
rem ============================================================================
rem Live configuration: DeepSeek + DashScope + Tencent OCR.
rem Shared stage limit: 110.7909466 CNY (history + 100 CNY for this 30-day window).
rem Request plan: chat 800, embedding 600, rerank 180, OCR text 11, OCR table 2.
rem Keep the plan identical to S2-OWNER-ACCEPTANCE-GO.json; never reset the ledger.
rem Real startup must fail visibly; do not silently fall back to offline mode.
rem ============================================================================
set PYTHONUTF8=1
set PYTHONDONTWRITEBYTECODE=1
set OPENBLAS_NUM_THREADS=1
set MKTKB_RAG_PROVIDER_MODE=live
set MKTKB_MODEL_NAME=deepseek-flash
set MKTKB_MODEL_INPUT_PRICE_PER_MILLION_CNY=2.0
set MKTKB_MODEL_OUTPUT_PRICE_PER_MILLION_CNY=8.0
set MKTKB_MODEL_MAX_INPUT_TOKENS=6144
set MKTKB_MODEL_MAX_OUTPUT_TOKENS=800
set MKTKB_MODEL_CONTEXT_CEILING_TOKENS=1048576
set MKTKB_MODEL_RESERVE_PROFILE=model_context_ceiling
set MKTKB_PROJECT_TOTAL_LIMIT_CNY=1000.0
set MKTKB_TRACE_ENABLED=1
set MKTKB_LIVE_STAGE=S2-OWNER-ACCEPTANCE
set MKTKB_RAG_STAGE_LIMIT_CNY=110.7909466
set MKTKB_RAG_MAX_REQUESTS=1600
set MKTKB_RAG_MAX_REQUEST_CNY=2.103552
set MKTKB_RAG_MAX_RETRIES=0
set MKTKB_UA_PLAN_CHAT=800
set MKTKB_UA_PLAN_EMBEDDING=600
set MKTKB_UA_PLAN_RERANK=180
set MKTKB_UA_PLAN_OCR_TEXT=11
set MKTKB_UA_PLAN_OCR_TABLE=2
set DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com
set MKTKB_OCR_ENDPOINT=https://ocr.tencentcloudapi.com
set MKTKB_OCR_REGION=ap-guangzhou
set MKTKB_OCR_DISABLED=0

rem If the verified live instance is already healthy, reuse it instead of starting again.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$c=Get-NetTCPConnection -LocalPort 8077 -State Listen -ErrorAction SilentlyContinue; if ($c) { $p=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $c.OwningProcess); if ($p.CommandLine -like '*start_local.py*--owner-live*') { try { $h=Invoke-RestMethod -Uri 'http://127.0.0.1:8077/api/v1/healthz' -TimeoutSec 3; $f=Invoke-WebRequest -Uri 'http://127.0.0.1:5673' -UseBasicParsing -TimeoutSec 3; if ($h.status -eq 'ok' -and $f.StatusCode -eq 200) { exit 0 } } catch {} } }; exit 1"
if not errorlevel 1 (
  echo The live instance is already running. Opening http://127.0.0.1:5673
  start "" "http://127.0.0.1:5673"
  exit /b 0
)

".venv\Scripts\python.exe" -B "tools\start_local.py" --owner-live
if not errorlevel 1 goto :done

echo.
echo ============================================================================
echo Live startup failed. Offline fallback is disabled.
echo Read the error above. Check the GO window, budget, ports and existing processes.
echo ============================================================================
pause
exit /b 1

:done
if errorlevel 1 pause
