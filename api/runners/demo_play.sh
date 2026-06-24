#!/usr/bin/env bash
# Demo playbook output — mimics ansible PLAY/TASK structure with delays so the
# live-streaming UI can be tested without a real ansible setup.
set -u
LABEL="${1:-demo}"

echo "PLAY [${LABEL}] *********************************************************"
sleep 0.3

echo "TASK [Gathering Facts] *************************************************"
sleep 0.4
echo "ok: [localhost]"
sleep 0.2

echo "TASK [checkout : clone repository] ************************************"
sleep 0.5
echo "changed: [localhost] => cloned branch main"
sleep 0.2

echo "TASK [build : install dependencies] **********************************"
sleep 0.4
echo "changed: [localhost] => npm install (1243 packages)"
sleep 0.3

echo "TASK [build : compile application] ***********************************"
sleep 0.5
echo "ok: [localhost] => vite build for production"
echo "ok: [localhost] => dist/assets/app.abc123.js 245.3 KB"
sleep 0.3

echo "TASK [package : create tarball] **************************************"
sleep 0.4
echo "changed: [localhost] => redvrm-agent.1.0.5.tar.gz"
sleep 0.2

echo "TASK [nexus : upload artifact] ***************************************"
sleep 0.5
echo "changed: [localhost] => uploaded to dev-artifacts/frontend/"
sleep 0.2

echo "PLAY RECAP ***********************************************************"
echo "localhost : ok=7 changed=4 unreachable=0 failed=0"
exit 0
