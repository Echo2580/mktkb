@echo off
title MKTKB Real Q&A Launcher
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Missing project Python: .venv\Scripts\python.exe
  pause
  exit /b 1
)
rem Live Q&A runtime parameters (process-scope only; .env is not modified):
rem   - official deepseek-flash (.env still has the old deepseek-chat alias)
rem   - official peak prices 2/8 CNY per million, context ceiling 1048576, max_tokens 800
rem   - project cap 20 CNY (owner-approved), stage limit 15.5, request cap 600, zero retry
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
set MKTKB_PROJECT_TOTAL_LIMIT_CNY=20.0
set MKTKB_RAG_STAGE_LIMIT_CNY=18.4
set MKTKB_RAG_MAX_REQUESTS=600
set MKTKB_RAG_MAX_REQUEST_CNY=0.5
set MKTKB_RAG_MAX_RETRIES=0
set DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com
set MKTKB_OCR_ENDPOINT=https://ocr.tencentcloudapi.com
set MKTKB_OCR_REGION=ap-guangzhou
set MKTKB_OCR_DISABLED=0
".venv\Scripts\python.exe" -B "tools\start_local.py"
if errorlevel 1 pause
