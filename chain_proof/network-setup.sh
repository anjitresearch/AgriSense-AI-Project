#!/bin/bash
# ==============================================================
#  CHAIN-PROOF™ — Hyperledger Fabric Network Setup Script
#  Deploys a local test network with 2 Orgs and 1 Channel ("agrifood")
#  Requires: Docker, Docker Compose, Hyperledger Fabric Binaries
# ==============================================================

set -e

CHANNEL_NAME="agrifood"
CHAINCODE_NAME="farmTraceability"
CHAINCODE_PATH="../chaincode/"
CHAINCODE_LANG="node"
CHAINCODE_VERSION="1.0"

echo "=============================================================="
echo " Starting CHAIN-PROOF™ Network Setup (Hyperledger Fabric v2.4)"
echo "=============================================================="

# This script assumes it sits next to the fabric-samples directory 
# or that you have cloned fabric-samples into a standard location.
# For demo purposes, we orchestrate the standard test-network script.

if [ ! -d "fabric-samples/test-network" ]; then
    echo "Downloading Fabric Samples (v2.4.9)..."
    curl -sSLO https://raw.githubusercontent.com/hyperledger/fabric/main/scripts/install-fabric.sh && chmod +x install-fabric.sh
    ./install-fabric.sh docker samples binary 2.4.9 1.5.5
fi

cd fabric-samples/test-network

echo "1. Tearing down any previous network..."
./network.sh down

echo "2. Bringing up network with 2 Orgs and creating channel '${CHANNEL_NAME}'..."
./network.sh up createChannel -c ${CHANNEL_NAME} -ca

echo "3. Deploying Chaincode '${CHAINCODE_NAME}' to channel '${CHANNEL_NAME}'..."
# Ensure dependencies are installed in chaincode directory before packaging
(cd ../../chaincode && npm install)

./network.sh deployCC -ccn ${CHAINCODE_NAME} \
                      -ccp ../../chaincode \
                      -ccl ${CHAINCODE_LANG} \
                      -ccv ${CHAINCODE_VERSION} \
                      -c ${CHANNEL_NAME}

echo "=============================================================="
echo "✅ CHAIN-PROOF™ Network is UP and Chaincode is DEPLOYED!"
echo "   Channel:   ${CHANNEL_NAME}"
echo "   Chaincode: ${CHAINCODE_NAME}"
echo "=============================================================="
