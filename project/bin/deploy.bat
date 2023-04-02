cd %~dp0/..

ssh.exe -i ssh_id -p %RPI_SSH_PORT% root@%RPI_IP_ADDR%       killall gdbserver
ssh.exe -i ssh_id -p %RPI_SSH_PORT% root@%RPI_IP_ADDR%       mkdir -p /usr/share/StudentContest

scp.exe -i ssh_id -P %RPI_SSH_PORT% build_dir/StudentContest root@%RPI_IP_ADDR%:/usr/bin/
scp.exe -i ssh_id -P %RPI_SSH_PORT% bin/run_gdb_server.sh    root@%RPI_IP_ADDR%:/usr/bin/
scp.exe -i ssh_id -P %RPI_SSH_PORT% src/python/*.py          root@%RPI_IP_ADDR%:/usr/share/StudentContest

ssh.exe -i ssh_id -p %RPI_SSH_PORT% root@%RPI_IP_ADDR%       chmod +x /usr/bin/StudentContest
ssh.exe -i ssh_id -p %RPI_SSH_PORT% root@%RPI_IP_ADDR%       sh /usr/bin/run_gdb_server.sh
