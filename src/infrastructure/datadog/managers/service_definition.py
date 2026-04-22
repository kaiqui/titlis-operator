from typing import Any, Dict, Optional

from src.infrastructure.datadog.client import DatadogClientBase
from src.utils.json_logger import get_logger


class ServiceDefinitionManager(DatadogClientBase):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        from datadog_api_client.v2.api.software_catalog_api import SoftwareCatalogApi

        self.api = SoftwareCatalogApi(self.api_client)
        self.logger = get_logger(self.__class__.__name__)

    def get_single_service_definition(
        self, service_name: str
    ) -> Optional[Dict[str, Any]]:
        attempts = [
            lambda: self.api.list_catalog_entity(
                filter_name=service_name, filter_kind="service", page_limit=5
            ),
            lambda: self.api.list_catalog_entity(
                filter_ref=f"service:{service_name}", page_limit=5
            ),
        ]
        for attempt_idx, call in enumerate(attempts):
            try:
                response = call()
                data_list = getattr(response, "data", None) or []

                self.logger.info(
                    "Software Catalog response",
                    extra={
                        "service_name": service_name,
                        "attempt": attempt_idx,
                        "data_count": len(data_list),
                        "data_types": [type(d).__name__ for d in data_list[:3]],
                    },
                )

                if not data_list:
                    continue

                entity = self._find_entity_by_name(data_list, service_name)
                if entity is None:
                    self.logger.info(
                        "Nenhuma entidade com nome exato encontrado",
                        extra={
                            "service_name": service_name,
                            "candidates": [
                                getattr(getattr(d, "attributes", None), "name", "?")
                                for d in data_list[:5]
                            ],
                        },
                    )
                    continue

                attrs = getattr(entity, "attributes", None)
                if attrs is None:
                    continue

                schema: Dict[str, Any] = {
                    "dd_service": getattr(attrs, "name", service_name),
                    "description": getattr(attrs, "description", None),
                    "team": getattr(attrs, "owner", None),
                    "tier": None,
                    "tags": list(getattr(attrs, "tags", None) or []),
                    "schema_version": getattr(attrs, "api_version", "v3"),
                }

                self.logger.info(
                    "Serviço encontrado no Software Catalog",
                    extra={"service_name": service_name, "schema": schema},
                )
                return {"data": {"attributes": {"schema": schema}}}

            except Exception:
                self.logger.exception(
                    "Erro ao buscar serviço no Software Catalog",
                    extra={"service_name": service_name, "attempt": attempt_idx},
                )

        self.logger.warning(
            "Serviço não encontrado no Software Catalog após todas as tentativas",
            extra={"service_name": service_name},
        )
        return None

    def _find_entity_by_name(self, data_list: Any, service_name: str) -> Optional[Any]:
        lower_name = service_name.lower()
        for entity in data_list:
            attrs = getattr(entity, "attributes", None)
            if attrs is None:
                continue
            name = getattr(attrs, "name", None) or ""
            if name.lower() == lower_name:
                return entity
        if len(data_list) == 1:
            return data_list[0]
        return None
