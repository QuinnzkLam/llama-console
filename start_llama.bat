@echo off
REM === start_llama.bat (single source of truth) ===
REM [UPDATED 2026-09-01] spec: draft-dflash -> draft-mtp (DFlash2 not supported by v0.3.0 loader;
REM   file verified structurally complete: 81/81 tensors, data fits. MTP = verified 08-31 prod config).
REM [UPDATED 2026-09-01d] +--fit off: v0.3.0 fit_params 默认 on, 对 --split-mode tensor
REM   会 abort ("llama_params_fit is not implemented for SPLIT_MODE_TENSOR"). 实测必须
REM   --fit off 才能用 tensor 启动。生产实例即以此方式运行。/health 200。
REM [UPDATED 2026-08-29] v0.1.2-dev -> v0.3.0 (nlama GUI same-source binary + same args)
REM v0.3.0 binary: D:\llama-console\llama.cpp\build\bin\llama-server.exe (built 08-28)
REM Args = nlama GUI cmdline_args.json (Unsloth Qwen3.8-27B thinking-mode recommended)
REM [UPDATED 2026-09-01 搬迁] 启动器统一搬到 D:\llama-console 下, log 落
REM   D:\llama-console\logs\llama_win.log, 不再引用旧 services 目录。
cd /d D:\llama-console
set CUDA_VISIBLE_DEVICES=0,1
D:\llama-console\llama.cpp\build\bin\llama-server.exe -m D:\llama-console\models\Qwen3.8-27B-Q8_0.gguf --mmproj D:\llama-console\models\mmproj-F16.gguf --host 0.0.0.0 --port 18605 -ngl 999 -c 262144 --chat-template-file D:\llama-console\chat_templates\qwen.jinja --temp 1.0 --top-p 0.95 --top-k 20 --min-p 0.0 --presence-penalty 0.0 --repeat-penalty 1.0 --chat-template-kwargs "{\"reasoning_effort\":\"medium\"}" --metrics --split-mode tensor --flash-attn on --parallel 1 --spec-type draft-mtp --cache-type-k q8_0 --cache-type-v q8_0 --cache-ram 0 --no-cache-idle-slots --alias qwen3.8-27b --image-min-tokens 1024 --fit off --log-file D:\llama-console\logs\llama_win.log
