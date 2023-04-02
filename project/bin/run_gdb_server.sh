#!/bin/sh

killall gdbserver
nohup gdbserver :5000 /usr/bin/StudentContest > sc.out 2> sc.err < /dev/null &