#!/bin/bash
# 旧的 Linux/一体化写法（mac 请用 ./start_all_mac.sh，它带 stop/status/logs）。
#
# 服务端已迁移到 TypeScript：跑之前要先编译，三个进程跑的是 dist/ 里的 js。
#   cd server && yarn install --frozen-lockfile && yarn build
# 入口与配置的相对关系没变：入口在 dist/<进程>/，所以 ../configs_mac.js 指向 dist/configs_mac.js。
nohup node ./dist/account_server/app.js ../configs_mac.js &
nohup node ./dist/hall_server/app.js ../configs_mac.js &
nohup node ./dist/game_server/app.js ../configs_mac.js &
