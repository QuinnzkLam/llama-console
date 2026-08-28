### CHECKLIST锛堝煼琛岄爢搴忥級

**Phase 0 鈥?棰勬锛坮ead-only锛寏10 min锛?* 鉁?15:45 瀹屾垚
- [x] 0.1 纾佺洏锛欳: free 782.7GB / D: free 822.7GB 鉁?- [x] 0.2 choco 2.6.0 鉁?- [x] 0.3 D:\llama-console\llama.cpp 瀛樺湪浣嗕负绌虹洰褰曪紙瀹夊叏锛宑lone 鐩爣锛夛紱backup cmdline_args.json 鈫?cmdline_args.json.bak_20260827_153646 鉁?- [x] 0.4 v1 PID 13596 alive + frpc PID 7392 alive 鉁?- [x] 0.5 baseline锛歝make/ninja/cl.exe 鍏?ABSENT锛汣UDA 12.5 鍦?/ 13.2 涓嶅湪锛汫itHub 鐩磋繛鍙揪锛圚EAD d7a2074锛?- [x] 0.6 CUDA 13.2 URL 鏍稿疄锛歞eveloper.download.nvidia.com/compute/cuda/13.2.0/local_installers/cuda_13.2.0_windows.exe锛?00 OK, 2.48GB锛沶etwork 鐗?404锛?- [x] 0.7 checklist 涓婃満 D:\llama-console\BUILD-CHECKLIST.md

**Phase 1 鈥?宸ュ叿閺堝畨瑁濓紙鏍稿綀姗燂紝~30-60 min锛屽彲涓柗绾屽仛锛?*
- [x] 1.1 cmake 4.4.3 鉁咃紙choco 鍏ㄥ 鈫?iMac 涓嬪畼鏂?zip 鈫?C:\tools\cmake锛?-version 椹楄瓑閫氶亷锛?- [x] 1.2 ninja 1.11.1 鉁咃紙鍚屾硶 鈫?C:\tools\ninja锛?-version 椹楄瓑閫氶亷锛?- [x] 1.3 VS2022 BuildTools VCTools 鉁咃紙RDP UAC oneclick_install.bat 璺戝畬锛宭og D:\llama-console\oneclick_install.log 鏈 "vs install exitcode=3010" + "ALL-FINISHED" 17:45锛汣:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools VCTools PRESENT锛?- [x] 1.4 CUDA 13.2 installer 钀戒綅 鉁咃紙D:\llama-console\cuda_13.2.0_windows.exe锛?.31GB锛?8:01锛?- [x] 1.5 闈滈煶瀹夎瀹屾垚 鉁咃紙cuda install exitcode=0锛宱neclick_install.log 17:45锛?- [x] 1.6 椹楄瓑 鉁咃細`C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v13.2\bin\nvcc.exe --version` 鈫?release 13.2 V13.2.51锛孊uild cuda_13.2.r13.2/compiler.37434383_0锛沜l.exe 鍙伒娓紙VS dev shell锛?- [x] 1.7 鏇存柊 BUILD-CHECKLIST.md 鐙€鎱?鉁咃紙21:39锛?
**Phase 2 鈥?婧愮⒓ + 绶ㄨ锛堟牳褰堟锛寏20-40 min锛?*
- [x] 2.1 婧愮⒓鍏?D:\llama-console\llama.cpp 鉁咃紙鏍稿綀姗熺洿閫?GitHub 琚?reset 鈫?iMac 涓?v0.3.0 zip 38.6MB 鈫?scp 鈫?瑙ｅ锛孋MakeLists.txt 纰鸿獚鍦ㄤ綅锛?- [x] 2.2 cmake configure 鉁咃紙Ninja generator锛沺2_configure.log 18:01:56 exitcode=0锛?- Found CUDAToolkit: C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA/v13.2/include ... found version "13.2.51"锛?- The CUDA compiler identification is NVIDIA 13.2.51 with host compiler MSVC 19.44.35228.0锛?- Using CMAKE_CUDA_ARCHITECTURES=86锛?- [x] 2.3 妾㈡煡榛?鉁咃細configure 鐩存帴瑾?CUDA 13.2.51锛?*鐒￠渶 fallback 12.5**锛沢gml version: 0.22.0锛汵CCL warning 鍞斿奖闊垮柈閫茬▼ server
- [x] 2.4 ninja 绶ㄨ 鉁咃紙469/469锛宲3_build.log 18:07:38 exitcode=0锛宭og 灏?"build OK" / "P3-BUILD-OK"锛沴og 鍏ラ潰鍞竴 error = UI dist.tar.gz 涓嬭級 timeout锛屽敂褰遍熆 server 浜岄€插埗鐢㈢墿锛?- [x] 2.5 鐢㈢墿椹楄瓑 鉁咃細**鈿狅笍 璺緫淇锛歂inja generator 杓稿嚭鍠?`D:\llama-console\llama.cpp\build\bin\`锛堝敂淇?checklist 鍘熸湰瀵槄 `build\bin\Release\`锛?*銆傜敘鐗╋細llama-server.exe (10,752 bytes) + ggml-cuda.dll (50,912,768 bytes / 48.6 MB) + ggml-base/cpu.dll/llama.dll/llama-common.dll/llama-server-impl.dll/mtmd.dll銆俙--version` 杓稿嚭锛歚version: 0.3.0-dev (build 0, commit unknown)` / `built with MSVC 19.44.35228.0 for Windows AMD64`锛坈ommit unknown 姝ｅ父锛寁0.3.0 zip 婧愬唶 .git锛?- [x] 2.6 鏇存柊 BUILD-CHECKLIST.md 鐙€鎱?鉁咃紙21:39锛?
**Phase 3 鈥?v2 鎺ラ锛堜唬纰兼敼 1 琛?+ 鍠枃浠堕儴缃诧級**
- [x] 3.1 local repo: draft/src/llama_console_v2/backend/llama_cpp.py L34 DONE (V2_BIN_DIR -> D:/llama-console/llama.cpp/build/bin)
- [x] 3.3 smoke: get_llama_server_exe returns new path + MZ header PASS
- [x] 3.4 local git commit DONE (commit fc1190b: feat llama-console v2 v2-bridge CUDA 13.2 compiled llama-server v0.3.0)
**Phase 4 鈥?鍒囨祦 + 椹楄瓑锛堚殸锔?闂滈嵉锛屾秹鍙?v1 閫茬▼锛?*
- [x] 4.1 new exe cold-start smoke DONE (port 18606 PID 23712 loaded Q8_0, /completion The capital of France is -> Paris... real inference)
- [x] 4.3 v2 GUI start DONE (PID 25144 alive 11+min, bind 0.0.0.0:18605, VRAM GPU0 22.7G GPU1 22.0G, /health 200, /v1/chat 2+2? -> content=4 finish=stop; chat template fix commit 1281ef7 +10 lines V2_CHAT_TEMPLATE_FILE + start() guard; manually launched via Start-Process -PassThru to avoid v2 source Popen CREATE_NO_WINDOW non-detach bug)
- [x] 4.4 FRP 28607 tunnel: Worker fix in flight (frpc PID 7792 alive but proxy Empty reply; add health-check + tcpKeepAlive in progress)
- [x] 4.5 rollback plan ready (D:\services\llama-server\llama-server.exe v0.1.2-dev + cmdline_args.json.bak_20260827_153646 preserved)

**Phase E 鈥?llama-cpp-python锛堚潓 SKIP 鈥?Quinn 2026-08-27 17:28 纰鸿獚鍞斾娇鍋氾細v2 闆?import锛岀磾 Popen llama-server.exe锛?*
- [ ] E.0 绲愯珫锛歷2 闆朵緷璩达紝灏嶅暉鍕曞櫒鐒″姛鑳藉鐩?- [skip] E.1 锛堣嫢鍋氾級鍚屽伐鍏烽張绶細`CMAKE_ARGS="-DGGML_CUDA=ON -DCMAKE_CUDA_ARCHITECTURES=86" python -m pip install llama-cpp-python --force-reinstall --no-build-isolation`锛堟牳褰堟 venv锛寏15-25 min锛?- [ ] E.2 椹楄瓑 import + CUDA 鍟熺敤

> 21:39 鐝惧牬椹楄瓑锛歅hase 0-2 鍏ㄩ儴瀹屾垚锛圵orker 瀵︽脯锛?

> 23:59 Phase 3 + Phase 4 all DONE (Franky cleanup); FRP 4.4 Worker fix in progress
