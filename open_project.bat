@echo off

set RPI_IP_ADDR=192.168.50.212
set RPI_SSH_PORT=22

icacls %~dp0/project/ssh_id /inheritance:r
icacls %~dp0/project/ssh_id /grant:r "%USERNAME%":"(R)"

code %~dp0/project
