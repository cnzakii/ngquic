#!/bin/bash
# The runner passes ROLE, TESTCASE, REQUESTS, SSLKEYLOGFILE and QLOGDIR, and
# mounts /certs, /www and /downloads; peer.py exits 127 for unsupported tests.
/setup.sh

if [ "$ROLE" == "client" ]; then
    /wait-for-it.sh sim:57832 -s -t 30
    exec /venv/bin/python /peer.py client --output /downloads $CLIENT_PARAMS
elif [ "$ROLE" == "server" ]; then
    exec /venv/bin/python /peer.py server --port 443 --cert /certs/cert.pem \
        --key /certs/priv.key --root /www $SERVER_PARAMS
fi
