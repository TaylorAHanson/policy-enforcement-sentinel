from app.providers.databricks.handlers.base import (
    BaseResourceHandler,
    SupportsAnnotate,
    SupportsCertification,
    SupportsDelete,
    SupportsDisable,
    SupportsQuarantine,
    SupportsRevokeAccess,
    SupportsTerminate,
    SupportsThrottle,
    supported_methods,
    supports,
)
from app.providers.databricks.handlers.app_handler import AppResourceHandler
from app.providers.databricks.handlers.cluster_handler import ClusterResourceHandler
from app.providers.databricks.handlers.dashboard_handler import DashboardResourceHandler
from app.providers.databricks.handlers.dataset_handler import DatasetResourceHandler
from app.providers.databricks.handlers.genie_space_handler import GenieSpaceResourceHandler
from app.providers.databricks.handlers.job_handler import JobResourceHandler
from app.providers.databricks.handlers.lakebase_handler import LakebaseResourceHandler
from app.providers.databricks.handlers.model_serving_handler import (
    ModelServingEndpointResourceHandler,
)
from app.providers.databricks.handlers.notebook_handler import NotebookResourceHandler
from app.providers.databricks.handlers.pipeline_handler import PipelineResourceHandler
from app.providers.databricks.handlers.service_principal_handler import (
    ServicePrincipalResourceHandler,
)
from app.providers.databricks.handlers.sql_warehouse_handler import SqlWarehouseResourceHandler
from app.providers.databricks.handlers.volume_handler import VolumeResourceHandler

#: Resource type (as it appears in the Rego input document) -> handler class.
#: The scan engine builds handlers from this, so adding a resource type here is
#: all it takes to bring it into scope.
HANDLER_REGISTRY = {
    "cluster": ClusterResourceHandler,
    "job": JobResourceHandler,
    "sql_warehouse": SqlWarehouseResourceHandler,
    "app": AppResourceHandler,
    "dashboard": DashboardResourceHandler,
    "genie_space": GenieSpaceResourceHandler,
    "service_principal": ServicePrincipalResourceHandler,
    "notebook": NotebookResourceHandler,
    "storage": VolumeResourceHandler,
    "dataset": DatasetResourceHandler,
    "model_serving_endpoint": ModelServingEndpointResourceHandler,
    "pipeline": PipelineResourceHandler,
    "lakebase_instance": LakebaseResourceHandler,
}

__all__ = [
    "BaseResourceHandler",
    "SupportsAnnotate",
    "SupportsCertification",
    "SupportsDelete",
    "SupportsDisable",
    "SupportsQuarantine",
    "SupportsRevokeAccess",
    "SupportsTerminate",
    "SupportsThrottle",
    "supported_methods",
    "supports",
    "HANDLER_REGISTRY",
    "AppResourceHandler",
    "ClusterResourceHandler",
    "DashboardResourceHandler",
    "DatasetResourceHandler",
    "GenieSpaceResourceHandler",
    "JobResourceHandler",
    "LakebaseResourceHandler",
    "ModelServingEndpointResourceHandler",
    "NotebookResourceHandler",
    "PipelineResourceHandler",
    "ServicePrincipalResourceHandler",
    "SqlWarehouseResourceHandler",
    "VolumeResourceHandler",
]
