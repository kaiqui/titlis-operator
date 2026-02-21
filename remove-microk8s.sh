#!/bin/bash
set -e

echo "=== RESET COMPLETO DO MICROK8S (WSL2) ==="

WIN_USER="kaiqu"
WIN_KUBE_DIR="/mnt/c/Users/${WIN_USER}/.kube"
WIN_KUBE_CONFIG="${WIN_KUBE_DIR}/config"

# 1. Parar microk8s se existir
echo "Parando MicroK8s (se existir)..."
sudo snap stop microk8s 2>/dev/null || true

# 2. Remover MicroK8s
echo "Removendo MicroK8s..."
sudo snap remove microk8s --purge 2>/dev/null || true

# 3. Limpeza residual (WSL2-safe)
echo "Limpando resíduos..."
sudo rm -rf /var/snap/microk8s
sudo rm -rf /var/snap/microk8s-common
sudo rm -rf /snap/microk8s
sudo rm -rf ~/.kube
sudo rm -rf /etc/cni
sudo rm -rf /var/lib/cni
sudo rm -rf /var/lib/kubelet
# 4. Reinstalar
echo "Reinstalando..."
sudo snap install microk8s --classic

# 5. Configurar permissões
echo "Configurando usuário..."
sudo usermod -a -G microk8s $USER

echo "⚠️  IMPORTANTE:"
echo "Feche este terminal e abra outro para aplicar o grupo 'microk8s'"

# 6. Iniciar
echo "Iniciando MicroK8s..."
sudo snap start microk8s
sleep 30

# 7. Verificar
echo "Verificando instalação..."
microk8s status --wait-ready

# 8. Habilitar addons essenciais
echo "Habilitando addons..."
microk8s enable dns
sleep 10
microk8s enable storage
sleep 10

# 9. Configurar kubeconfig para Windows
echo "Configurando kubeconfig para Windows (usuário: kaiqu)..."
mkdir -p "${WIN_KUBE_DIR}"
microk8s config > "${WIN_KUBE_CONFIG}"
chmod 600 "${WIN_KUBE_CONFIG}"

# 10. Teste rápido
echo "Testando cluster..."
microk8s kubectl get nodes
microk8s kubectl run test --image=nginx --restart=Never

echo "=== COMPLETO ==="
echo "MicroK8s reinstalado com sucesso no WSL2"
echo "Kubeconfig em: ${WIN_KUBE_CONFIG}"
