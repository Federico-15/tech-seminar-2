"""
K8s GPU 스케줄러 (v8)

CRITICAL 감지 시: vllm-4b replicas 0 → vllm-8b replicas 1
분석 완료 시:     vllm-8b replicas 0 → vllm-4b replicas 1

vllm-4b와 vllm-8b가 동일한 GPU 노드에 있으므로
VRAM(23GB)이 부족해 두 Pod를 동시에 띄울 수 없습니다.
4B를 먼저 내려 VRAM을 반환한 뒤 8B를 올려야 합니다.
"""
import logging

from kubernetes import client, config as k8s_config
from kubernetes.client.exceptions import ApiException

from config.settings import settings

logger = logging.getLogger(__name__)


def _get_apps_v1() -> client.AppsV1Api:
    """클러스터 내부면 in-cluster config, 외부면 kubeconfig를 사용합니다."""
    try:
        k8s_config.load_incluster_config()
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
    return client.AppsV1Api()


def _scale(deployment_name: str, replicas: int) -> None:
    apps_v1 = _get_apps_v1()
    try:
        apps_v1.patch_namespaced_deployment_scale(
            name=deployment_name,
            namespace=settings.k8s_namespace,
            body={"spec": {"replicas": replicas}},
        )
        logger.info(f"[K8sScaler] {deployment_name} → replicas={replicas}")
    except ApiException as e:
        logger.error(f"[K8sScaler] scale 실패 ({deployment_name}): {e.status} {e.reason}")
        raise


def switch_to_8b() -> None:
    """
    4B Pod를 내리고 8B Pod를 올립니다.

    순서가 중요합니다:
    1. 4B 먼저 종료 → VRAM 11GB 반환
    2. 8B 시작      → VRAM 19GB 로딩 (~2분)
    이 사이에 Kafka 큐가 로그를 보관합니다.
    """
    if not settings.k8s_enabled:
        logger.info("[K8sScaler] K8S_ENABLED=false — Pod 교체 스킵 (로컬 개발 모드)")
        return

    logger.info("[K8sScaler] 4B → 8B 전환 시작")
    _scale(settings.k8s_vllm_4b_deployment, 0)
    _scale(settings.k8s_vllm_8b_deployment, 1)
    logger.info("[K8sScaler] 8B Pod 생성 요청 완료. 로딩까지 약 2분 소요.")


def switch_to_4b() -> None:
    """
    8B Pod를 내리고 4B Pod를 복귀시킵니다.
    kafka_consumer.py에서 모든 메시지 처리 완료 후 호출합니다.
    """
    if not settings.k8s_enabled:
        logger.info("[K8sScaler] K8S_ENABLED=false — Pod 복귀 스킵 (로컬 개발 모드)")
        return

    logger.info("[K8sScaler] 8B → 4B 복귀 시작")
    _scale(settings.k8s_vllm_8b_deployment, 0)
    _scale(settings.k8s_vllm_4b_deployment, 1)
    logger.info("[K8sScaler] 4B Pod 복귀 완료. 상시 감시 재개.")
