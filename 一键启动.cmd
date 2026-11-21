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
rem 真实问答运行参数（只影响本进程；不修改 .env）
rem   - 官方 deepseek-flash（.env 里仍是旧 deepseek-chat 别名，这里显式覆盖）
rem   - 官方峰值价格 2/8 元每百万 token；上下文上限 1048576；max_tokens 800
rem   - 阶段 S2-OWNER-ACCEPTANCE：项目上限 100、阶段上限 10、300 次请求（计划 288 次）、单请求上界 2.103552
rem   - 说明：真实模式需要一份**有效且未用尽**的亲验 GO（docs/evidence/.../PM/S2-OWNER-ACCEPTANCE-GO.json）
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
set MKTKB_PROJECT_TOTAL_LIMIT_CNY=100.0
set MKTKB_LIVE_STAGE=S2-OWNER-ACCEPTANCE
set MKTKB_RAG_STAGE_LIMIT_CNY=10.0
set MKTKB_RAG_MAX_REQUESTS=300
set MKTKB_RAG_MAX_REQUEST_CNY=2.103552
set MKTKB_RAG_MAX_RETRIES=0
set DASHSCOPE_BASE_URL=https://dashscope.aliyuncs.com
set MKTKB_OCR_ENDPOINT=https://ocr.tencentcloudapi.com
set MKTKB_OCR_REGION=ap-guangzhou
set MKTKB_OCR_DISABLED=0

".venv\Scripts\python.exe" -B "tools\start_local.py" --owner-live
if not errorlevel 1 goto :done

echo.
echo ============================================================================
echo [一键启动] 真实模式未能启动。最常见原因：亲验 GO 的请求窗口已用完或已过期
echo            （上方会打印具体原因，例如“亲验请求窗口已用完”）。
echo [一键启动] 现在改为「离线模式」启动：可登录、上传、发布、检索浏览；
echo            但问答不调用真实模型（会显式提示未配置模型，不会伪造答案）。
echo [一键启动] 要恢复真实问答：重新签发亲验 GO 后，再双击本脚本即可。
echo ============================================================================
echo.
".venv\Scripts\python.exe" -B "tools\start_local.py" --offline
if errorlevel 1 pause
goto :eof

:done
if errorlevel 1 pause
