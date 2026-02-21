#!/bin/bash

# --- CONFIGURAÇÃO ---
DOCKER_USER="kailima"      # Seu nome de usuário no Docker Hub
SERVICE_NAME="titlis-operator"  # Nome do seu serviço
IMAGE_NAME="${DOCKER_USER}/${SERVICE_NAME}" # Repositório completo

# Gera a tag de versão com base na data e hora (Ex: 20251215-1907)
VERSION_TAG=$(date +%Y%m%d-%H%M)

echo "--- Iniciando o processo de Build, Tag e Push para ${IMAGE_NAME} ---"
echo "Versão de Tag gerada: ${VERSION_TAG}"

# 1. BUILD
# Assumimos que seu Dockerfile está no diretório atual (./)
echo -e "\n[1/3] Construindo a imagem..."
# O "." indica que o Dockerfile está no diretório atual
docker build -t ${IMAGE_NAME}:${VERSION_TAG} .

if [ $? -ne 0 ]; then
    echo "❌ ERRO: O Build falhou. Saindo."
    exit 1
fi

# 2. TAG (Tag 'latest')
# Cria a tag 'latest' para facilitar o deploy e uso da imagem mais recente
echo -e "\n[2/3] Taggeando a imagem com 'latest'..."
docker tag ${IMAGE_NAME}:${VERSION_TAG} ${IMAGE_NAME}:latest

# 3. PUSH (Envio para o Docker Hub)
# Nota: Você deve estar logado no Docker Hub (docker login)
echo -e "\n[3/3] Enviando as tags ${VERSION_TAG} e latest para o Docker Hub..."

# Envia a tag de versão
docker push ${IMAGE_NAME}:${VERSION_TAG}

# Verifica se o push da versão falhou
if [ $? -ne 0 ]; then
    echo "❌ ERRO: O Push da tag de versão falhou. Saindo."
    exit 1
fi

# Envia a tag 'latest'
docker push ${IMAGE_NAME}:latest

# Verifica se o push do latest falhou
if [ $? -ne 0 ]; then
    echo "❌ ERRO: O Push da tag 'latest' falhou. Saindo."
    exit 1
fi

echo -e "\n✅ SUCESSO! Imagem enviada para o Docker Hub:"
echo "   - ${IMAGE_NAME}:${VERSION_TAG}"
echo "   - ${IMAGE_NAME}:latest"