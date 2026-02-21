# Quickstart Titlis


1. Crie namespace e secret com as chaves do Datadog:


kubectl create ns titlis-system || true
kubectl create secret generic titlis-datadog-keys \
  -n titlis-system \
  --from-literal=api-key=0d36c05b3a6f6588a5fadd6796af0d46 \
  --from-literal=app-key=7afa4e9f4bd9c0b41042f3247a022e7d63035377

2. adicionar secrets do slack:
# Slack App Configuration (OAuth)
SLACK_ENABLED=true
SLACK_CLIENT_ID=10343045942535.10356470117638
SLACK_CLIENT_SECRET=c816b36c2f58831eb9f249fd8162cd90
SLACK_SIGNING_SECRET=a650686388ac8757198a5bdd7018d92c
SLACK_VERIFICATION_TOKEN=l7npWNNiJtfTkgWW1LSHkZ1k

# Bot Token (obtido após instalação do App)
SLACK_BOT_TOKEN=xapp-1-A0AAGDU3FJS-10352146467171-3b6c03a32d7861d782461c2435dbc5b89238b99b69382c47cbe1d8cec5e00635


3. Instale o chart:


helm upgrade --install titlis-operator /home/kailima/codes/titlis-operator/charts/titlis-operator -n titlis